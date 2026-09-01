"""PostgreSQL task queue core for the four frozen generation task types.

Public transaction contract
---------------------------

``TaskQueue`` methods receive an ``AsyncSession`` and do not commit it.  They
flush their changes and return a ``TaskChange``/``EnqueueResult``.  The caller
must commit the session and may then call ``publish_committed(result)``.  This
keeps WS/event publication after the database commit.

The main public methods are:

* ``acquire_advisory_lock(connection) -> bool`` and
  ``release_advisory_lock(connection) -> bool``; use a dedicated physical
  connection held for the whole process lifetime.
* ``recover_running_tasks(session) -> list[TaskChange]``
* ``claim_next(session) -> TaskChange | None``
* ``heartbeat(session, task_id, progress=None) -> TaskChange``
* ``complete(session, task_id) -> TaskChange``
* ``fail(session, task_id, error) -> TaskChange``
* ``request_cancel(session, task_id) -> TaskChange`` and
  ``cancel_safe_point(session, task_id) -> TaskChange``
* ``enqueue(session, type, target_id, payload, request_id=None) -> EnqueueResult``
* ``find_request(session, request_id) -> Task | None``

``run_worker`` is a single serial consumer and ``run_with_lock`` combines the
dedicated session lock, startup recovery, and that consumer.  It accepts
handlers only from its caller; normal application startup does not register
any handler.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import traceback
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, TypeAlias

from sqlalchemy import and_, case, delete, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.db.session import engine
from app.models import Clip, Task
from app.tasks.events import TaskEvent, TaskEventPublisher


logger = logging.getLogger("app.tasks.queue")

TaskType: TypeAlias = Literal[
    "gen_assets",
    "gen_shots",
    "gen_asset_image",
    "gen_clip_video",
]
TaskStatus: TypeAlias = Literal[
    "queued", "running", "done", "failed", "canceled"
]

TASK_TYPES: tuple[TaskType, ...] = (
    "gen_assets",
    "gen_shots",
    "gen_asset_image",
    "gen_clip_video",
)
TASK_STATUSES: tuple[TaskStatus, ...] = (
    "queued",
    "running",
    "done",
    "failed",
    "canceled",
)
ACTIVE_STATUSES: tuple[TaskStatus, ...] = ("queued", "running")
HEARTBEAT_INTERVAL_SECONDS = 10.0
# Stable project-specific PostgreSQL session advisory lock key.
ADVISORY_LOCK_KEY = 0x41495F4452414D41
REQUEST_ID_LOCK_NAMESPACE = "ai_drama_studio:request_id:"

_PAYLOAD_KEYS = frozenset(
    {"input_snapshot", "input_hash", "source_revisions"}
)
_REQUEST_CONSTRAINT = "uq_tasks_active_request_id"
_TARGET_CONSTRAINT = "uq_tasks_active_target"


class TaskQueueError(RuntimeError):
    """Base class for expected queue-domain errors."""


class TaskValidationError(ValueError):
    """A boundary value violates the frozen task contract."""


class TaskNotFoundError(TaskQueueError):
    """The requested task id does not exist."""


class TaskConflictError(TaskQueueError):
    """A valid request is blocked by an existing task or terminal state."""

    def __init__(
        self,
        message: str,
        *,
        existing_task: Task | None = None,
        conflict_kind: str = "conflict",
    ) -> None:
        super().__init__(message)
        self.existing_task = existing_task
        self.conflict_kind = conflict_kind


class TaskRequestConflictError(TaskConflictError):
    """A request id exists but its type, target, or payload differs."""

    def __init__(self, message: str, *, existing_task: Task | None = None) -> None:
        super().__init__(
            message,
            existing_task=existing_task,
            conflict_kind="request_id",
        )


class TaskTargetConflictError(TaskConflictError):
    """An active gen_assets/gen_shots task already owns the target."""

    def __init__(self, message: str, *, existing_task: Task | None = None) -> None:
        super().__init__(
            message,
            existing_task=existing_task,
            conflict_kind="target",
        )


class AdvisoryLockNotAcquired(TaskQueueError):
    """Raised by ``run_with_lock`` when another process owns the lock."""


@dataclass(slots=True)
class TaskChange:
    """One conditional mutation and its optional post-commit event."""

    task: Task | None
    changed: bool
    event: TaskEvent | None = None


@dataclass(slots=True)
class EnqueueResult:
    """The result of an enqueue or request-id idempotency lookup."""

    task: Task
    created: bool
    event: TaskEvent | None = None

    @property
    def changed(self) -> bool:
        """Whether a new database row was created."""

        return self.created


@dataclass(frozen=True, slots=True)
class ClaimedTask:
    """Immutable worker input copied from the claimed row's payload."""

    id: int
    type: TaskType
    target_id: int
    request_id: str | None
    payload: dict[str, Any]


