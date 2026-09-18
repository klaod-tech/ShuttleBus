"""Socket.IO 서버와 백그라운드 작업 (12 1·2·4·5장).

단일 백엔드로 시작한다 (12 6장). API 프로세스에 Socket.IO를 붙이고, 같은 프로세스에서
outbox 전송과 시간 경과에 따른 상태 확정 작업을 돌린다. 여러 인스턴스로 늘리면 Redis 매니저가
룸 브로드캐스트를 잇고, outbox는 SKIP LOCKED로 나눠 가진다.
"""

import asyncio
import contextlib
import logging
import uuid
from datetime import timedelta

import socketio
from sqlalchemy import select

from app.clock import get_now
from app.config import settings
from app.db import SessionLocal
from app.models.calendar import ScheduledTrip
from app.models.reference import Route
from app.idempotency import purge_expired
from app.realtime.cache import get_cache
from app.realtime.outbox import drain_once, purge_sent
from app.realtime.state import refresh_states
from app.timeutil import today_seoul

log = logging.getLogger("app.realtime")


def _manager():
    if settings.redis_url:
        return socketio.AsyncRedisManager(settings.redis_url)
    return None


# CORS 허용 출처는 화면 배포 주소가 정해질 때 설정한다 (md_frontend/must_do.md S2). 기본은 같은 출처만
# 화면 출처는 CORS_ORIGINS를 따르고, 필요하면 SOCKET_CORS_ORIGINS로 따로 지정한다. 비우면 같은 출처만 허용
_origins = settings.socket_cors_origins or settings.cors_origins
sio = socketio.AsyncServer(async_mode="asgi", client_manager=_manager(), cors_allowed_origins=_origins or None)


# ---------- 구독 (12 1·2장) ----------


def _exists(model, key) -> bool:
    with SessionLocal() as session:
        return session.get(model, key) is not None


async def _join(sid, data, kind: str, model):
    try:
        target = uuid.UUID(str((data or {}).get(f"{kind}_id")))
    except ValueError:
        return {"ok": False, "code": "VALIDATION_ERROR"}
    if not await asyncio.to_thread(_exists, model, target):
        return {"ok": False, "code": "RESOURCE_NOT_FOUND"}
    await sio.enter_room(sid, f"{kind}:{target}")
    return {"ok": True, f"{kind}_id": str(target)}


@sio.on("trip:subscribe")
async def trip_subscribe(sid, data):
    # 승인 응답만 준다. 화면은 핸들러 등록 → 구독 승인 → REST /state 조회 순서로 동기화한다 (12 3장)
    return await _join(sid, data, "trip", ScheduledTrip)


@sio.on("trip:unsubscribe")
async def trip_unsubscribe(sid, data):
    with contextlib.suppress(Exception):
        await sio.leave_room(sid, f"trip:{uuid.UUID(str(data.get('trip_id')))}")
    return {"ok": True}


@sio.on("route:subscribe")
async def route_subscribe(sid, data):
    return await _join(sid, data, "route", Route)


@sio.on("route:unsubscribe")
async def route_unsubscribe(sid, data):
    with contextlib.suppress(Exception):
        await sio.leave_room(sid, f"route:{uuid.UUID(str(data.get('route_id')))}")
    return {"ok": True}


# ---------- 전송 ----------


async def emit(event: str, room: str, payload: dict) -> None:
    if event == "trip:state":
        # 캐시는 커밋된 상태만 받는다. 더 새 버전일 때만 덮는다
        await asyncio.to_thread(get_cache().put, room.split(":", 1)[1], payload["state_version"], payload)
    await sio.emit(event, payload, room=room)


def refresh_today_states() -> int:
    """시간 경과로 바뀐 오늘 회차 상태를 새 버전으로 확정한다 (08 9장 expire_predictions 역할)."""
    now = get_now()
    today = today_seoul(now)
    with SessionLocal() as session:
        return refresh_states(session, (today - timedelta(days=1), today), now)


def restore_cache_on_start() -> int:
    """서비스 시작 시 오늘·어제 회차의 DB 스냅샷을 캐시에 복사한다 (12 5장)."""
    cache = get_cache()
    if not cache.enabled:
        return 0
    today = today_seoul(get_now())
    with SessionLocal() as session:
        trip_ids = session.scalars(
            select(ScheduledTrip.scheduled_trip_id).where(ScheduledTrip.service_date.in_((today, today - timedelta(days=1))))
        ).all()
        return sum(1 for tid in trip_ids if cache.rebuild(session, tid))


def purge_old_records() -> tuple[int, int]:
    """전송이 끝난 outbox 항목과 보존 기간이 지난 멱등 기록을 지운다. 하루 한 번 돌린다."""
    now = get_now()
    with SessionLocal() as session:
        sent = purge_sent(session, now)
        keys = purge_expired(session, now)
        session.commit()
        return sent, keys


async def _loop(name: str, interval: float, work):
    while True:
        try:
            await work()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("%s 작업 실패", name)
        await asyncio.sleep(interval)


async def _drain():
    await drain_once(SessionLocal, emit, get_now())


async def _refresh():
    await asyncio.to_thread(refresh_today_states)


async def _purge():
    await asyncio.to_thread(purge_old_records)


@contextlib.asynccontextmanager
async def background_workers():
    if not settings.realtime_workers:
        yield
        return
    await asyncio.to_thread(restore_cache_on_start)
    tasks = [
        asyncio.create_task(_loop("outbox 전송", settings.outbox_poll_seconds, _drain)),
        asyncio.create_task(_loop("상태 만료 확정", settings.state_refresh_seconds, _refresh)),
        asyncio.create_task(_loop("오래된 기록 정리", 3600, _purge)),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
