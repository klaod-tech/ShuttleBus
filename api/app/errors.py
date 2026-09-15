"""오류 봉투 (01 5장): {error: {code, message, retryable}}. 화면 안내는 한국어."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False):
        self.status, self.code, self.message, self.retryable = status, code, message, retryable


def not_found(what: str) -> AppError:
    return AppError(404, "RESOURCE_NOT_FOUND", f"{what}을(를) 찾을 수 없습니다.")


def invalid(message: str) -> AppError:
    return AppError(422, "VALIDATION_ERROR", message)


def envelope(status: int, code: str, message: str, retryable: bool = False) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "retryable": retryable}},
        media_type="application/json; charset=utf-8",
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return envelope(exc.status, exc.code, exc.message, exc.retryable)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        fields = ", ".join(".".join(str(p) for p in e["loc"][1:]) for e in exc.errors())
        return envelope(422, "VALIDATION_ERROR", f"요청 형식이 올바르지 않습니다: {fields}")

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return envelope(404, "RESOURCE_NOT_FOUND", "요청한 경로를 찾을 수 없습니다.")
        return envelope(exc.status_code, "HTTP_ERROR", str(exc.detail))
