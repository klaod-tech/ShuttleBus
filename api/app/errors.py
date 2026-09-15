"""오류 봉투 (01 5장): {error: {code, message, retryable[, details]}}. 화면 안내는 한국어."""

import logging
from datetime import date

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False, details: dict | None = None):
        self.status, self.code, self.message, self.retryable, self.details = status, code, message, retryable, details

    def body(self) -> dict:
        error = {"code": self.code, "message": self.message, "retryable": self.retryable}
        if self.details is not None:
            error["details"] = self.details
        return {"error": error}


def not_found(what: str) -> AppError:
    return AppError(404, "RESOURCE_NOT_FOUND", f"{what}을(를) 찾을 수 없습니다.")


def invalid(message: str) -> AppError:
    return AppError(422, "VALIDATION_ERROR", message)


def check_service_date(*dates: date) -> None:
    from app.timeutil import MAX_SERVICE_DATE, MIN_SERVICE_DATE

    for d in dates:
        if not MIN_SERVICE_DATE <= d <= MAX_SERVICE_DATE:
            raise invalid(f"운행 날짜는 {MIN_SERVICE_DATE}~{MAX_SERVICE_DATE} 범위여야 합니다.")


def envelope(status: int, code: str, message: str, retryable: bool = False) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "retryable": retryable}},
        media_type="application/json; charset=utf-8",
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status, content=exc.body(), media_type="application/json; charset=utf-8")

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        fields = ", ".join(".".join(str(p) for p in e["loc"][1:]) for e in exc.errors())
        return envelope(422, "VALIDATION_ERROR", f"요청 형식이 올바르지 않습니다: {fields}")

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        # 내부 정보는 응답에 싣지 않고 로그로만 남긴다
        logging.getLogger("app").exception("처리하지 못한 오류: %s %s", request.method, request.url.path)
        return envelope(500, "INTERNAL_ERROR", "일시적인 서버 오류입니다. 잠시 후 다시 시도해 주세요.", retryable=True)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return envelope(404, "RESOURCE_NOT_FOUND", "요청한 경로를 찾을 수 없습니다.")
        return envelope(exc.status_code, "HTTP_ERROR", str(exc.detail))
