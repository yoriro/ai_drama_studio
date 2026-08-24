import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.system import router as system_router
from app.core.config import settings
from app.core.errors import register_exception_handlers

logging.basicConfig(level=logging.INFO, stream=sys.stdout)


def create_app() -> FastAPI:
    application = FastAPI(title="AI Drama Studio API")
    application.state.settings = settings
    application.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(?:localhost|127\.0\.0\.1)(?::[0-9]+)?$",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(system_router, prefix="/api")
    register_exception_handlers(application)
    return application


app = create_app()