TaskHandler: TypeAlias = Callable[
    [ClaimedTask, "WorkerContext"], Awaitable[None]
]


def validate_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and deep-copy the immutable three-field task payload.

    The top-level contract is intentionally closed.  Business-specific input
    belongs inside ``input_snapshot`` or ``source_revisions`` and is not
    interpreted by this module.
    """

    if not isinstance(payload, Mapping):
        raise TaskValidationError("payload must be a JSON object")
    copied = copy.deepcopy(dict(payload))
    if set(copied) != _PAYLOAD_KEYS:
        raise TaskValidationError(
            "payload must contain exactly input_snapshot, input_hash, "
            "and source_revisions"
        )
    if not isinstance(copied["input_snapshot"], dict):
        raise TaskValidationError("payload.input_snapshot must be an object")
    if copied["input_hash"] is not None and not isinstance(
        copied["input_hash"], str
    ):
        raise TaskValidationError("payload.input_hash must be a string or null")
    if not isinstance(copied["source_revisions"], dict):
        raise TaskValidationError("payload.source_revisions must be an object")
    try:
        json.dumps(copied, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise TaskValidationError("payload must contain JSON values") from exc
    return copied


def normalize_request_id(request_id: str | None) -> str | None:
    """Trim a request id and enforce the frozen one-to-128 character range."""

    if request_id is None:
        return None
    if not isinstance(request_id, str):
        raise TaskValidationError("request_id must be a string or null")
    normalized = request_id.strip()
    if not 1 <= len(normalized) <= 128:
        raise TaskValidationError("request_id must contain 1..128 characters")
    return normalized


def _validate_task_type(task_type: str) -> TaskType:
    if task_type not in TASK_TYPES:
        raise TaskValidationError(f"unsupported task type: {task_type}")
    return task_type  # type: ignore[return-value]


def _validate_target_id(target_id: int) -> int:
    if isinstance(target_id, bool) or not isinstance(target_id, int):
        raise TaskValidationError("target_id must be an integer")
    return target_id


def _validate_progress(progress: float) -> float:
    if isinstance(progress, bool) or not isinstance(progress, (int, float)):
        raise TaskValidationError("progress must be a number between 0 and 1")
    numeric = float(progress)
    if not math.isfinite(numeric) or not 0 <= numeric <= 1:
        raise TaskValidationError("progress must be a number between 0 and 1")
    return numeric


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _event_for(task: Task, message: str) -> TaskEvent:
    return TaskEvent(
        task_id=task.id,
        type=task.type,
        status=task.status,
        progress=task.progress,
        message=message,
    )


def _format_error(error: BaseException | str) -> str:
    if isinstance(error, str):
        message = error
    else:
        message = "".join(traceback.format_exception(error))
    if not message.strip():
        raise TaskValidationError("task failure error_msg must be non-empty")
    return message


def _constraint_name(error: IntegrityError) -> str | None:
    original = error.orig
    candidates = (
        original,
        getattr(original, "__cause__", None),
        getattr(original, "__context__", None),
    )
    for candidate in candidates:
        if candidate is None:
            continue
        name = getattr(candidate, "constraint_name", None)
        if name is not None:
            return name
        diagnostic = getattr(candidate, "diag", None)
        name = getattr(diagnostic, "constraint_name", None)
        if name is not None:
            return name
    return None


async def _read_task(
    session: AsyncSession, task_id: int, *, for_update: bool = False
) -> Task | None:
    statement = (
        select(Task)
        .where(Task.id == task_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def _require_task(session: AsyncSession, task_id: int) -> Task:
    task = await _read_task(session, task_id)
    if task is None:
        raise TaskNotFoundError(f"task {task_id} does not exist")
    return task


async def aggregate_clip_generation_state(
    session: AsyncSession, clip_id: int
) -> str:
    """Project one Clip state from its non-canceled video tasks."""

    clip = await session.scalar(
        select(Clip)
        .where(Clip.id == clip_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if clip is None:
        raise TaskQueueError(f"clip {clip_id} does not exist")

    priority = case(
        (Task.status == "running", 0),
        (Task.status == "queued", 1),
        else_=2,
    )
    result = await session.execute(
        select(Task.status)
        .where(
            Task.type == "gen_clip_video",
            Task.target_id == clip_id,
            Task.status.in_(("running", "queued", "done", "failed")),
        )
        .order_by(
            priority,
            Task.finished_at.desc().nulls_last(),
            Task.id.desc(),
        )
        .limit(1)
    )
    selected_status = result.scalar_one_or_none()
    if selected_status == "running":
        projected_state = "generating"
    elif selected_status == "queued":
        projected_state = "queued"
    elif selected_status == "done":
        projected_state = "ready"
    elif selected_status == "failed":
        projected_state = "failed"
    else:
        projected_state = "empty"

    if clip.generation_state != projected_state:
        clip.generation_state = projected_state
        clip.updated_at = _utc_now()
        await session.flush()
    return projected_state


class TaskQueue:
    """PostgreSQL queue operations with no implicit transaction commits."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        *,
        publisher: TaskEventPublisher | None = None,
        lock_key: int = ADVISORY_LOCK_KEY,
    ) -> None:
        if not -(2**63) <= lock_key < 2**63:
            raise TaskValidationError("lock_key must fit PostgreSQL bigint")
        self.session_factory = session_factory
        self.publisher = publisher
        self.lock_key = lock_key

    async def acquire_advisory_lock(self, connection: AsyncConnection) -> bool:
        """Try the stable session advisory lock; return false when busy.

        ``connection`` must stay checked out from the pool for the full worker
        lifetime.  Committing the implicit transaction does not release a
        PostgreSQL session advisory lock while the physical connection stays
        open.
        """

        result = await connection.execute(
            text("SELECT pg_try_advisory_lock(:lock_key)"),
            {"lock_key": self.lock_key},
        )
        acquired = bool(result.scalar_one())
        await connection.commit()
        return acquired

    async def release_advisory_lock(self, connection: AsyncConnection) -> bool:
        """Release the session advisory lock on its owning connection."""

        result = await connection.execute(
            text("SELECT pg_advisory_unlock(:lock_key)"),
            {"lock_key": self.lock_key},
        )
        released = bool(result.scalar_one())
        await connection.commit()
        return released

    async def recover_running_tasks(
        self, session: AsyncSession
    ) -> list[TaskChange]:
        """Conditionally fail every leftover running task in one transaction."""

        now = _utc_now()
        result = await session.execute(
            update(Task)
            .where(Task.status == "running")
            .values(
                status="failed",
                error_msg="server restarted",
                finished_at=now,
            )
            .returning(Task)
        )
        tasks = list(result.scalars().all())
        for clip_id in sorted(
            {task.target_id for task in tasks if task.type == "gen_clip_video"}
        ):
            await aggregate_clip_generation_state(session, clip_id)
        return [
            TaskChange(task=task, changed=True, event=_event_for(task, "任务失败：server restarted"))
            for task in tasks
        ]

    async def claim_next(self, session: AsyncSession) -> TaskChange | None:
        """Claim the lowest-id queued task with ``FOR UPDATE SKIP LOCKED``."""

        result = await session.execute(
            select(Task)
            .where(Task.status == "queued")
            .order_by(Task.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        queued = result.scalar_one_or_none()
        if queued is None:
            return None

        now = _utc_now()
        changed = await session.execute(
            update(Task)
            .where(Task.id == queued.id, Task.status == "queued")
            .values(status="running", started_at=now, heartbeat_at=now)
            .returning(Task)
        )
        task = changed.scalar_one_or_none()
        if task is None:
            current = await _require_task(session, queued.id)
            return TaskChange(task=current, changed=False)
        await self._project_task_clip(session, task)
        return TaskChange(task=task, changed=True, event=_event_for(task, "任务执行中"))

    async def heartbeat(
        self,
        session: AsyncSession,
        task_id: int,
        progress: float | None = None,
    ) -> TaskChange:
        """Update a running task heartbeat every ten seconds, optionally progress."""

        numeric_progress = (
            None if progress is None else _validate_progress(progress)
        )
        current = await _read_task(session, task_id, for_update=True)
        if current is None:
            raise TaskNotFoundError(f"task {task_id} does not exist")
        if current.status != "running":
            return TaskChange(task=current, changed=False)

        progress_changed = (
            numeric_progress is not None and current.progress != numeric_progress
        )
        values: dict[str, Any] = {"heartbeat_at": _utc_now()}
        if numeric_progress is not None:
            values["progress"] = numeric_progress
        result = await session.execute(
            update(Task)
            .where(Task.id == task_id, Task.status == "running")
            .values(**values)
            .returning(Task)
        )
        task = result.scalar_one_or_none()
        if task is None:
            current = await _require_task(session, task_id)
            return TaskChange(task=current, changed=False)
        await self._project_task_clip(session, task)
        event = _event_for(task, "任务执行中") if progress_changed else None
        return TaskChange(task=task, changed=True, event=event)

    async def complete(self, session: AsyncSession, task_id: int) -> TaskChange:
        """Conditionally transition running to done exactly once."""

        result = await session.execute(
            update(Task)
            .where(
                Task.id == task_id,
                Task.status == "running",
                Task.cancel_requested_at.is_(None),
            )
            .values(
                status="done",
                progress=1.0,
                error_msg=None,
                finished_at=_utc_now(),
            )
            .returning(Task)
        )
        task = result.scalar_one_or_none()
        if task is None:
            current = await _require_task(session, task_id)
            return TaskChange(task=current, changed=False)
        await self._project_task_clip(session, task)
        return TaskChange(task=task, changed=True, event=_event_for(task, "任务完成"))

    async def fail(
        self,
        session: AsyncSession,
        task_id: int,
        error: BaseException | str,
    ) -> TaskChange:
        """Conditionally transition running to failed with the complete error."""

        error_msg = _format_error(error)
        result = await session.execute(
            update(Task)
            .where(Task.id == task_id, Task.status == "running")
            .values(status="failed", error_msg=error_msg, finished_at=_utc_now())
            .returning(Task)
        )
        task = result.scalar_one_or_none()
        if task is None:
            current = await _require_task(session, task_id)
            return TaskChange(task=current, changed=False)
        await self._project_task_clip(session, task)
        if isinstance(error, BaseException) and error.__traceback__ is not None:
            logger.error(
                "task failed id=%s type=%s target_id=%s",
                task.id,
                task.type,
                task.target_id,
                exc_info=(type(error), error, error.__traceback__),
            )
        else:
            logger.error(
                "task failed id=%s type=%s target_id=%s error_msg=%s",
                task.id,
                task.type,
                task.target_id,
                error_msg,
            )
        return TaskChange(task=task, changed=True, event=_event_for(task, f"任务失败：{error_msg}"))

    async def request_cancel(
        self, session: AsyncSession, task_id: int
    ) -> TaskChange:
        """Cancel queued atomically or mark running for its first safe point."""

        now = _utc_now()
        result = await session.execute(
            update(Task)
            .where(
                Task.id == task_id,
                or_(
                    Task.status == "queued",
                    and_(
                        Task.status == "running",
                        Task.cancel_requested_at.is_(None),
                    ),
                ),
            )
            .values(
                status=case(
                    (Task.status == "queued", "canceled"),
                    else_=Task.status,
                ),
                finished_at=case(
                    (Task.status == "queued", now),
                    else_=Task.finished_at,
                ),
                cancel_requested_at=case(
                    (Task.status == "running", now),
                    else_=Task.cancel_requested_at,
                ),
            )
            .returning(Task)
        )
        task = result.scalar_one_or_none()
        if task is not None:
            await self._project_task_clip(session, task)
            message = "任务已取消" if task.status == "canceled" else "已请求取消"
            return TaskChange(task=task, changed=True, event=_event_for(task, message))

        current = await _require_task(session, task_id)
        if current.status in {"done", "failed"}:
            raise TaskConflictError(
                f"task {task_id} is already terminal",
                existing_task=current,
                conflict_kind="terminal_cancel",
            )
        return TaskChange(task=current, changed=False)

    async def cancel_safe_point(
        self, session: AsyncSession, task_id: int
    ) -> TaskChange:
        """Conditionally turn a running task with a cancel request into canceled."""

        result = await session.execute(
            update(Task)
            .where(
                Task.id == task_id,
                Task.status == "running",
                Task.cancel_requested_at.is_not(None),
            )
            .values(status="canceled", finished_at=_utc_now())
            .returning(Task)
        )
        task = result.scalar_one_or_none()
        if task is None:
            current = await _require_task(session, task_id)
            return TaskChange(task=current, changed=False)
        await self._project_task_clip(session, task)
        return TaskChange(task=task, changed=True, event=_event_for(task, "任务已取消"))

    async def find_request(
        self, session: AsyncSession, request_id: str
    ) -> Task | None:
        """Find a normalized request id in any task state, including terminal."""

        normalized = normalize_request_id(request_id)
        if normalized is None:
            raise TaskValidationError("request_id is required")
        result = await session.execute(
            select(Task)
            .where(Task.request_id == normalized)
            .order_by(Task.id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def acquire_request_id_lock(
        self, session: AsyncSession, request_id: str
    ) -> str:
        """Acquire the transaction-scoped lock for one normalized request id."""

        normalized = normalize_request_id(request_id)
        if normalized is None:
            raise TaskValidationError("request_id is required")
        await session.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended(:lock_namespace || :request_id, 0))"
            ),
            {
                "lock_namespace": REQUEST_ID_LOCK_NAMESPACE,
                "request_id": normalized,
            },
        )
        return normalized

    async def enqueue(
        self,
        session: AsyncSession,
        task_type: str,
        target_id: int,
        payload: Mapping[str, Any],
        request_id: str | None = None,
    ) -> EnqueueResult:
        """Insert one queued task after request and active-target checks.

        The existing PostgreSQL partial unique indexes remain the concurrent
        final arbiter.  A recognized unique violation is rolled back only to
        its savepoint, the winner is read, and the insert is not retried.
        """

        checked_type = _validate_task_type(task_type)
        checked_target = _validate_target_id(target_id)
        checked_payload = validate_payload(payload)
        normalized_request = normalize_request_id(request_id)

        if normalized_request is not None:
            existing = await self.find_request(session, normalized_request)
            if existing is not None:
                self._ensure_request_match(
                    existing,
                    checked_type,
                    checked_target,
                    checked_payload,
                )
                return EnqueueResult(task=existing, created=False)

        if checked_type in {"gen_assets", "gen_shots"}:
            active = await self._find_active_target(
                session, checked_type, checked_target
            )
            if active is not None:
                raise TaskTargetConflictError(
                    f"active task already owns type={checked_type} target_id={checked_target}",
                    existing_task=active,
                )

        task = Task(
            type=checked_type,
            target_id=checked_target,
            request_id=normalized_request,
            payload=checked_payload,
            status="queued",
            progress=0.0,
        )
        try:
            async with session.begin_nested():
                session.add(task)
                await session.flush()
        except IntegrityError as exc:
            constraint = _constraint_name(exc)
            if constraint not in {_REQUEST_CONSTRAINT, _TARGET_CONSTRAINT}:
                raise
            if constraint == _REQUEST_CONSTRAINT:
                winner = (
                    None
                    if normalized_request is None
                    else await self.find_request(session, normalized_request)
                )
                if winner is not None:
                    self._ensure_request_match(
                        winner,
                        checked_type,
                        checked_target,
                        checked_payload,
                    )
                    return EnqueueResult(task=winner, created=False)
                raise TaskRequestConflictError(
                    "request_id uniqueness conflict has no visible winner"
                ) from exc

            winner = await self._find_active_target(
                session, checked_type, checked_target
            )
            raise TaskTargetConflictError(
                f"active task already owns type={checked_type} target_id={checked_target}",
                existing_task=winner,
            ) from exc

        await self._project_task_clip(session, task)
        return EnqueueResult(
            task=task,
            created=True,
            event=_event_for(task, "任务已排队"),
        )

    async def record_failed(
        self,
        session: AsyncSession,
        task_type: str,
        target_id: int,
        payload: Mapping[str, Any],
        error: BaseException | str,
        request_id: str | None = None,
    ) -> EnqueueResult:
        """Insert one terminal failed task inside the caller's transaction."""

        checked_type = _validate_task_type(task_type)
        checked_target = _validate_target_id(target_id)
        checked_payload = validate_payload(payload)
        normalized_request = normalize_request_id(request_id)
        error_msg = _format_error(error)
        task = Task(
            type=checked_type,
            target_id=checked_target,
            request_id=normalized_request,
            payload=checked_payload,
            status="failed",
            progress=0.0,
            error_msg=error_msg,
            finished_at=_utc_now(),
        )
        session.add(task)
        await session.flush()
        await self._project_task_clip(session, task)
        return EnqueueResult(
            task=task,
            created=True,
            event=_event_for(task, f"任务失败：{error_msg}"),
        )

    async def publish_committed(
        self,
        result: TaskChange | EnqueueResult,
        publisher: TaskEventPublisher | None = None,
    ) -> None:
        """Publish a mutation event after the caller has committed its session."""

        event = result.event
        callback = publisher or self.publisher
        if event is not None and callback is not None:
            await callback(event)

    async def run_worker(
        self,
        *,
        handlers: Mapping[str, TaskHandler],
        stop_event: asyncio.Event | None = None,
        poll_interval: float = 0.5,
        stop_when_idle: bool = False,
    ) -> None:
        """Run one serial worker using only caller-supplied handlers."""

        factory = self._require_factory()
        if poll_interval < 0:
            raise TaskValidationError("poll_interval must not be negative")
        stop = stop_event or asyncio.Event()
        while not stop.is_set():
            async with factory() as session:
                async with session.begin():
                    claimed = await self.claim_next(session)
            if claimed is None:
                if stop_when_idle:
                    return
                await self._wait_for_stop(stop, poll_interval)
                continue
            if claimed.task is None:
                raise TaskQueueError("claim returned no task")
            if not claimed.changed:
                continue
            await self.publish_committed(claimed)
            await self._execute_claimed(claimed.task, handlers)

    async def run_with_lock(
        self,
        *,
        handlers: Mapping[str, TaskHandler],
        stop_event: asyncio.Event | None = None,
        poll_interval: float = 0.5,
        stop_when_idle: bool = False,
    ) -> None:
        """Acquire lock, recover, then run one worker and release in order."""

        factory = self._require_factory()
        lock_connection = await engine.connect()
        acquired = False
        try:
            acquired = await self.acquire_advisory_lock(lock_connection)
            if not acquired:
                raise AdvisoryLockNotAcquired(
                    "task worker advisory lock is already held"
                )
            async with factory() as recovery_session:
                async with recovery_session.begin():
                    recovery = await self.recover_running_tasks(recovery_session)
            for change in recovery:
                await self.publish_committed(change)
            await self.run_worker(
                handlers=handlers,
                stop_event=stop_event,
                poll_interval=poll_interval,
                stop_when_idle=stop_when_idle,
            )
        finally:
            if acquired:
                await self.release_advisory_lock(lock_connection)
            await lock_connection.close()

    async def _find_active_target(
        self, session: AsyncSession, task_type: TaskType, target_id: int
    ) -> Task | None:
        result = await session.execute(
            select(Task)
            .where(
                Task.type == task_type,
                Task.target_id == target_id,
                Task.status.in_(ACTIVE_STATUSES),
            )
            .order_by(Task.id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _project_task_clip(
        session: AsyncSession, task: Task
    ) -> None:
        if task.type == "gen_clip_video":
            await aggregate_clip_generation_state(session, task.target_id)

    @staticmethod
    def _ensure_request_match(
        existing: Task,
        task_type: TaskType,
        target_id: int,
        payload: dict[str, Any],
    ) -> None:
        if (
            existing.type != task_type
            or existing.target_id != target_id
            or existing.payload != payload
        ):
            raise TaskRequestConflictError(
                "request_id is already bound to a different task request",
                existing_task=existing,
            )

    def _require_factory(self) -> async_sessionmaker[AsyncSession]:
        if self.session_factory is None:
            raise TaskQueueError(
                "a session_factory is required for worker execution"
            )
        return self.session_factory

    async def _execute_claimed(
        self,
        task: Task,
        handlers: Mapping[str, TaskHandler],
    ) -> None:
        factory = self._require_factory()
        work_item = ClaimedTask(
            id=task.id,
            type=_validate_task_type(task.type),
            target_id=task.target_id,
            request_id=task.request_id,
            payload=copy.deepcopy(task.payload),
        )
        handler = handlers.get(work_item.type)
        if handler is None:
            await self._fail_after_commit(
                task.id,
                RuntimeError(
                    f"no task handler registered for type {work_item.type}"
                ),
            )
            return

        context = WorkerContext(self, work_item, factory)
        heartbeat_stop = asyncio.Event()
        handler_task = asyncio.create_task(
            handler(work_item, context),
            name=f"task-handler-{task.id}",
        )
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(task.id, heartbeat_stop),
            name=f"task-heartbeat-{task.id}",
        )
        try:
            done, _ = await asyncio.wait(
                {handler_task, heartbeat_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            heartbeat_error = self._task_error(heartbeat_task)
            handler_error = self._task_error(handler_task)
            if heartbeat_error is not None:
                if not handler_task.done():
                    handler_task.cancel()
                    await self._await_cancelled_task(handler_task)
                await self._fail_after_commit(task.id, heartbeat_error)
                return
            if handler_error is not None:
                await self._stop_heartbeat(heartbeat_stop, heartbeat_task)
                await self._fail_after_commit(task.id, handler_error)
                return
            if handler_task not in done:
                raise TaskQueueError("worker task coordination ended unexpectedly")
            await self._stop_heartbeat(heartbeat_stop, heartbeat_task)
            safe_point = await self._cancel_safe_point_after_commit(task.id)
            if safe_point.task is not None and safe_point.task.status == "canceled":
                return
            completed = await self._complete_after_commit(task.id)
            if (
                not completed.changed
                and completed.task is not None
                and completed.task.status == "running"
                and completed.task.cancel_requested_at is not None
            ):
                await self._cancel_safe_point_after_commit(task.id)
        except asyncio.CancelledError:
            handler_task.cancel()
            heartbeat_stop.set()
            await self._await_cancelled_task(handler_task)
            await self._await_cancelled_task(heartbeat_task)
            raise
        finally:
            if not heartbeat_task.done():
                heartbeat_stop.set()
                await self._await_cancelled_task(heartbeat_task)

    async def _heartbeat_loop(
        self, task_id: int, stop_event: asyncio.Event
    ) -> None:
        while True:
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS
                )
                return
            except asyncio.TimeoutError:
                factory = self._require_factory()
                async with factory() as session:
                    async with session.begin():
                        change = await self.heartbeat(session, task_id)
                if not change.changed:
                    raise TaskQueueError(
                        f"heartbeat condition lost for task {task_id}"
                    )

    async def _complete_after_commit(self, task_id: int) -> TaskChange:
        factory = self._require_factory()
        async with factory() as session:
            async with session.begin():
                change = await self.complete(session, task_id)
        await self.publish_committed(change)
        return change

    async def _fail_after_commit(
        self, task_id: int, error: BaseException | str
    ) -> TaskChange:
        factory = self._require_factory()
        async with factory() as session:
            async with session.begin():
                change = await self.fail(session, task_id, error)
        await self.publish_committed(change)
        return change

    async def _cancel_safe_point_after_commit(self, task_id: int) -> TaskChange:
        factory = self._require_factory()
        async with factory() as session:
            async with session.begin():
                change = await self.cancel_safe_point(session, task_id)
        await self.publish_committed(change)
        return change

    @staticmethod
    async def _stop_heartbeat(
        stop_event: asyncio.Event, heartbeat_task: asyncio.Task[None]
    ) -> None:
        stop_event.set()
        if not heartbeat_task.done():
            await TaskQueue._await_cancelled_task(heartbeat_task)
        else:
            error = TaskQueue._task_error(heartbeat_task)
            if error is not None:
                raise error

    @staticmethod
    def _task_error(task: asyncio.Task[Any]) -> BaseException | None:
        if not task.done() or task.cancelled():
            return None
        return task.exception()

    @staticmethod
    async def _await_cancelled_task(task: asyncio.Task[Any]) -> None:
        if task.done():
            if task.cancelled():
                return
            error = task.exception()
            if error is not None:
                raise error
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return

    @staticmethod
    async def _wait_for_stop(stop_event: asyncio.Event, timeout: float) -> None:
        if timeout == 0:
            await asyncio.sleep(0)
            return
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return


class WorkerContext:
    """Database-backed controls exposed to an explicitly injected handler."""

    def __init__(
        self,
        queue: TaskQueue,
        task: ClaimedTask,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.queue = queue
        self.task = task
        self._session_factory = session_factory

    @property
    def payload(self) -> dict[str, Any]:
        """Return a copy of the claimed payload, never a live entity lookup."""

        return copy.deepcopy(self.task.payload)

    async def heartbeat(self, progress: float | None = None) -> TaskChange:
        """Commit one explicit heartbeat/progress mutation."""

        async with self._session_factory() as session:
            async with session.begin():
                change = await self.queue.heartbeat(session, self.task.id, progress)
        await self.queue.publish_committed(change)
        return change

    async def cancel_safe_point(self) -> TaskChange:
        """Check the cancel marker and commit a safe-point cancellation."""

        async with self._session_factory() as session:
            async with session.begin():
                change = await self.queue.cancel_safe_point(session, self.task.id)
        await self.queue.publish_committed(change)
        return change

    async def cancel_requested(self) -> bool:
        """Read the current cancel marker for the claimed task."""

        async with self._session_factory() as session:
            result = await session.execute(
                select(Task.status, Task.cancel_requested_at).where(
                    Task.id == self.task.id
                )
            )
            row = result.one_or_none()
        if row is None:
            raise TaskNotFoundError(f"task {self.task.id} does not exist")
        return row.status == "running" and row.cancel_requested_at is not None
