import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.datastructures import Headers
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response

from app.api.styles import router as styles_router
from app.api.system import router as system_router
from app.api.episodes import router as episodes_router
from app.api.assets import router as assets_router
from app.api.media import router as media_router
from app.api.projects import router as projects_router
from app.api.prompt_templates import router as prompt_templates_router
from app.api.tasks import router as tasks_router, ws_router as tasks_ws_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.db.session import async_session_factory, dispose_engine
from app.tasks.events import EventBus
from app.tasks.queue import AdvisoryLockNotAcquired, TaskQueue
from app.services.trash import cleanup_expired_trash, run_trash_cleanup_loop

logging.basicConfig(level=logging.INFO, stream=sys.stdout)


class StructuredCORSMiddleware(CORSMiddleware):
    def preflight_response(self, request_headers: Headers) -> Response:
        response = super().preflight_response(request_headers)
        if response.status_code != 400:
            return response

        headers = dict(response.headers)
        headers.pop("content-length", None)
        headers.pop("content-type", None)
        return JSONResponse(
            content={
                "detail": {
                    "code": "validation_error",
                    "message": response.body.decode("utf-8"),
                }
            },
            status_code=400,
            headers=headers,
        )


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    event_bus = EventBus()
    application.state.task_event_bus = event_bus
    queue = TaskQueue(async_session_factory, publisher=event_bus.publish)
    lock_session = async_session_factory()
    worker_stop = asyncio.Event()
    worker_task: asyncio.Task[None] | None = None
    cleanup_task: asyncio.Task[None] | None = None
    lock_acquired = False
    application.state.task_queue = queue
    application.state.task_runtime = None
    application.state.task_worker_stop = worker_stop
    try:
        try:
            lock_acquired = await queue.acquire_advisory_lock(lock_session)
            if not lock_acquired:
                raise AdvisoryLockNotAcquired(
                    "task worker advisory lock is already held"
                )
        except AdvisoryLockNotAcquired:
            logging.getLogger("app.lifecycle").exception(
                "Application startup rejected: project worker advisory lock is held"
            )
            raise
        try:
            cleanup_expired_trash(settings.DATA_DIR, settings.TRASH_RETENTION_HOURS)
        except OSError:
            logging.getLogger("app.trash").exception(
                "Initial trash cleanup failed"
            )
            raise
        async with async_session_factory() as recovery_session:
            async with recovery_session.begin():
                recovery = await queue.recover_running_tasks(recovery_session)
        for change in recovery:
            await queue.publish_committed(change)
        cleanup_task = asyncio.create_task(
            run_trash_cleanup_loop(settings.DATA_DIR, settings.TRASH_RETENTION_HOURS)
        )
        worker_task = asyncio.create_task(
            queue.run_worker(
                handlers={},
                stop_event=worker_stop,
                poll_interval=0.25,
            )
        )
        application.state.task_runtime = worker_task
        try:
            yield
        finally:
            if cleanup_task is not None:
                cleanup_task.cancel()
                try:
                    await cleanup_task
                except asyncio.CancelledError:
                    pass
    finally:
        try:
            worker_stop.set()
            if worker_task is not None:
                await worker_task
        finally:
            try:
                if lock_acquired:
                    await queue.release_advisory_lock(lock_session)
            finally:
                try:
                    await lock_session.close()
                finally:
                    await dispose_engine()


def create_app() -> FastAPI:
    application = FastAPI(title="AI Drama Studio API", lifespan=lifespan)
    application.state.settings = settings
    application.add_middleware(
        StructuredCORSMiddleware,
        allow_origin_regex=r"^http://(?:localhost|127\.0\.0\.1)(?::[0-9]+)?$",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(system_router, prefix="/api")
    application.include_router(styles_router, prefix="/api")
    application.include_router(projects_router, prefix="/api")
    application.include_router(episodes_router, prefix="/api")
    application.include_router(assets_router, prefix="/api")
    application.include_router(media_router)
    application.include_router(prompt_templates_router, prefix="/api")
    application.include_router(tasks_router, prefix="/api")
    application.include_router(tasks_ws_router)
    register_exception_handlers(application)
    return application


app = create_app()
