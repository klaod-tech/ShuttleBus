"""13 운영 관리 (FR-OP) — 차량 완료, 회차 취소, 공지, 관측 검토·복구, 완료 재검토, 검토 대상 판정."""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models.calendar import ScheduledTrip, TripVehicle
from app.models.observation import CollectionSession, ObservationReview
from app.operations.completion import recompute_trip_status
from app.operations.service import mark_sessions_for_review
from app.seed import route_id
from app.timeutil import SEOUL
from tests.test_collection import Collector, accounts, at, trip1, trip_state, trusted_settings  # noqa: F401  픽스처 재사용

ROUTE = str(route_id("cheonan_asan"))


class Admin(Collector):
    def __init__(self, client):
        super().__init__(client, "boss")

    def control(self, trip_no):
        return trip_state(self.client, trip_no)["control_version"]

    def complete(self, vehicle_id, trip_no, evidence="collector_report", **extra):
        body = {"evidence_type": evidence, "expected_control_version": self.control(trip_no), **extra}
        return self.post(f"/api/v1/admin/trip-vehicles/{vehicle_id}/completion", body)

    def cancel_trip(self, trip_id, version, reason="차량 고장"):
        return self.post(f"/api/v1/admin/scheduled-trips/{trip_id}/cancellation", {"reason": reason, "expected_control_version": version})

    def review(self, event_id, decision, collector, trip_no, key=None, **extra):
        body = {
            "decision": decision,
            "reason": "현장 확인",
            "evidence_note": "입력자 통화로 확인",
            "expected_input_version": collector.reload()["input_version"],
            "expected_control_version": self.control(trip_no),
            **extra,
        }
        return self.post(f"/api/v1/admin/events/{event_id}/review", body, key)

    def restore(self, event_id, collector, trip_no, key=None, body=None):
        body = body or {
            "reason": "잘못 취소",
            "evidence_note": "사진 확인",
            "expected_input_version": collector.reload()["input_version"],
            "expected_control_version": self.control(trip_no),
        }
        return self.post(f"/api/v1/admin/events/{event_id}/restore", body, key), body


@pytest.fixture
def boss(client, accounts):  # noqa: F811
    return Admin(client)


@pytest.fixture
def trip7(client, set_now, accounts):  # noqa: F811
    """천안아산역 순7 — 월요일 2대 운행. 천안아산역 09:00 출발 → 캠퍼스 09:15 도착."""
    set_now(2026, 9, 14, 8, 50)
    s = trip_state(client, 7)
    return {"state": s, "vehicles": [v["trip_vehicle_id"] for v in s["vehicles"]], "stops": [x["trip_stop_id"] for x in s["stops"]]}


def cancel(collector, event_id):
    res = collector.post(
        f"/api/v1/events/{event_id}/cancel", {"reason": "잘못 누름", "expected_input_version": collector.reload()["input_version"]}
    )
    assert res.status_code == 200, res.text
    collector.session["input_version"] = res.json()["input_version"]
    return res


# ---------- 차량 완료 ----------


def test_fr_op_04_05_08_vehicle_completion_is_per_slot(client, boss, trip7, set_now):
    assert len(trip7["vehicles"]) == 2
    set_now(2026, 9, 14, 9, 20)
    before = trip_state(client, 7)
    res = boss.complete(trip7["vehicles"][0], 7, note="기사님 통화")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["decision"]["observed_completed_at"] is None  # 근거 없는 완료 시각을 만들지 않는다
    after = trip_state(client, 7)
    assert [v["operation_status"] for v in after["vehicles"]] == ["completed", "scheduled"]
    assert after["operation_status"] == "scheduled"
    assert after["control_version"] == before["control_version"] + 1
    assert after["state_version"] == before["state_version"] + 1

    boss.complete(trip7["vehicles"][1], 7)
    assert trip_state(client, 7)["operation_status"] == "completed"


