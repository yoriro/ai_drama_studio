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
from app.api.projects import router as projects_router
from app.api.prompt_templates import router as prompt_templates_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.db.session import dispose_engine

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
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
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
    application.include_router(prompt_templates_router, prefix="/api")
    register_exception_handlers(application)
    return application


app = create_app()
