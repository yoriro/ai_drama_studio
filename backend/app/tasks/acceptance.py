"""Explicit, non-production C004 queue acceptance driver.

The normal FastAPI application never imports this module and never registers
the controlled handlers below.  Every scenario uses the real PostgreSQL
``tasks`` table and the same queue primitives as the application.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Awaitable, Callable

from sqlalchemy import delete, select, text

from app.db.session import async_session_factory, engine
from app.models import Task
from app.tasks.events import EventBus
from app.tasks.queue import (
    HEARTBEAT_INTERVAL_SECONDS,
    TASK_STATUSES,
    TASK_TYPES,
    ClaimedTask,
    TaskChange,
    TaskConflictError,
    TaskQueue,
    TaskRequestConflictError,
    TaskTargetConflictError,
    TaskValidationError,
    WorkerContext,
)


def payload(label: str) -> dict[str, object]:
    return {
        "input_snapshot": {"label": label},
        "input_hash": None,
        "source_revisions": {},
    }


async def clear_tasks() -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(Task))


async def command_lock_lifecycle() -> None:
    queue = TaskQueue(async_session_factory)
    owner = await engine.connect()
    probe = await engine.connect()
    owner_acquired = False
    probe_acquired = False
    try:
        owner_pid_result = await owner.execute(text("SELECT pg_backend_pid()"))
        probe_pid_result = await probe.execute(text("SELECT pg_backend_pid()"))
        owner_pid = int(owner_pid_result.scalar_one())
        probe_pid = int(probe_pid_result.scalar_one())
        assert owner_pid != probe_pid

        owner_acquired = await queue.acquire_advisory_lock(owner)
        assert owner_acquired
        blocked_result = await probe.execute(
            text("SELECT pg_try_advisory_lock(:lock_key)"),
            {"lock_key": queue.lock_key},
        )
        blocked = not bool(blocked_result.scalar_one())
        await probe.commit()
        assert blocked

        owner_released = await queue.release_advisory_lock(owner)
        owner_acquired = False
        assert owner_released
        after_release_result = await probe.execute(
            text("SELECT pg_try_advisory_lock(:lock_key)"),
            {"lock_key": queue.lock_key},
        )
        probe_acquired = bool(after_release_result.scalar_one())
        await probe.commit()
        assert probe_acquired
        probe_released = await probe.execute(
            text("SELECT pg_advisory_unlock(:lock_key)"),
            {"lock_key": queue.lock_key},
        )
        probe_acquired = False
        await probe.commit()
        assert bool(probe_released.scalar_one())
        print(
            json.dumps(
                {
                    "owner_backend_pid": owner_pid,
                    "probe_backend_pid": probe_pid,
                    "owner_acquired": True,
                    "probe_blocked_while_owner_holds": blocked,
                    "probe_acquired_after_owner_release": True,
                    "probe_released": True,
                },
                ensure_ascii=False,
            )
        )
    finally:
        if probe_acquired:
            await queue.release_advisory_lock(probe)
        if owner_acquired:
            await queue.release_advisory_lock(owner)
        await probe.close()
        await owner.close()


async def insert_task(
    task_type: str,
    target_id: int,
    status: str = "queued",
    request_id: str | None = None,
    task_payload: dict[str, object] | None = None,
) -> Task:
    async with async_session_factory() as session:
        async with session.begin():
            task = Task(
                type=task_type,
                target_id=target_id,
                request_id=request_id,
                payload=task_payload or payload(str(target_id)),
                status=status,
                progress=0.0 if status == "queued" else 1.0 if status == "done" else 0.2,
            )
            session.add(task)
            await session.flush()
        return task


async def read_task(task_id: int) -> Task:
    async with async_session_factory() as session:
        task = await session.get(Task, task_id)
    assert task is not None
    return task


async def show_tasks() -> list[dict[str, object]]:
    async with async_session_factory() as session:
        result = await session.execute(select(Task).order_by(Task.id))
        return [
            {
                "id": task.id,
                "type": task.type,
                "target_id": task.target_id,
                "request_id": task.request_id,
                "status": task.status,
                "progress": task.progress,
                "error_msg": task.error_msg,
                "heartbeat_at": task.heartbeat_at.isoformat()
                if task.heartbeat_at
                else None,
                "cancel_requested_at": task.cancel_requested_at.isoformat()
                if task.cancel_requested_at
                else None,
                "created_at": task.created_at.isoformat()
                if task.created_at
                else None,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "finished_at": task.finished_at.isoformat()
                if task.finished_at
                else None,
                "payload": task.payload,
            }
            for task in result.scalars()
        ]


async def commit_claim(queue: TaskQueue) -> TaskChange | None:
    async with async_session_factory() as session:
        async with session.begin():
            change = await queue.claim_next(session)
    if change is not None:
        await queue.publish_committed(change)
    return change


async def commit_transition(
    queue: TaskQueue,
    method: str,
    task_id: int,
    *args: object,
) -> TaskChange:
    async with async_session_factory() as session:
        async with session.begin():
            change = await getattr(queue, method)(session, task_id, *args)
    await queue.publish_committed(change)
    return change


async def commit_enqueue(
    queue: TaskQueue,
    task_type: str,
    target_id: int,
    task_payload: dict[str, object],
    request_id: str | None = None,
) -> tuple[Task, bool]:
    async with async_session_factory() as session:
        async with session.begin():
            result = await queue.enqueue(
                session,
                task_type,
                target_id,
                task_payload,
                request_id,
            )
    await queue.publish_committed(result)
    return result.task, result.created


async def command_contract() -> None:
    queue = TaskQueue()
    queue_payload = payload("contract")
    print(
        json.dumps(
            {
                "types": list(TASK_TYPES),
                "statuses": list(TASK_STATUSES),
                "payload": sorted(queue_payload),
                "explicit": True,
            },
            ensure_ascii=False,
        )
    )
    from app.tasks.queue import validate_payload

    validate_payload(queue_payload)


async def command_recover() -> None:
    await clear_tasks()
    running = await insert_task("gen_assets", 1, "running")
    queued = await insert_task("gen_shots", 2)
    queue = TaskQueue(async_session_factory)
    async with async_session_factory() as session:
        async with session.begin():
            changes = await queue.recover_running_tasks(session)
    for change in changes:
        await queue.publish_committed(change)
    print(
        json.dumps(
            {
                "recovered": len(changes),
                "running_id": running.id,
                "queued_id": queued.id,
                "tasks": await show_tasks(),
            },
            ensure_ascii=False,
        )
    )


async def command_claim(count: int, claimers: int) -> None:
    await clear_tasks()
    for index in range(count):
        await insert_task("gen_assets", index + 1)
    queue = TaskQueue(async_session_factory)
    claimed: list[tuple[int, int]] = []
    claimed_lock = asyncio.Lock()

    async def claimant(number: int) -> None:
        while True:
            change = await commit_claim(queue)
            if change is None or change.task is None:
                return
            async with claimed_lock:
                claimed.append((number, change.task.id))
            await asyncio.sleep(0.01)

    await asyncio.gather(*(claimant(index) for index in range(claimers)))
    print(
        json.dumps(
            {
                "claimed": claimed,
                "unique_ids": len({task_id for _, task_id in claimed}),
                "count": len(claimed),
            },
            ensure_ascii=False,
        )
    )


async def command_transition_race() -> None:
    await clear_tasks()
    task = await insert_task("gen_assets", 1)
    queue = TaskQueue(async_session_factory)
    change = await commit_claim(queue)
    assert change is not None
    results = await asyncio.gather(
        commit_transition(queue, "complete", task.id),
        commit_transition(queue, "fail", task.id, "race failure"),
    )
    print(
        json.dumps(
            {"changed": [result.changed for result in results], "tasks": await show_tasks()},
            ensure_ascii=False,
        )
    )


async def command_heartbeat(seconds: int) -> None:
    await clear_tasks()
    task = await insert_task("gen_assets", 1)
    queue = TaskQueue(async_session_factory)
    claimed = await commit_claim(queue)
    assert claimed is not None and claimed.task is not None
    heartbeat_times = [claimed.task.heartbeat_at]
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        await asyncio.sleep(min(HEARTBEAT_INTERVAL_SECONDS, deadline - time.monotonic()))
        change = await commit_transition(queue, "heartbeat", task.id)
        if change.changed and change.task is not None:
            heartbeat_times.append(change.task.heartbeat_at)
    current = await read_task(task.id)
    print(
        json.dumps(
            {
                "task_id": task.id,
                "status": current.status,
                "heartbeat_times": [stamp.isoformat() for stamp in heartbeat_times if stamp],
                "heartbeat_count": len(heartbeat_times),
                "seconds": seconds,
            },
            ensure_ascii=False,
        )
    )


async def failing_handler(task: ClaimedTask, context: WorkerContext) -> None:
    del task, context
    raise RuntimeError("controlled acceptance failure with task context")


async def success_handler(task: ClaimedTask, context: WorkerContext) -> None:
    del task
    await context.heartbeat(0.5)
    await asyncio.sleep(0.05)


async def demo_success_handler(
    task: ClaimedTask, context: WorkerContext
) -> None:
    del task
    await context.heartbeat(0.5)
    await asyncio.sleep(1.0)


async def event_success_handler(
    task: ClaimedTask, context: WorkerContext
) -> None:
    del task, context
    await asyncio.sleep(0.02)


async def cancel_handler(task: ClaimedTask, context: WorkerContext) -> None:
    del task
    while not await context.cancel_requested():
        await asyncio.sleep(0.05)
    await context.cancel_safe_point()


async def wait_for_terminal(task_id: int) -> Task:
    while True:
        task = await read_task(task_id)
        if task.status in {"done", "failed", "canceled"}:
            return task
        await asyncio.sleep(0.05)


async def run_worker_until(
    queue: TaskQueue,
    handlers: dict[str, Callable[[ClaimedTask, WorkerContext], Awaitable[None]]],
    task_ids: list[int],
) -> None:
    stop = asyncio.Event()
    worker = asyncio.create_task(
        queue.run_worker(handlers=handlers, stop_event=stop, poll_interval=0.05)
    )
    await asyncio.gather(*(wait_for_terminal(task_id) for task_id in task_ids))
    stop.set()
    await worker


async def collect_task_events(
    event_queue: asyncio.Queue[dict[str, object]], task_id: int
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    while True:
        event = await asyncio.wait_for(event_queue.get(), timeout=5)
        if event["task_id"] != task_id:
            raise AssertionError(f"unexpected event for task {task_id}: {event}")
        assert set(event) == {"task_id", "type", "status", "progress", "message"}
        events.append(event)
        if event["status"] in {"done", "failed", "canceled"}:
            return events


async def command_events() -> None:
    await clear_tasks()
    event_bus = EventBus()
    event_queue = event_bus.subscribe_queue()
    queue = TaskQueue(async_session_factory, publisher=event_bus.publish)
    stop = asyncio.Event()
    worker = asyncio.create_task(
        queue.run_worker(
            handlers={
                "gen_assets": event_success_handler,
                "gen_shots": failing_handler,
            },
            stop_event=stop,
            poll_interval=0.01,
        )
    )
    try:
        success, _ = await commit_enqueue(
            queue, "gen_assets", 1, payload("events-success")
        )
        success_events = await collect_task_events(event_queue, success.id)
        failure, _ = await commit_enqueue(
            queue, "gen_shots", 2, payload("events-failure")
        )
        failure_events = await collect_task_events(event_queue, failure.id)

        assert [event["status"] for event in success_events] == [
            "queued",
            "running",
            "done",
        ]
        assert [event["status"] for event in failure_events] == [
            "queued",
            "running",
            "failed",
        ]
        assert success_events[0]["message"] == "任务已排队"
        assert success_events[1]["message"] == "任务执行中"
        assert success_events[2]["message"] == "任务完成"
        assert failure_events[0]["message"] == "任务已排队"
        assert failure_events[1]["message"] == "任务执行中"
        assert str(failure_events[2]["message"]).startswith("任务失败：")

        assert await commit_claim(queue) is None
        heartbeat_task = await insert_task("gen_assets", 3, status="running")
        heartbeat_change = await commit_transition(
            queue, "heartbeat", heartbeat_task.id
        )
        assert heartbeat_change.changed
        assert event_queue.empty()
        print(
            json.dumps(
                {
                    "success_events": success_events,
                    "failure_events": failure_events,
                    "unsuccessful_claim_published": False,
                    "heartbeat_only_published": False,
                },
                ensure_ascii=False,
            )
        )
    finally:
        stop.set()
        await worker
        event_bus.unsubscribe(event_queue)


async def command_fail_once() -> None:
    await clear_tasks()
    task = await insert_task("gen_assets", 1)
    queue = TaskQueue(async_session_factory)
    await run_worker_until(queue, {"gen_assets": failing_handler}, [task.id])
    print(json.dumps({"tasks": await show_tasks()}, ensure_ascii=False))


async def command_dedupe_target(concurrency: int) -> None:
    await clear_tasks()
    queue = TaskQueue(async_session_factory)

    async def attempt(task_type: str) -> str:
        try:
            await commit_enqueue(queue, task_type, 1, payload(task_type))
        except TaskTargetConflictError:
            return "conflict"
        return "created"

    results = await asyncio.gather(
        *(attempt("gen_assets") for _ in range(concurrency)),
        *(attempt("gen_shots") for _ in range(concurrency)),
    )
    print(json.dumps({"results": results, "tasks": await show_tasks()}, ensure_ascii=False))


async def command_allow_draws(count: int) -> None:
    await clear_tasks()
    queue = TaskQueue(async_session_factory)
    for task_type in ("gen_asset_image", "gen_clip_video"):
        for index in range(count):
            await commit_enqueue(queue, task_type, 1, payload(f"{task_type}-{index}"))
    print(json.dumps({"tasks": await show_tasks()}, ensure_ascii=False))


async def command_snapshot() -> None:
    await clear_tasks()
    queue = TaskQueue(async_session_factory)
    frozen = payload("before")
    task, created = await commit_enqueue(queue, "gen_assets", 1, frozen)
    frozen["input_snapshot"] = {"label": "after"}
    stored = await read_task(task.id)
    print(
        json.dumps(
            {"created": created, "stored_payload": stored.payload, "worker_payload": task.payload},
            ensure_ascii=False,
        )
    )


async def command_cancel_race() -> None:
    await clear_tasks()
    task = await insert_task("gen_assets", 1)
    queue = TaskQueue(async_session_factory)
    await commit_claim(queue)
    await commit_transition(queue, "request_cancel", task.id)
    results = await asyncio.gather(
        commit_transition(queue, "cancel_safe_point", task.id),
        commit_transition(queue, "complete", task.id),
    )
    print(
        json.dumps(
            {"changed": [result.changed for result in results], "tasks": await show_tasks()},
            ensure_ascii=False,
        )
    )


async def command_worker(count: int) -> None:
    await clear_tasks()
    tasks = [await insert_task("gen_assets", index + 1) for index in range(count)]
    failed = await insert_task("gen_shots", count + 1)
    queue = TaskQueue(async_session_factory)
    await run_worker_until(
        queue,
        {"gen_assets": success_handler, "gen_shots": failing_handler},
        [task.id for task in tasks] + [failed.id],
    )
    print(json.dumps({"tasks": await show_tasks()}, ensure_ascii=False))


async def command_dedupe_request(concurrency: int, states: str) -> None:
    await clear_tasks()
    queue = TaskQueue(async_session_factory)

    if states == "all":
        state_results: list[dict[str, object]] = []
        for index, task_status in enumerate(TASK_STATUSES):
            request_key = f"state-{task_status}"
            existing = await insert_task(
                "gen_assets",
                index + 1,
                task_status,
                request_key,
                payload(f"state-{task_status}"),
            )
            reused_task, created = await commit_enqueue(
                queue,
                "gen_assets",
                existing.target_id,
                payload(f"state-{task_status}"),
                request_key,
            )
            state_results.append(
                {
                    "state": task_status,
                    "existing_id": existing.id,
                    "returned_id": reused_task.id,
                    "created": created,
                }
            )
        print(json.dumps({"states": state_results}, ensure_ascii=False))
    elif states != "all":
        raise TaskValidationError("--states must be all")

    async def attempt() -> tuple[int, bool]:
        task, reused = await commit_enqueue(
            queue,
            "gen_assets",
            1000,
            payload("request"),
            " request-key ",
        )
        return task.id, reused

    results = await asyncio.gather(*(attempt() for _ in range(concurrency)))
    print(
        json.dumps(
            {"results": results, "tasks": await show_tasks()}, ensure_ascii=False
        )
    )


async def command_dedupe_request_conflicts() -> None:
    await clear_tasks()
    queue = TaskQueue(async_session_factory)
    await commit_enqueue(queue, "gen_assets", 1, payload("a"), "key")
    output: dict[str, str] = {}
    for name, values in {
        "type": ("gen_shots", 1, payload("a")),
        "target": ("gen_assets", 2, payload("a")),
        "payload": ("gen_assets", 1, payload("b")),
    }.items():
        try:
            await commit_enqueue(queue, values[0], values[1], values[2], "key")
        except TaskRequestConflictError:
            output[name] = "conflict"
    for invalid in (" ", "x" * 129):
        try:
            await commit_enqueue(queue, "gen_asset_image", 1, payload("x"), invalid)
        except TaskValidationError:
            output["invalid"] = "validation_error"
    print(json.dumps({"results": output, "tasks": await show_tasks()}, ensure_ascii=False))


async def drive_demo(application) -> None:
    while not hasattr(application.state, "task_event_bus"):
        await asyncio.sleep(0.05)
    event_bus: EventBus = application.state.task_event_bus
    while event_bus.subscriber_count == 0:
        await asyncio.sleep(0.05)
    await asyncio.sleep(2.0)

    queue: TaskQueue = application.state.task_queue
    success, _ = await commit_enqueue(
        queue,
        "gen_assets",
        910001,
        payload("explicit-demo-success"),
    )
    failure, _ = await commit_enqueue(
        queue,
        "gen_shots",
        910002,
        payload("explicit-demo-failure"),
    )
    print(
        json.dumps(
            {
                "ws_subscribers_confirmed": event_bus.subscriber_count,
                "task_ids": [success.id, failure.id],
                "message": "demo tasks enqueued; service remains active until stopped",
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


async def command_demo(host: str, port: int) -> None:
    import uvicorn

    from app.main import create_app

    async def prepare_demo() -> None:
        await clear_tasks()

    demo_app = create_app(
        task_handlers={
            "gen_assets": demo_success_handler,
            "gen_shots": failing_handler,
        },
        startup_prepare=prepare_demo,
    )
    driver = asyncio.create_task(drive_demo(demo_app))
    server = uvicorn.Server(
        uvicorn.Config(demo_app, host=host, port=port, log_level="info")
    )
    try:
        await server.serve()
    finally:
        if not driver.done():
            driver.cancel()
            await driver
        else:
            driver.result()


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(prog="python -m app.tasks.acceptance")
    subparsers = argument_parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("contract")
    subparsers.add_parser("recover")
    claim = subparsers.add_parser("claim")
    claim.add_argument("--count", type=int, default=3)
    claim.add_argument("--claimers", type=int, default=2)
    subparsers.add_parser("transition-race")
    heartbeat = subparsers.add_parser("heartbeat")
    heartbeat.add_argument("--seconds", type=int, default=22)
    subparsers.add_parser("fail-once")
    target = subparsers.add_parser("dedupe-target")
    target.add_argument("--concurrency", type=int, default=2)
    draws = subparsers.add_parser("allow-draws")
    draws.add_argument("--count", type=int, default=2)
    subparsers.add_parser("snapshot")
    subparsers.add_parser("cancel-race")
    worker = subparsers.add_parser("worker")
    worker.add_argument("--tasks", type=int, default=3)
    request = subparsers.add_parser("dedupe-request")
    request.add_argument("--concurrency", type=int, default=2)
    request.add_argument("--states", choices=("all",), default="all")
    subparsers.add_parser("dedupe-request-conflicts")
    subparsers.add_parser("events")
    subparsers.add_parser("lock-lifecycle")
    demo = subparsers.add_parser("demo")
    demo.add_argument("--host", default="127.0.0.1")
    demo.add_argument("--port", type=int, default=8000)
    return argument_parser


async def run(arguments: argparse.Namespace) -> None:
    commands: dict[str, Callable[[], Awaitable[None]]] = {
        "contract": command_contract,
        "recover": command_recover,
        "transition-race": command_transition_race,
        "fail-once": command_fail_once,
        "snapshot": command_snapshot,
        "cancel-race": command_cancel_race,
        "dedupe-request-conflicts": command_dedupe_request_conflicts,
        "events": command_events,
        "lock-lifecycle": command_lock_lifecycle,
    }
    if arguments.command == "claim":
        await command_claim(arguments.count, arguments.claimers)
    elif arguments.command == "heartbeat":
        await command_heartbeat(arguments.seconds)
    elif arguments.command == "dedupe-target":
        await command_dedupe_target(arguments.concurrency)
    elif arguments.command == "allow-draws":
        await command_allow_draws(arguments.count)
    elif arguments.command == "worker":
        await command_worker(arguments.tasks)
    elif arguments.command == "dedupe-request":
        await command_dedupe_request(arguments.concurrency, arguments.states)
    elif arguments.command == "demo":
        await command_demo(arguments.host, arguments.port)
    else:
        await commands[arguments.command]()


async def async_main(arguments: argparse.Namespace) -> None:
    try:
        await run(arguments)
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(async_main(parser().parse_args()))


if __name__ == "__main__":
    main()