def test_completion_conflicts(client, boss, trip7, set_now):
    set_now(2026, 9, 14, 9, 20)
    stale = boss.control(7)
    boss.complete(trip7["vehicles"][0], 7)
    res = boss.post(
        f"/api/v1/admin/trip-vehicles/{trip7['vehicles'][1]}/completion",
        {"evidence_type": "admin_judgement", "expected_control_version": stale},
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "CONTROL_VERSION_CONFLICT"
    again = boss.complete(trip7["vehicles"][0], 7)
    assert again.status_code == 409 and again.json()["error"]["code"] == "OPERATION_STATE_CONFLICT"
    future = boss.complete(trip7["vehicles"][1], 7, observed_completed_at=datetime(2026, 9, 14, 10, 0, tzinfo=SEOUL).isoformat())
    assert future.status_code == 422


def test_admin_endpoints_require_admin(client, trip7, set_now):
    kim = Collector(client, "kim")
    res = kim.post(f"/api/v1/admin/trip-vehicles/{trip7['vehicles'][0]}/completion", {"evidence_type": "admin_judgement", "expected_control_version": 1})
    assert res.status_code == 403 and res.json()["error"]["code"] == "FORBIDDEN"


def test_fr_op_18_20_terminal_observation_auto_completes_one_slot(client, trip7, set_now, trusted_settings):  # noqa: F811
    kim = Collector(client, "kim")
    kim.start(trip7["vehicles"][0])
    clock = kim.clock(set_now, datetime(2026, 9, 14, 8, 59, tzinfo=SEOUL))
    kim.observe(trip7["stops"][0], "departed", datetime(2026, 9, 14, 9, 0, tzinfo=SEOUL), clock=clock)
    set_now(2026, 9, 14, 9, 16)
    arrived, _ = kim.observe(trip7["stops"][1], "arrived", datetime(2026, 9, 14, 9, 16, tzinfo=SEOUL), clock=clock)
    assert arrived.status_code == 201, arrived.text
    state = trip_state(client, 7)
    assert [v["operation_status"] for v in state["vehicles"]] == ["completed", "scheduled"]
    assert state["operation_status"] == "scheduled"


def test_fr_op_19_terminal_needs_review_does_not_complete(client, trip7, set_now):
    kim = Collector(client, "kim")
    kim.start(trip7["vehicles"][0])
    set_now(2026, 9, 14, 9, 16)
    res, _ = kim.observe(trip7["stops"][1], "arrived", datetime(2026, 9, 14, 9, 16, tzinfo=SEOUL))  # 시계 근거 없음
    assert res.json()["event"]["validation_status"] == "needs_review"
    assert trip_state(client, 7)["vehicles"][0]["operation_status"] == "scheduled"


# ---------- 회차 취소 ----------


def test_fr_op_06_10_13_cancel_trip(client, boss, trip1, set_now, trusted_settings):  # noqa: F811
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    set_now(2026, 9, 14, 8, 10)
    before = trip_state(client, 1)
    res = boss.cancel_trip(before["trip_id"], before["control_version"])
    assert res.status_code == 200, res.text
    state = trip_state(client, 1)
    assert state["operation_status"] == "cancelled" and state["cancellation_reason"] == "차량 고장"
    assert [v["operation_status"] for v in state["vehicles"]] == ["cancelled"]
    assert state["vehicles"][0]["cancellation_reason"] == "차량 고장"
    assert {v["unavailable_reason"] for v in state["vehicles"][0]["visits"]} == {"trip_cancelled"}
    assert state["state_version"] == before["state_version"] + 1  # 학생 화면 전파의 근거 (FR-OP-10)

    # 취소 뒤 늦게 도착한 실측은 이력에 보충되지만 운행을 재개하지 않는다
    late, _ = kim.observe(trip1["stops"][4], "arrived", at(40), clock=clock, confirm_skip=True)
    assert late.status_code == 201
    assert trip_state(client, 1)["operation_status"] == "cancelled"

    twice = boss.cancel_trip(state["trip_id"], state["control_version"])
    assert twice.status_code == 409 and twice.json()["error"]["code"] == "OPERATION_STATE_CONFLICT"


def test_fr_op_14_all_slots_cancelled_is_cancelled_not_completed(db, trip7):
    trip = db.get(ScheduledTrip, uuid.UUID(trip7["state"]["trip_id"]))
    for v in db.scalars(select(TripVehicle).where(TripVehicle.scheduled_trip_id == trip.scheduled_trip_id)):
        v.operation_status = "cancelled"
    db.flush()
    recompute_trip_status(db, trip)
    assert trip.operation_status == "cancelled"


# ---------- 공지 ----------


def test_fr_op_07_11_notices(client, boss, trip1, set_now):
    set_now(2026, 9, 14, 7, 50)
    trip_id = trip1["state"]["trip_id"]
    body = {
        "route_id": ROUTE,
        "trip_id": trip_id,
        "notice_type": "cancel",
        "message": "순1 운행 취소 예정",
        "expires_at": datetime(2026, 9, 14, 12, 0, tzinfo=SEOUL).isoformat(),
    }
    created = boss.post("/api/v1/admin/notices", body)
    assert created.status_code == 201, created.text
    route_wide = boss.post("/api/v1/admin/notices", {**body, "trip_id": None, "notice_type": "info", "message": "노선 안내"})
    assert trip_state(client, 1)["operation_status"] == "scheduled"  # 공지 cancel만으로 취소 안 됨

    listed = client.get("/api/v1/notices", params={"route_id": ROUTE, "trip_id": trip_id})  # 인증 불필요
    assert listed.status_code == 200 and len(listed.json()["notices"]) == 2

    notice_id = created.json()["notice_id"]
    expired = boss.post(f"/api/v1/admin/notices/{notice_id}/expire", {})
    assert expired.status_code == 200 and expired.json()["expired_early_at"] is not None
    remaining = client.get("/api/v1/notices", params={"route_id": ROUTE}).json()["notices"]
    assert [n["notice_id"] for n in remaining] == [route_wide.json()["notice_id"]]

    set_now(2026, 9, 14, 12, 0)
    assert client.get("/api/v1/notices", params={"route_id": ROUTE}).json()["notices"] == []


def test_notice_validation(client, boss, trip1, set_now):
    set_now(2026, 9, 14, 7, 50)
    past = boss.post(
        "/api/v1/admin/notices",
        {"route_id": ROUTE, "notice_type": "info", "message": "x", "expires_at": datetime(2026, 9, 14, 7, 0, tzinfo=SEOUL).isoformat()},
    )
    assert past.status_code == 422
    other_route = boss.post(
        "/api/v1/admin/notices",
        {
            "route_id": str(route_id("cheonan")),
            "trip_id": trip1["state"]["trip_id"],
            "notice_type": "info",
            "message": "x",
            "expires_at": datetime(2026, 9, 14, 9, 0, tzinfo=SEOUL).isoformat(),
        },
    )
    assert other_route.status_code == 404


# ---------- 관측 검토 ----------


def test_fr_op_15_approve_and_replay(client, db, boss, trip1, set_now):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    set_now(2026, 9, 14, 8, 5)
    res, _ = kim.observe(trip1["stops"][0], "departed", at(5))  # 시계 근거 없음 → 검토 대기
    event = res.json()["event"]
    assert event["validation_status"] == "needs_review"
    assert trip_state(client, 1)["vehicles"][0]["information_status"] == "timetable_only"

    no_evidence = boss.review(event["event_id"], "approve", kim, 1, evidence_note="")
    assert no_evidence.status_code == 422

    key = str(uuid.uuid4())
    approved = boss.review(event["event_id"], "approve", kim, 1, key=key)
    assert approved.status_code == 200, approved.text
    assert approved.json()["event"]["validation_status"] == "valid"
    assert approved.json()["event"]["occurred_at"] == event["occurred_at"]  # 원본 시각 보존
    assert trip_state(client, 1)["vehicles"][0]["information_status"] == "observed"

    # 새 키로 다시 결정하면 REVIEW_CONFLICT. 같은 키 재전송은 test_review_same_key_same_body_replays
    count = lambda: db.scalar(select(func.count()).where(ObservationReview.event_id == uuid.UUID(event["event_id"]), ObservationReview.decision == "approve"))  # noqa: E731
    assert count() == 1
    again = boss.review(event["event_id"], "approve", kim, 1)
    assert again.status_code == 409 and again.json()["error"]["code"] == "REVIEW_CONFLICT"
    assert count() == 1


def test_review_same_key_same_body_replays(client, db, boss, trip1, set_now):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    set_now(2026, 9, 14, 8, 5)
    res, _ = kim.observe(trip1["stops"][0], "departed", at(5))
    event_id = res.json()["event"]["event_id"]
    body = {
        "decision": "reject",
        "reason": "잘못된 정거장",
        "evidence_note": None,
        "expected_input_version": kim.reload()["input_version"],
        "expected_control_version": boss.control(1),
    }
    key = str(uuid.uuid4())
    first = boss.post(f"/api/v1/admin/events/{event_id}/review", body, key)
    second = boss.post(f"/api/v1/admin/events/{event_id}/review", body, key)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["event"]["cancel_reason"] == "observation_rejected"
    assert db.scalar(select(func.count()).where(ObservationReview.event_id == uuid.UUID(event_id))) == 1


def test_review_version_conflicts(client, boss, trip1, set_now):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    set_now(2026, 9, 14, 8, 5)
    res, _ = kim.observe(trip1["stops"][0], "departed", at(5))
    event_id = res.json()["event"]["event_id"]
    stale_input = boss.review(event_id, "approve", kim, 1, expected_input_version=0)
    assert stale_input.json()["error"]["code"] == "INPUT_VERSION_CONFLICT"
    stale_control = boss.review(event_id, "approve", kim, 1, expected_control_version=0)
    assert stale_control.json()["error"]["code"] == "CONTROL_VERSION_CONFLICT"


# ---------- 복구 ----------


def test_fr_op_22_restore_rejected_returns_to_needs_review(client, boss, trip1, set_now):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    set_now(2026, 9, 14, 8, 5)
    res, _ = kim.observe(trip1["stops"][0], "departed", at(5))
    event_id = res.json()["event"]["event_id"]
    boss.review(event_id, "reject", kim, 1)
    restored, _ = boss.restore(event_id, kim, 1)
    assert restored.status_code == 200, restored.text
    assert restored.json()["event"]["validation_status"] == "needs_review"
    assert restored.json()["event"]["cancel_reason"] is None
    assert trip_state(client, 1)["vehicles"][0]["information_status"] == "timetable_only"

    not_cancelled, _ = boss.restore(event_id, kim, 1)
    assert not_cancelled.json()["error"]["code"] == "REVIEW_CONFLICT"


def test_fr_op_23_restore_conflict_with_replacement(client, boss, trip1, set_now, trusted_settings):  # noqa: F811
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    first, _ = kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    cancel(kim, first.json()["event"]["event_id"])
    replacement, _ = kim.observe(trip1["stops"][0], "departed", at(6), clock=clock)
    assert replacement.json()["event"]["validation_status"] == "valid"
    res, _ = boss.restore(first.json()["event"]["event_id"], kim, 1)
    assert res.status_code == 409 and res.json()["error"]["code"] == "RESTORE_CONFLICT"

    # 관리자가 대체 관측을 먼저 취소하면 복구된다
    boss_cancel = boss.post(f"/api/v1/events/{replacement.json()['event']['event_id']}/cancel", {"reason": "대체 관측 정리", "expected_input_version": kim.reload()["input_version"]})
    assert boss_cancel.status_code == 200, boss_cancel.text
    ok, _ = boss.restore(first.json()["event"]["event_id"], kim, 1)
    assert ok.status_code == 200 and ok.json()["event"]["validation_status"] == "valid"


def test_fr_op_24_restore_replay_and_skipped_recomputed(client, db, boss, trip1, set_now, trusted_settings):  # noqa: F811
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    set_now(2026, 9, 14, 8, 25)
    station, _ = kim.observe(trip1["stops"][3], "arrived", at(25), clock=clock)
    assert len(station.json()["skipped_events"]) == 2
    event_id = station.json()["event"]["event_id"]
    cancelled = cancel(kim, event_id).json()
    assert len(cancelled["cascaded_events"]) == 2

    key = str(uuid.uuid4())
    first, body = boss.restore(event_id, kim, 1, key=key)
    second, _ = boss.restore(event_id, kim, 1, key=key, body=body)
    assert first.status_code == second.status_code == 200, first.text
    assert first.json() == second.json()
    restored = first.json()
    assert restored["event"]["validation_status"] == "valid"
    assert len(restored["skipped_events"]) == 2  # 파생 누락은 되살리지 않고 다시 계산한다
    restores = db.scalar(select(func.count()).where(ObservationReview.event_id == uuid.UUID(event_id), ObservationReview.decision == "restore"))
    assert restores == 1
    visits = trip_state(client, 1)["vehicles"][0]["visits"]
    assert [v["visit_status"] for v in visits[:4]] == ["departed", "passed_inferred", "passed_inferred", "arrived"]


def test_restore_order_conflict(client, boss, trip1, set_now, trusted_settings):  # noqa: F811
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    set_now(2026, 9, 14, 8, 15)
    mid, _ = kim.observe(trip1["stops"][1], "arrived", at(15), clock=clock)
    cancel(kim, mid.json()["event"]["event_id"])
    set_now(2026, 9, 14, 8, 25)
    kim.observe(trip1["stops"][3], "arrived", at(12), clock=clock)  # 복구 대상보다 이른 시각의 뒤 방문
    res, _ = boss.restore(mid.json()["event"]["event_id"], kim, 1)
    assert res.status_code == 409 and res.json()["error"]["code"] == "EVENT_ORDER_CONFLICT"


def test_fr_op_26_restore_on_completed_vehicle_keeps_completion(client, boss, trip1, set_now, trusted_settings):  # noqa: F811
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    dep, _ = kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    cancel(kim, dep.json()["event"]["event_id"])
    set_now(2026, 9, 14, 8, 45)
    boss.complete(trip1["vehicle"], 1)
    res, _ = boss.restore(dep.json()["event"]["event_id"], kim, 1)
    assert res.status_code == 200 and res.json()["event"]["validation_status"] == "valid"
    assert trip_state(client, 1)["vehicles"][0]["operation_status"] == "completed"


# ---------- 완료 근거 재검토 ----------


def test_fr_op_12_16_evidence_cancel_keeps_completion_until_decision(client, boss, trip1, set_now, trusted_settings):  # noqa: F811
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    set_now(2026, 9, 14, 8, 41)
    terminal, _ = kim.observe(trip1["stops"][4], "arrived", at(40), clock=clock, confirm_skip=True)
    assert trip_state(client, 1)["vehicles"][0]["operation_status"] == "completed"

    cancel(kim, terminal.json()["event"]["event_id"])
    assert trip_state(client, 1)["vehicles"][0]["operation_status"] == "completed"  # 자동 해제 없음
    listed = client.get("/api/v1/admin/collection-sessions", params={"service_date": "2026-09-14", "review_required": False}, headers=boss.headers)
    row = next(s for s in listed.json()["sessions"] if s["trip_vehicle_id"] == trip1["vehicle"])
    assert row["completion_review_required"] is True

    no_evidence = boss.post(
        f"/api/v1/admin/trip-vehicles/{trip1['vehicle']}/completion-review",
        {"decision": "keep_completed", "expected_control_version": boss.control(1)},
    )
    assert no_evidence.status_code == 422
    reopened = boss.post(
        f"/api/v1/admin/trip-vehicles/{trip1['vehicle']}/completion-review",
        {"decision": "reopen", "note": "종점 도착 오입력 확인", "expected_control_version": boss.control(1)},
    )
    assert reopened.status_code == 200, reopened.text
    decision = reopened.json()["decision"]
    assert decision["supersedes_decision_id"] is not None
    state = trip_state(client, 1)
    assert state["vehicles"][0]["operation_status"] == "scheduled" and state["operation_status"] == "scheduled"


def test_keep_completed_with_new_evidence(client, boss, trip1, set_now):
    set_now(2026, 9, 14, 8, 45)
    boss.complete(trip1["vehicle"], 1, evidence="admin_judgement")
    kept = boss.post(
        f"/api/v1/admin/trip-vehicles/{trip1['vehicle']}/completion-review",
        {"decision": "keep_completed", "evidence_type": "operator_notice", "note": "운영사 확인", "expected_control_version": boss.control(1)},
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["vehicles"][0]["operation_status"] == "completed"
    assert kept.json()["vehicles"][0]["completion_review_required"] is False


# ---------- 검토 대상 판정 · 기록 조회 ----------


def test_fr_op_02_17_mark_sessions_for_review(client, db, boss, trip1, trip7, set_now, trusted_settings):  # noqa: F811
    kim, lee = Collector(client, "kim"), Collector(client, "lee")
    kim.start(trip1["vehicle"])
    lee.start(trip7["vehicles"][0])
    set_now(2026, 9, 14, 9, 30)
    ended = lee.post(
        f"/api/v1/collection-sessions/{lee.session['collection_session_id']}/end",
        {"ended_at": at(90).isoformat(), "expected_input_version": lee.session["input_version"]},
    )
    assert ended.status_code == 200, ended.text
    now = datetime(2026, 9, 14, 12, 0, tzinfo=SEOUL)
    assert mark_sessions_for_review(db, now) == []  # 구간 소요시간이 없으면 올리지 않는다

    marked = mark_sessions_for_review(db, now, remaining=lambda s, v, stop: timedelta(minutes=35), grace_seconds=600)
    assert len(marked) == 2
    open_sess = db.get(CollectionSession, uuid.UUID(kim.session["collection_session_id"]))
    ended_sess = db.get(CollectionSession, uuid.UUID(lee.session["collection_session_id"]))
    assert open_sess.collection_status == "needs_review" and open_sess.review_required
    assert ended_sess.collection_status == "ended" and ended_sess.review_required
    assert trip_state(client, 1)["operation_status"] == "scheduled"  # 완료로 단정하지 않는다

    listed = client.get(
        "/api/v1/admin/collection-sessions", params={"service_date": "2026-09-14", "review_required": True}, headers=boss.headers
    ).json()["sessions"]
    assert {s["collection_session_id"] for s in listed} == {kim.session["collection_session_id"], lee.session["collection_session_id"]}


def test_admin_session_events_include_cancelled_and_skipped(client, boss, trip1, set_now, trusted_settings):  # noqa: F811
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    set_now(2026, 9, 14, 8, 25)
    station, _ = kim.observe(trip1["stops"][3], "arrived", at(25), clock=clock)
    cancel(kim, station.json()["event"]["event_id"])
    res = client.get(f"/api/v1/admin/collection-sessions/{kim.session['collection_session_id']}/events", headers=boss.headers)
    assert res.status_code == 200
    body = res.json()
    assert {e["event_type"] for e in body["events"]} == {"departed", "arrived", "skipped"}
    assert {e["validation_status"] for e in body["events"]} == {"valid", "cancelled"}
    assert len(body["reviews"]) == 3  # 근거 취소 1 + 연동 누락 취소 2
