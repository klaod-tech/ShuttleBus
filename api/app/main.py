from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.admin import router as admin_router
from app.api.calendar import router as calendar_router
from app.api.collection import router as collection_router
from app.api.trips import router as trips_router
from app.errors import install_error_handlers


class UTF8JSONResponse(JSONResponse):
    # charset이 없으면 일부 클라이언트(Windows PowerShell 5.1 등)가 한국어를 Latin-1로 읽는다
    media_type = "application/json; charset=utf-8"


app = FastAPI(title="ShuttleBus API", version="0.1.0", default_response_class=UTF8JSONResponse)
install_error_handlers(app)
app.include_router(calendar_router)
app.include_router(trips_router)
app.include_router(collection_router)
app.include_router(admin_router)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
