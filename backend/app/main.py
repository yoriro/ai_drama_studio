import asyncio
import logging
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Protocol

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
from app.api.shots import router as shots_router
from app.api.tasks import router as tasks_router, ws_router as tasks_ws_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.db.session import async_session_factory, dispose_engine, engine
from app.integrations.comfy import ComfyClient
from app.integrations.workflow_binding import (
    DEFAULT_BINDING_PATH,
    WorkflowBindingError,
    load_binding_snapshot,
)
from app.services.system_health import build_health_response
from app.services.vllm import VLLMClient
from app.tasks.events import EventBus
from app.tasks.gen_assets import gen_assets_handler
from app.tasks.gen_shots import gen_shots_handler
from app.tasks.queue import AdvisoryLockNotAcquired, TaskHandler, TaskQueue
from app.services.trash import cleanup_expired_trash, run_trash_cleanup_loop

logging.basicConfig(level=logging.INFO, stream=sys.stdout)


class HealthClient(Protocol):
    async def health(self) -> object:
        ...


HealthClientFactory = Callable[[str], HealthClient]


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
    lock_connection = None
    worker_stop = asyncio.Event()
    worker_task: asyncio.Task[None] | None = None
    cleanup_task: asyncio.Task[None] | None = None
    lock_acquired = False
    application.state.task_queue = queue
    application.state.task_runtime = None
    application.state.task_worker_stop = worker_stop
    try:
        lock_connection = await engine.connect()
        try:
            lock_acquired = await queue.acquire_advisory_lock(lock_connection)
            if not lock_acquired:
                raise AdvisoryLockNotAcquired(
                    "task worker advisory lock is already held"
                )
        except AdvisoryLockNotAcquired:
            logging.getLogger("app.lifecycle").exception(
                "Application startup rejected: project worker advisory lock is held"
            )
            raise
        app_settings = application.state.settings
        try:
            binding_snapshot = load_binding_snapshot(
                application.state.binding_path,
                backend_root=application.state.binding_root,
            )
        except WorkflowBindingError:
            logging.getLogger("app.lifecycle").exception(
                "Application startup rejected: invalid Z-Image workflow binding"
            )
            raise
        application.state.workflow_binding_snapshot = binding_snapshot
        application.state.vllm_client = application.state.vllm_client_factory(
            str(app_settings.VLLM_BASE_URL)
        )
        application.state.comfy_client = application.state.comfy_client_factory(
            str(app_settings.COMFY_BASE_URL)
        )
        startup_health = await build_health_response(
            vllm_probe=application.state.vllm_client.health,
            comfy_probe=application.state.comfy_client.health,
            workflow_hash=binding_snapshot.workflow_hash,
        )
        lifecycle_logger = logging.getLogger("app.lifecycle")
        lifecycle_logger.info(
            "Startup health probes completed: vllm=%s comfy=%s workflow_binding=valid",
            startup_health.vllm.status,
            startup_health.comfy.status,
        )
        for component_name, component in (
            ("vLLM", startup_health.vllm),
            ("ComfyUI", startup_health.comfy),
        ):
            if component.status == "unhealthy":
                lifecycle_logger.warning(
                    "%s startup health probe unhealthy: %s",
                    component_name,
                    component.message,
                )
        if application.state.startup_prepare is not None:
            await application.state.startup_prepare()
        try:
            cleanup_expired_trash(
                app_settings.DATA_DIR, app_settings.TRASH_RETENTION_HOURS
            )
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
            run_trash_cleanup_loop(
                app_settings.DATA_DIR, app_settings.TRASH_RETENTION_HOURS
            )
        )
        worker_task = asyncio.create_task(
            queue.run_worker(
                handlers=application.state.task_handlers,
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
                    await queue.release_advisory_lock(lock_connection)
            finally:
                try:
                    if lock_connection is not None:
                        await lock_connection.close()
                finally:
                    await dispose_engine()


def create_app(
    *,
    task_handlers: Mapping[str, TaskHandler] | None = None,
    startup_prepare: Callable[[], Awaitable[None]] | None = None,
    binding_path: str | Path | None = None,
    binding_root: str | Path | None = None,
    vllm_client_factory: HealthClientFactory | None = None,
    comfy_client_factory: HealthClientFactory | None = None,
) -> FastAPI:
    application = FastAPI(title="AI Drama Studio API", lifespan=lifespan)
    application.state.settings = settings
    handlers: dict[str, TaskHandler] = {
        "gen_assets": gen_assets_handler,
        "gen_shots": gen_shots_handler,
    }
    handlers.update(task_handlers or {})
    application.state.task_handlers = handlers
    application.state.startup_prepare = startup_prepare
    application.state.binding_path = (
        DEFAULT_BINDING_PATH if binding_path is None else Path(binding_path)
    )
    application.state.binding_root = (
        None if binding_root is None else Path(binding_root)
    )
    application.state.vllm_client_factory = (
        VLLMClient if vllm_client_factory is None else vllm_client_factory
    )
    application.state.comfy_client_factory = (
        ComfyClient if comfy_client_factory is None else comfy_client_factory
    )
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
    application.include_router(shots_router, prefix="/api")
    application.include_router(media_router)
    application.include_router(prompt_templates_router, prefix="/api")
    application.include_router(tasks_router, prefix="/api")
    application.include_router(tasks_ws_router)
    register_exception_handlers(application)
    return application


app = create_app()
