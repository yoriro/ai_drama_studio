import asyncio
import logging
from typing import Annotated

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
    queue = bus.subscribe_queue()
    try:
        while True:
            receive_task = asyncio.create_task(websocket.receive())
            event_task = asyncio.create_task(queue.get())
            done, pending = await asyncio.wait(
                {receive_task, event_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for pending_task in pending:
                pending_task.cancel()
            completed = done.pop()
            if completed is receive_task:
                message = completed.result()
                if message["type"] == "websocket.disconnect":
                    break
                continue
            await websocket.send_json(completed.result())
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(queue)
