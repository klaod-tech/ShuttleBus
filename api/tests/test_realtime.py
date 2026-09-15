"""12 실시간 전송 (FR-RT) — 서버 쪽: 상태 확정·outbox·캐시 복원. 화면 동기화 절차(FR-RT-01·02·05·06·13)는 UI 단계."""

import asyncio
import contextlib
import uuid
from datetime import date, datetime

import fakeredis
import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models.calendar import ScheduleException
from app.models.realtime import OutboxEvent, TripStateSnapshot
from app.realtime import cache as cache_module
from app.realtime.cache import StateCache
from app.realtime.outbox import drain_once
from app.realtime.state import refresh_states
from app.seed import route_id
from app.timeutil import SEOUL
from tests.test_collection import Collector, accounts, at, trip1, trip_state, trusted_settings  # noqa: F401
from tests.test_operations import Admin

ROUTE = route_id("cheonan_asan")
DAY = date(2026, 9, 14)


def outbox(db, event=None):
    query = select(OutboxEvent).order_by(OutboxEvent.outbox_id)
    if event:
        query = query.where(OutboxEvent.event == event)
    return list(db.scalars(query))


def drain(db, now, emit=None, sent=None):
    sent = [] if sent is None else sent

    async def default_emit(event, room, payload):
        sent.append((event, room, payload))

    asyncio.run(drain_once(lambda: contextlib.nullcontext(db), emit or default_emit, now))
    return sent


@pytest.fixture
def redis_cache():
    fake = StateCache(fakeredis.FakeRedis())
    previous = cache_module.get_cache()
    cache_module.set_cache(fake)
    yield fake
    cache_module.set_cache(previous)


# ---------- 상태 확정 ----------


def test_fr_rt_03_trip_state_event_has_rest_structure(client, db, trip1):  # noqa: F811
    rest = trip_state(client, 1)
    events = outbox(db, "trip:state")
    assert len(events) == 1 and events[0].room == f"trip:{rest['trip_id']}"
    payload = events[0].payload
    assert set(payload) == set(rest) - {"server_time"}
    assert payload["stops"] and payload["vehicles"][0]["visits"]
    assert payload["state_version"] == rest["state_version"]


def test_fr_rt_09_same_content_does_not_bump_or_publish(client, db, trip1):  # noqa: F811
    first = trip_state(client, 1)
    count = len(outbox(db))
    again = trip_state(client, 1)
    assert again["state_version"] == first["state_version"]
    assert len(outbox(db)) == count


def test_observation_publishes_new_version_and_candidates_on_boarding_transition(client, db, trip1, set_now, trusted_settings):  # noqa: F811
    before = trip_state(client, 1)
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    res, _ = kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    state_events = outbox(db, "trip:state")
    assert state_events[-1].payload["state_version"] == res.json()["state_version"] > before["state_version"]
    # 기점 방문이 upcoming → departed: 그 방문에서 타는 후보가 사라진다 (FR-RT-15)
    changed = outbox(db, "candidates:changed")
    assert changed and changed[-1].room == f"route:{ROUTE}"
    assert changed[-1].payload == {"route_id": str(ROUTE), "service_date": "2026-09-14", "affected_trip_ids": [before["trip_id"]]}


def test_needs_review_input_publishes_nothing(client, db, trip1, set_now):  # noqa: F811
    trip_state(client, 1)
    count = len(outbox(db))
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    set_now(2026, 9, 14, 8, 5)
    res, _ = kim.observe(trip1["stops"][0], "departed", at(5))  # 시계 근거 없음 → 검토 대기
    assert res.json()["event"]["validation_status"] == "needs_review"
    assert len(outbox(db)) == count


def test_time_passage_commits_new_version_via_get_and_refresh(client, db, trip1, set_now):  # noqa: F811
    set_now(2026, 9, 14, 7, 50)
    v1 = trip_state(client, 1)["state_version"]
    # 기점 출발 시각(08:05)이 지나면 예측 만료로 내용이 바뀐다 → 같은 버전 번호로 다른 내용을 주지 않는다
    set_now(2026, 9, 14, 8, 6)
    v2 = trip_state(client, 1)["state_version"]
    assert v2 == v1 + 1

    now = datetime(2026, 9, 14, 8, 30, tzinfo=SEOUL)
    committed = refresh_states(db, [DAY], now)
    assert committed >= 1  # 순1 포함, 공개된 모든 회차의 시간 경과 확정
    set_now(2026, 9, 14, 8, 30)
    assert trip_state(client, 1)["state_version"] == v2 + 1
    assert refresh_states(db, [DAY], now) == 0  # 같은 시각 재실행은 아무것도 확정하지 않는다


def test_fr_rt_14_content_change_without_classification_change(client, db, trip1, set_now, trusted_settings, monkeypatch):  # noqa: F811
    """관측이 오래되어(stale) 내용은 바뀌지만 후보 집합·분류는 그대로면 candidates:changed를 보내지 않는다."""
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    set_now(2026, 9, 14, 8, 5, 30)
    trip_state(client, 1)
    changed_before = len(outbox(db, "candidates:changed"))
    monkeypatch.setattr(settings, "observation_grace_seconds", 60)
    set_now(2026, 9, 14, 8, 7)
    state = trip_state(client, 1)
    assert state["vehicles"][0]["information_status"] == "stale"
    assert outbox(db, "trip:state")[-1].payload["state_version"] == state["state_version"]
    assert len(outbox(db, "candidates:changed")) == changed_before


