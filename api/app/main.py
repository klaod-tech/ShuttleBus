import contextlib

import socketio
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.admin import router as admin_router
from app.api.calendar import router as calendar_router
from app.api.collection import router as collection_router
from app.api.trips import router as trips_router
from app.config import settings
from app.errors import install_error_handlers
from app.realtime.cache import connect_from_settings, set_cache


class UTF8JSONResponse(JSONResponse):
    # charset이 없으면 일부 클라이언트(Windows PowerShell 5.1 등)가 한국어를 Latin-1로 읽는다
    media_type = "application/json; charset=utf-8"


settings.check_production_secrets()

@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    from app.realtime.server import background_workers

    if settings.realtime_workers:
        set_cache(connect_from_settings(settings.redis_url))
    async with background_workers():
        yield


app = FastAPI(title="ShuttleBus API", version="0.1.0", default_response_class=UTF8JSONResponse, lifespan=lifespan)
install_error_handlers(app)
app.include_router(calendar_router)
app.include_router(trips_router)
app.include_router(collection_router)
app.include_router(admin_router)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


def _asgi():
    from app.realtime.server import sio

    # /socket.io 는 Socket.IO, 나머지는 FastAPI. 실행: uvicorn app.main:asgi
    return socketio.ASGIApp(sio, other_asgi_app=app)


asgi = _asgi()
