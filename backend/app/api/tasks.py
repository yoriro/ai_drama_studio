import asyncio
import logging
from typing import Any, Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket
from fastapi.websockets import WebSocketDisconnect
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import Task
from app.schemas.tasks import TaskResponse, TaskStatus, TaskType
from app.tasks.events import EventBus
from app.tasks.queue import TaskConflictError, TaskNotFoundError, TaskQueue


router = APIRouter(tags=["tasks"])
ws_router = APIRouter(tags=["tasks"])
logger = logging.getLogger("app.api.tasks")
WS_SEND_TIMEOUT_SECONDS = 10.0


async def _cancel_and_await(task: asyncio.Task[Any]) -> None:
    if not task.done():
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


async def _close_transport(websocket: WebSocket, *, reason: str) -> None:
    logger.warning("Task websocket closing code=1013 reason=%s", reason)
    try:
        await websocket.close(code=1013)
    except (OSError, RuntimeError, WebSocketDisconnect) as exc:
        logger.warning(
            "Task websocket close already unavailable reason=%s error=%s",
            reason,
            exc,
        )


async def _interrupt_running_comfy_task(request: Request, task: Task) -> None:
    snapshot = task.payload["input_snapshot"]
    prompt_id = snapshot["comfy_prompt_id"]
    try:
        await request.app.state.comfy_client.interrupt(prompt_id)
    except (httpx.HTTPError, OSError, TimeoutError) as exc:
        logger.warning(
            "Comfy interrupt best-effort call failed task_id=%s prompt_id=%s error=%s",
            task.id,
            prompt_id,
            exc,
        )


@router.get("/tasks", response_model=list[TaskResponse])
async def read_tasks(
    status_filter: Annotated[
        TaskStatus | None, Query(alias="status")
    ] = None,
    task_type: Annotated[TaskType | None, Query(alias="type")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    session: AsyncSession = Depends(get_session),
) -> list[Task]:
    statement = select(Task)
    if status_filter is not None:
        statement = statement.where(Task.status == status_filter)
    if task_type is not None:
        statement = statement.where(Task.type == task_type)
    statement = statement.order_by(desc(Task.id)).limit(limit)
    result = await session.execute(statement)
    return list(result.scalars().all())


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def read_task(
    task_id: int,
    session: AsyncSession = Depends(get_session),
) -> Task:
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/tasks/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(
    task_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Task:
    body = await request.body()
    if body.strip():
        raise HTTPException(status_code=422, detail="Cancel request body must be empty")

    queue: TaskQueue = request.app.state.task_queue
    try:
        async with session.begin():
            change = await queue.request_cancel(session, task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TaskConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await queue.publish_committed(change)
    if change.task is None:
        raise HTTPException(status_code=500, detail="Task cancellation returned no task")
    if (
        change.changed
        and change.task.status == "running"
        and change.task.type in {"gen_asset_image", "gen_clip_video"}
    ):
        await _interrupt_running_comfy_task(request, change.task)
    return change.task


@ws_router.websocket("/ws/tasks")
async def task_events(websocket: WebSocket) -> None:
    await websocket.accept()
    bus: EventBus = websocket.app.state.task_event_bus
    overflow_event = asyncio.Event()
    queue = bus.subscribe_queue(overflow_event=overflow_event)
    active_tasks: set[asyncio.Task[Any]] = set()
    try:
        while True:
            receive_task = asyncio.create_task(websocket.receive())
            event_task = asyncio.create_task(queue.get())
            overflow_task = asyncio.create_task(overflow_event.wait())
            active_tasks = {receive_task, event_task, overflow_task}
            done, pending = await asyncio.wait(
                active_tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for pending_task in pending:
                await _cancel_and_await(pending_task)
            active_tasks = set()

            message: dict[str, Any] | None = None
            disconnected = False
            if receive_task in done:
                try:
                    message = receive_task.result()
                except WebSocketDisconnect:
                    disconnected = True
                else:
                    disconnected = message["type"] == "websocket.disconnect"

            event_payload: dict[str, object] | None = None
            if event_task in done:
                event_payload = event_task.result()
            overflowed = False
            if overflow_task in done:
                overflow_task.result()
                overflowed = True
            if disconnected:
                break
            if overflowed:
                await _close_transport(websocket, reason="subscription_overflow")
                break
            if event_payload is None:
                continue

            send_task = asyncio.create_task(websocket.send_json(event_payload))
            send_overflow_task = asyncio.create_task(overflow_event.wait())
            active_tasks = {send_task, send_overflow_task}
            done, _pending = await asyncio.wait(
                active_tasks,
                timeout=WS_SEND_TIMEOUT_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                await _cancel_and_await(send_task)
                await _cancel_and_await(send_overflow_task)
                active_tasks = set()
                await _close_transport(websocket, reason="send_timeout")
                break

            if send_overflow_task in done and send_task not in done:
                send_overflow_task.result()
                await _cancel_and_await(send_task)
                active_tasks = set()
                await _close_transport(websocket, reason="subscription_overflow")
                break

            await _cancel_and_await(send_overflow_task)
            active_tasks = {send_task}
            try:
                send_task.result()
            except (OSError, RuntimeError, WebSocketDisconnect) as exc:
                active_tasks = set()
                logger.warning(
                    "Task websocket send failed reason=send_error error=%s", exc
                )
                await _close_transport(websocket, reason="send_error")
                break
            active_tasks = set()
    except WebSocketDisconnect:
        pass
    finally:
        for task in active_tasks:
            await _cancel_and_await(task)
        bus.unsubscribe(queue)
