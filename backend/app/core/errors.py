import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.errors")


def _error_code(status_code: int) -> str:
    if status_code == 404:
        return "not_found"
    if status_code == 405:
        return "method_not_allowed"
    if status_code == 409:
        return "conflict"
    if status_code == 422:
        return "validation_error"
    if status_code >= 500:
        return "internal_error"
    return "validation_error"


async def handle_http_exception(
    request: Request, exception: StarletteHTTPException
) -> JSONResponse:
    del request
    detail = exception.detail if isinstance(exception.detail, str) else "Request failed"
    return JSONResponse(
        status_code=exception.status_code,
        content={
            "detail": {
                "code": _error_code(exception.status_code),
                "message": detail,
            }
        },
    )


async def handle_validation_error(
    request: Request, exception: RequestValidationError
) -> JSONResponse:
    del request, exception
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "code": "validation_error",
                "message": "Request validation failed",
            }
        },
    )


async def handle_unexpected_error(request: Request, exception: Exception) -> JSONResponse:
    logger.exception(
        "Unhandled request error method=%s path=%s",
        request.method,
        request.url.path,
    )
    del exception
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "code": "internal_error",
                "message": "Internal server error",
            }
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