def test_cancellation_publishes_state_and_candidates(client, db, trip1, set_now):  # noqa: F811
    boss = Admin(client)
    state = trip_state(client, 1)
    boss.cancel_trip(state["trip_id"], state["control_version"])
    last_state = outbox(db, "trip:state")[-1].payload
    assert last_state["operation_status"] == "cancelled" and last_state["cancellation_reason"] == "차량 고장"
    assert outbox(db, "candidates:changed")


# ---------- 공지·날짜 ----------


def test_fr_rt_04_notice_rooms(client, db, trip1, set_now):  # noqa: F811
    boss = Admin(client)
    set_now(2026, 9, 14, 7, 50)
    base = {"route_id": str(ROUTE), "notice_type": "info", "message": "안내", "expires_at": datetime(2026, 9, 14, 12, 0, tzinfo=SEOUL).isoformat()}
    route_wide = boss.post("/api/v1/admin/notices", base).json()
    trip_only = boss.post("/api/v1/admin/notices", {**base, "trip_id": trip1["state"]["trip_id"]}).json()
    boss.post(f"/api/v1/admin/notices/{route_wide['notice_id']}/expire", {})
    rooms = [(e.room, e.payload["trip_id"]) for e in outbox(db, "notice:changed")]
    assert rooms == [
        (f"route:{ROUTE}", None),
        (f"trip:{trip_only['trip_id']}", trip_only["trip_id"]),
        (f"route:{ROUTE}", None),
    ]


def test_fr_rt_18_schedule_change_sends_one_kind(client, db, trip1, set_now):  # noqa: F811
    db.add(ScheduleException(exception_date=DAY, route_id=ROUTE, exception_type="no_service", source_reference="시험", note="임시 휴행"))
    db.flush()
    res = client.get("/api/v1/scheduled-trips", params={"route_id": str(ROUTE), "service_date": "2026-09-14"})
    assert res.json()["schedule_status"] == "no_service"
    kinds = [e.event for e in outbox(db) if e.room == f"route:{ROUTE}"]
    assert kinds == ["schedule:changed"]


# ---------- 전송 ----------


def test_drain_sends_in_order_and_marks_sent(client, db, trip1, set_now, trusted_settings):  # noqa: F811
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    now = datetime(2026, 9, 14, 8, 6, tzinfo=SEOUL)
    sent = drain(db, now)
    versions = [p["state_version"] for e, _, p in sent if e == "trip:state"]
    assert versions == sorted(versions) and len(versions) >= 1
    assert all(e.sent_at is not None for e in outbox(db))
    assert drain(db, now) == []  # 이미 보낸 항목은 다시 보내지 않는다


def test_fr_rt_12_failed_send_is_retried_after_lease(client, db, trip1):  # noqa: F811
    trip_state(client, 1)

    async def broken(event, room, payload):
        raise ConnectionError("socket down")

    now = datetime(2026, 9, 14, 8, 0, tzinfo=SEOUL)
    drain(db, now, emit=broken)
    row = outbox(db)[0]
    assert row.sent_at is None and row.attempts == 1 and "socket down" in row.last_error
    assert drain(db, now) == []  # 임대 기한 안에는 다시 잡지 않는다
    later = datetime(2026, 9, 14, 8, 1, tzinfo=SEOUL)
    assert [e for e, _, _ in drain(db, later)] == ["trip:state"]


# ---------- 캐시 ----------


def test_cache_put_only_newer_versions(redis_cache):
    trip_id = uuid.uuid4()
    assert redis_cache.put(trip_id, 3, {"v": 3})
    assert not redis_cache.put(trip_id, 2, {"v": 2})  # 복원 작업의 과거 상태가 새 상태를 덮지 않는다
    assert redis_cache.get(trip_id) == (3, {"v": 3})


def test_fr_rt_07_09_flushall_restores_from_db_without_new_version(client, db, trip1, redis_cache):  # noqa: F811
    from app.realtime.server import emit

    first = trip_state(client, 1)
    drain(db, datetime(2026, 9, 14, 8, 0, tzinfo=SEOUL), emit=emit)
    assert redis_cache.get(first["trip_id"])[0] == first["state_version"]

    redis_cache.client.flushall()
    snapshots = db.scalar(select(func.count()).select_from(TripStateSnapshot))
    events = len(outbox(db))
    again = trip_state(client, 1)
    assert again["state_version"] == first["state_version"]
    assert redis_cache.get(first["trip_id"])[0] == first["state_version"]  # DB 스냅샷에서 다시 채워짐
    assert db.scalar(select(func.count()).select_from(TripStateSnapshot)) == snapshots
    assert len(outbox(db)) == events


def test_redis_outage_falls_back_to_db(client, db, trip1):  # noqa: F811
    class Broken:
        def register_script(self, _):
            def run(**_):
                raise ConnectionError("redis down")

            return run

        def hgetall(self, _):
            raise ConnectionError("redis down")

    previous = cache_module.get_cache()
    cache_module.set_cache(StateCache(Broken()))
    try:
        assert trip_state(client, 1)["state_version"] >= 1
    finally:
        cache_module.set_cache(previous)
