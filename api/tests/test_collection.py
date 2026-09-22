"""06 수동 수집 (FR-MC) · 02 관측 계약 (FR-OB) · 01 멱등 계약."""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.auth import hash_password
from app.config import settings
from app.models.observation import ObservationReview, StaffAccount
from app.seed import route_id, stop_id
from app.timeutil import SEOUL

# 시험 계정 비밀번호는 실행할 때마다 만든다 — 저장소에 비밀번호처럼 보이는 문자열을 남기지 않는다 (2026-09-22)
TEST_PASSWORD = "pytest-" + uuid.uuid4().hex

DAY = "2026-09-14"
T0 = datetime(2026, 9, 14, 7, 55, tzinfo=SEOUL)


@pytest.fixture
def accounts(db):
    made = {}
    for name, role in (("kim", "collector"), ("lee", "collector"), ("boss", "admin")):
        a = StaffAccount(username=name, role=role, password_hash=hash_password(TEST_PASSWORD))
        db.add(a)
        made[name] = a
    db.flush()
    return made


@pytest.fixture
def trusted_settings(monkeypatch):
    """시계·보관·실시간 창 설정이 정해진 경우. 미정 값의 기본 동작은 별도 시험에서 본다."""
    monkeypatch.setattr(settings, "clock_skew_tolerance_seconds", 5.0)
    monkeypatch.setattr(settings, "clock_check_valid_seconds", 6 * 3600)
    monkeypatch.setattr(settings, "pending_input_retention_hours", 24.0)
    monkeypatch.setattr(settings, "realtime_input_window_seconds", 120)


def advance_clock_to(moment: datetime) -> None:
    """버튼을 누른 순간보다 서버 시각이 앞서 있을 수 없다. 서버 시각이 발생 시각보다 이르면 발생 시각으로 옮긴다.

    열린 세션은 수신 시각 이후의 발생 시각을 수집 기간 밖으로 본다 (02 6장).
    """
    from app import clock

    if clock._fixed is not None and clock._fixed < moment:
        clock.set_fixed_now(moment)


class Collector:
    """입력자 앱 흉내. 논리 관측 ID·순번은 유지하고 요청 시도마다 Idempotency-Key를 발급한다."""

    def __init__(self, client, username):
        self.client = client
        res = client.post("/api/v1/auth/login", json={"username": username, "password": TEST_PASSWORD})
        assert res.status_code == 200, res.text
        self.headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
        self.sequence = 0
        self.session = None

    def post(self, path, body, key=None):
        headers = {**self.headers, "Idempotency-Key": key or str(uuid.uuid4())}
        return self.client.post(path, json=body, headers=headers)

    def start(self, trip_vehicle_id, start_trip_stop_id=None, writer=None):
        res = self.post(
            "/api/v1/collection-sessions",
            {"trip_vehicle_id": trip_vehicle_id, "collection_start_trip_stop_id": start_trip_stop_id, "writer_instance_id": writer},
        )
        if res.status_code in (200, 201):
            self.session = res.json()
        return res

    def clock(self, set_now, at: datetime):
        set_now(*at.timetuple()[:6])
        begin = self.client.post(
            f"/api/v1/collection-sessions/{self.session['collection_session_id']}/clock-checks",
            json={"device_sent_at": at.isoformat()}, headers=self.headers,
        ).json()
        done = self.client.post(
            f"/api/v1/clock-checks/{begin['clock_check_id']}/complete",
            json={"device_received_at": at.isoformat()}, headers=self.headers,
        ).json()
        return done["clock_check_id"]

    def observe(self, trip_stop_id, event_type, occurred_at, *, clock=None, confirm_skip=False, event_id=None, sequence=None, key=None, version=None, advance_clock=True):
        if sequence is None:
            self.sequence += 1
            sequence = self.sequence
        body = {
            "trip_stop_id": trip_stop_id,
            "event_type": event_type,
            "occurred_at": occurred_at.isoformat(),
            "client_event_id": event_id or f"e{sequence}",
            "client_sequence": sequence,
            "expected_input_version": self.session["input_version"] if version is None else version,
            "confirm_skip": confirm_skip,
            "writer_instance_id": self.session["writer_instance_id"],
            "clock_check_id": clock,
        }
        if advance_clock:
            advance_clock_to(occurred_at)
        res = self.post(f"/api/v1/collection-sessions/{self.session['collection_session_id']}/events", body, key)
        if res.status_code in (200, 201):
            self.session["input_version"] = res.json()["input_version"]
        return res, body

    def reload(self):
        res = self.client.get(f"/api/v1/collection-sessions/{self.session['collection_session_id']}", headers=self.headers)
        self.session = res.json()
        return self.session


def trip_state(client, trip_no, set_now=None, route="cheonan_asan"):
    body = client.get("/api/v1/scheduled-trips", params={"route_id": str(route_id(route)), "service_date": DAY}).json()
    trip = next(t for t in body["trips"] if t["trip_no"] == trip_no)
    return client.get(f"/api/v1/scheduled-trips/{trip['trip_id']}/state").json()


@pytest.fixture
def trip1(client, set_now, accounts):
    """천안아산역 순1 (08:05 캠퍼스 출발 → 탕정역 → 시티프라디움 → 천안아산역 08:25 → 캠퍼스 08:40)."""
    set_now(2026, 9, 14, 7, 50)
    s = trip_state(client, 1)
    return {"state": s, "vehicle": s["vehicles"][0]["trip_vehicle_id"], "stops": [x["trip_stop_id"] for x in s["stops"]]}


def at(minutes: int) -> datetime:
    return datetime(2026, 9, 14, 8, 0, tzinfo=SEOUL) + timedelta(minutes=minutes)


# ---------- 인증 ----------


def test_login_and_auth_required(client, accounts, set_now):
    set_now(2026, 9, 14, 7, 0)
    bad = client.post("/api/v1/auth/login", json={"username": "kim", "password": "wrong"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "AUTH_REQUIRED"
    ok = client.post("/api/v1/auth/login", json={"username": "kim", "password": TEST_PASSWORD}).json()
    assert ok["expires_in"] == 86400 and ok["role"] == "collector"
    res = client.post("/api/v1/collection-sessions", json={"trip_vehicle_id": str(uuid.uuid4())}, headers={"Idempotency-Key": "k"})
    assert res.status_code == 401


def test_token_expires_after_24h(client, accounts, set_now, trip1):
    set_now(2026, 9, 14, 7, 0)
    kim = Collector(client, "kim")
    set_now(2026, 9, 15, 7, 1)
    res = kim.start(trip1["vehicle"])
    assert res.status_code == 401 and "만료" in res.json()["error"]["message"]


# ---------- 세션 (FR-MC-01·02·16) ----------


def test_fr_mc_01_restart_returns_same_session(client, trip1, set_now):
    kim = Collector(client, "kim")
    first = kim.start(trip1["vehicle"])
    assert first.status_code == 201
    again = kim.start(trip1["vehicle"], writer=first.json()["writer_instance_id"])
    assert again.status_code == 200
    assert again.json()["collection_session_id"] == first.json()["collection_session_id"]


def test_fr_mc_02_other_collector_conflict(client, trip1):
    Collector(client, "kim").start(trip1["vehicle"])
    res = Collector(client, "lee").start(trip1["vehicle"])
    assert res.status_code == 409 and res.json()["error"]["code"] == "SESSION_OWNERSHIP_CONFLICT"


def test_fr_mc_16_same_account_second_device_conflict(client, trip1):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    other_device = Collector(client, "kim").start(trip1["vehicle"])  # 로컬 writer_instance_id 없음
    assert other_device.status_code == 409 and other_device.json()["error"]["code"] == "SESSION_OWNERSHIP_CONFLICT"


def test_start_stop_must_belong_to_trip(client, trip1, set_now):
    other = trip_state(client, 11)["stops"][0]["trip_stop_id"]
    res = Collector(client, "kim").start(trip1["vehicle"], start_trip_stop_id=other)
    assert res.status_code == 404


# ---------- 멱등 (01 4장, FR-OB-01·02) ----------


def test_idempotency_same_key_same_body_replays(client, trip1, set_now, trusted_settings):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    first, body = kim.observe(trip1["stops"][0], "departed", at(5), clock=clock, key="same-key")
    replay = kim.post(f"/api/v1/collection-sessions/{kim.session['collection_session_id']}/events", body, "same-key")
    assert first.status_code == 201 and replay.status_code == 201
    assert replay.json() == first.json()


def test_idempotency_key_reuse_with_different_body(client, trip1, set_now, trusted_settings):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock, key="k1")
    res, _ = kim.observe(trip1["stops"][1], "passed", at(8), clock=clock, key="k1")
    assert res.status_code == 409 and res.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_fr_ob_01_same_logical_event_new_key_stored_once(client, db, trip1, set_now, trusted_settings):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    first, body = kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    # 기대 버전이 낡았더라도 이미 확정된 논리 관측이면 기존 결과를 돌려준다 (01 4장)
    retry, _ = kim.observe(trip1["stops"][0], "departed", at(5), clock=clock, event_id="e1", sequence=1, version=1)
    assert retry.status_code == 200
    assert retry.json()["event"]["event_id"] == first.json()["event"]["event_id"]
    from app.models.observation import LocationEvent

    assert db.scalar(select(func.count()).select_from(LocationEvent).where(LocationEvent.client_event_id == "e1")) == 1


def test_fr_ob_02_changed_immutable_content_rejected(client, trip1, set_now, trusted_settings):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    res, _ = kim.observe(trip1["stops"][0], "departed", at(6), clock=clock, event_id="e1", sequence=1)
    assert res.status_code == 409 and res.json()["error"]["code"] == "EVENT_ID_REUSED"


def test_fr_mc_05_version_conflict_then_retry_keeps_logical_id(client, trip1, set_now, trusted_settings):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    stale, _ = kim.observe(trip1["stops"][1], "passed", at(8), clock=clock, version=1)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "INPUT_VERSION_CONFLICT"
    assert stale.json()["error"]["details"]["current_input_version"] == 2
    kim.reload()
    ok, _ = kim.observe(trip1["stops"][1], "passed", at(8), clock=clock, event_id="e2", sequence=2)
    assert ok.status_code == 201


# ---------- 유효성·순서 ----------


def test_valid_observation_updates_public_state(client, trip1, set_now, trusted_settings):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    res, _ = kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    body = res.json()
    assert body["event"]["validation_status"] == "valid" and body["event"]["time_confidence"] == "observed"

    set_now(2026, 9, 14, 8, 6)
    s = trip_state(client, 1)
    v = s["vehicles"][0]
    assert v["information_status"] == "observed" and s["tracked_vehicle_count"] == 1
    assert v["last_observation"]["stop_name"] == "아산캠퍼스" and v["last_observation"]["event_type"] == "departed"
    assert v["visits"][0]["visit_status"] == "departed"
    assert v["visits"][0]["unavailable_reason"] == "already_passed"
    # 구간 통계가 아직 없으므로 미래 방문은 missing_baseline (08 6장)
    assert [x["unavailable_reason"] for x in v["visits"][1:]] == ["missing_baseline"] * 4
    assert s["state_version"] == trip1["state"]["state_version"] + 1


def test_unset_settings_store_needs_review(client, trip1, set_now, monkeypatch):
    """시계·보관 설정이 미정이면 거절하지 않고 검토 대기로 보관한다 (02 6·12장)."""
    for name in ("clock_skew_tolerance_seconds", "clock_check_valid_seconds",
                 "pending_input_retention_hours", "realtime_input_window_seconds"):
        monkeypatch.setattr(settings, name, None)
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    set_now(2026, 9, 14, 8, 5)
    res, _ = kim.observe(trip1["stops"][0], "departed", at(5))
    event = res.json()["event"]
    assert res.status_code == 201 and event["validation_status"] == "needs_review"
    assert "clock_unverified" in event["review_reason"] and "retention_undefined" in event["review_reason"]
    assert trip_state(client, 1)["vehicles"][0]["information_status"] == "timetable_only"
    assert len(kim.reload()["unresolved_events"]) == 1


def test_fr_ob_05_skipped_created_with_null_time(client, trip1, set_now, trusted_settings):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    res, _ = kim.observe(trip1["stops"][3], "arrived", at(25), clock=clock)  # 탕정역·시티프라디움 건너뜀
    skipped = res.json()["skipped_events"]
    assert [e["trip_stop_id"] for e in skipped] == trip1["stops"][1:3]
    assert all(e["occurred_at"] is None and e["time_confidence"] == "inferred" and e["source"] == "system" for e in skipped)
    assert all(e["parent_event_id"] == res.json()["event"]["event_id"] and e["client_sequence"] is None for e in skipped)

    set_now(2026, 9, 14, 8, 26)
    visits = trip_state(client, 1)["vehicles"][0]["visits"]
    assert [v["visit_status"] for v in visits] == ["departed", "passed_inferred", "passed_inferred", "arrived", "upcoming"]


def test_fr_ob_11_client_sequence_continues_after_system_events(client, trip1, set_now, trusted_settings):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)   # 순번 1
    kim.observe(trip1["stops"][3], "arrived", at(25), clock=clock)   # 순번 2, 자동 누락 2개
    res, _ = kim.observe(trip1["stops"][3], "departed", at(26), clock=clock)  # 순번 3
    assert res.status_code == 201 and res.json()["event"]["client_sequence"] == 3


def test_fr_mc_06_skip_limit_requires_confirm(client, trip1, set_now, trusted_settings, monkeypatch):
    monkeypatch.setattr(settings, "max_skip_stops", 1)
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    res, body = kim.observe(trip1["stops"][3], "arrived", at(25), clock=clock)
    assert res.status_code == 409 and res.json()["error"]["code"] == "SKIP_LIMIT_EXCEEDED"
    assert [v["stop_name"] for v in res.json()["error"]["details"]["skipped_visits"]] == ["탕정역", "시티프라디움"]
    ok, _ = kim.observe(trip1["stops"][3], "arrived", at(25), clock=clock, confirm_skip=True, event_id=body["client_event_id"], sequence=body["client_sequence"])
    assert ok.status_code == 201 and len(ok.json()["skipped_events"]) == 2


def test_fr_ob_03_realtime_backward_rejected(client, trip1, set_now, trusted_settings):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    set_now(2026, 9, 14, 8, 25)
    kim.observe(trip1["stops"][3], "arrived", at(25), clock=clock)
    res, _ = kim.observe(trip1["stops"][1], "passed", at(24), clock=clock)  # 1분 전 발생·즉시 수신
    assert res.status_code == 409 and res.json()["error"]["code"] == "EVENT_ORDER_CONFLICT"


def test_fr_ob_03_06_late_supplement_replaces_skipped(client, trip1, set_now, trusted_settings):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    set_now(2026, 9, 14, 8, 25)
    kim.observe(trip1["stops"][3], "arrived", at(25), clock=clock)
    set_now(2026, 9, 14, 8, 40)  # 오프라인 큐에 있던 탕정역 기록이 창(120초)을 넘겨 도착
    res, _ = kim.observe(trip1["stops"][1], "passed", at(9), clock=clock)
    body = res.json()
    assert res.status_code == 201 and body["event"]["validation_status"] == "valid"
    assert [e["trip_stop_id"] for e in body["superseded_events"]] == [trip1["stops"][1]]
    v = trip_state(client, 1)["vehicles"][0]
    assert v["last_observation"]["stop_name"] == "천안아산역"  # 최신 위치를 뒤로 옮기지 않는다
    assert v["visits"][1]["visit_status"] == "passed"


def test_backward_without_window_goes_to_review(client, trip1, set_now, trusted_settings, monkeypatch):
    monkeypatch.setattr(settings, "realtime_input_window_seconds", None)
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    kim.observe(trip1["stops"][3], "arrived", at(25), clock=clock)
    res, _ = kim.observe(trip1["stops"][1], "passed", at(24), clock=clock)
    assert res.status_code == 201 and res.json()["event"]["review_reason"] == "order_backward_window_undefined"


def test_fr_ob_10_arrived_only_is_not_passed(client, trip1, set_now, trusted_settings):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    kim.observe(trip1["stops"][3], "arrived", at(25), clock=clock)
    set_now(2026, 9, 14, 8, 25, 30)
    s = trip_state(client, 1)
    assert s["vehicles"][0]["visits"][3]["visit_status"] == "arrived"
    # 신선한 도착은 group 0 후보 (11 3장 5)
    body = client.get(
        "/api/v1/scheduled-trips",
        params={"route_id": str(route_id("cheonan_asan")), "service_date": DAY,
                "origin_stop_id": str(stop_id("천안아산역")), "destination_stop_id": str(stop_id("아산캠퍼스"))},
    ).json()
    first = body["candidates"][0]
    assert (first["trip_no"], first["priority_group"], first["sort_basis_event_type"]) == (1, 0, "arrived")


def test_same_visit_conflicts_go_to_review(client, trip1, set_now, trusted_settings):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    kim.observe(trip1["stops"][3], "arrived", at(25), clock=clock)
    passed, _ = kim.observe(trip1["stops"][3], "passed", at(25), clock=clock)
    assert passed.json()["event"]["review_reason"] == "conflicting_event_types"
    early, _ = kim.observe(trip1["stops"][3], "departed", at(24), clock=clock)
    assert early.json()["event"]["review_reason"] == "departed_before_arrived"


def test_terminal_arrival_completes_vehicle(client, trip1, set_now, trusted_settings):
    """종점 유효 실측은 완료 근거다 (13 3장 FR-OP-18). 완료 차량은 '이번 운행 종료'가 우선한다 (03 6장)."""
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    before = trip_state(client, 1)["control_version"]
    kim.observe(trip1["stops"][4], "arrived", at(40), clock=clock, confirm_skip=True)
    set_now(2026, 9, 14, 8, 41)
    state = trip_state(client, 1)
    assert state["vehicles"][0]["operation_status"] == "completed" and state["operation_status"] == "completed"
    assert state["vehicles"][0]["visits"][4]["unavailable_reason"] == "trip_completed"
    assert state["control_version"] == before  # 관측 입력은 control_version을 올리지 않는다 (FR-OP-09)


def test_clock_skew_and_offset(client, trip1, set_now, trusted_settings):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    set_now(2026, 9, 14, 8, 0, 0)
    sid = kim.session["collection_session_id"]
    device_ahead = datetime(2026, 9, 14, 8, 0, 10, tzinfo=SEOUL)  # 단말이 10초 빠름
    begin = client.post(f"/api/v1/collection-sessions/{sid}/clock-checks", json={"device_sent_at": device_ahead.isoformat()}, headers=kim.headers).json()
    done = client.post(
        f"/api/v1/clock-checks/{begin['clock_check_id']}/complete",
        json={"device_received_at": (device_ahead + timedelta(seconds=1)).isoformat()}, headers=kim.headers,
    ).json()
    assert done["estimated_offset_seconds"] == pytest.approx(10.5) and done["uncertainty_seconds"] == pytest.approx(0.5)
    res, _ = kim.observe(trip1["stops"][0], "departed", at(5), clock=done["clock_check_id"])
    assert res.json()["event"]["review_reason"] == "clock_skew_exceeded"


def test_clock_check_of_other_session_invalid(client, trip1, set_now, trusted_settings):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    other = trip_state(client, 11)["vehicles"][0]["trip_vehicle_id"]
    kim2 = Collector(client, "kim")
    kim2.start(other)
    res, _ = kim2.observe(trip_state(client, 11)["stops"][0]["trip_stop_id"], "departed", at(5), clock=clock)
    assert res.status_code == 422 and res.json()["error"]["code"] == "CLOCK_EVIDENCE_INVALID"


# ---------- 취소 (FR-OB-08·09, FR-MC-12) ----------


def test_fr_ob_08_09_cancel_preserves_and_cascades(client, db, trip1, set_now, trusted_settings):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    res, _ = kim.observe(trip1["stops"][3], "arrived", at(25), clock=clock)
    event_id = res.json()["event"]["event_id"]
    cancel = kim.post(f"/api/v1/events/{event_id}/cancel", {"reason": "잘못 누름", "expected_input_version": kim.session["input_version"]})
    body = cancel.json()
    assert cancel.status_code == 200
    assert body["event"]["validation_status"] == "cancelled" and body["event"]["cancel_reason"] == "observation_cancelled"
    assert body["event"]["occurred_at"] is not None  # 원본 보존
    assert len(body["cascaded_events"]) == 2 and all(e["validation_status"] == "cancelled" for e in body["cascaded_events"])
    assert db.scalar(select(func.count()).select_from(ObservationReview)) == 3

    again = kim.post(f"/api/v1/events/{event_id}/cancel", {"reason": "다시", "expected_input_version": body["input_version"]})
    assert again.status_code == 409 and again.json()["error"]["code"] == "EVENT_ALREADY_CANCELLED"

    set_now(2026, 9, 14, 8, 26)
    v = trip_state(client, 1)["vehicles"][0]
    assert v["last_observation"]["stop_name"] == "아산캠퍼스"
    # 취소된 도착은 사라지고, 공시 08:25가 지났으므로 unknown (통과로 확정하지 않음)
    assert v["visits"][3]["visit_status"] == "unknown"
    assert [x["visit_status"] for x in v["visits"][1:3]] == ["unknown", "unknown"]


# ---------- 중간 탑승·종료 (FR-MC-09·10·11·13) ----------


def test_fr_mc_09_mid_boarding_not_collected(client, trip1, set_now, trusted_settings):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"], start_trip_stop_id=trip1["stops"][3])
    clock = kim.clock(set_now, at(24))
    res, _ = kim.observe(trip1["stops"][3], "arrived", at(25), clock=clock)
    assert res.json()["skipped_events"] == []  # 탑승 전 방문을 누락으로 만들지 않는다
    set_now(2026, 9, 14, 8, 26)
    visits = trip_state(client, 1)["vehicles"][0]["visits"]
    assert [v["visit_status"] for v in visits[:3]] == ["not_collected"] * 3


def test_fr_mc_10_11_13_end_is_not_completion(client, trip1, set_now, trusted_settings):
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    kim.observe(trip1["stops"][0], "departed", at(5), clock=clock)
    set_now(2026, 9, 14, 8, 30)
    ended = kim.post(
        f"/api/v1/collection-sessions/{kim.session['collection_session_id']}/end",
        {"ended_at": at(30).isoformat(), "expected_input_version": kim.session["input_version"]},
    )
    assert ended.status_code == 200 and ended.json()["collection_status"] == "ended"
    kim.session["input_version"] = ended.json()["input_version"]
    assert trip_state(client, 1)["operation_status"] == "scheduled"

    # 수집 기간 안에 발생한 대기 기록이 종료 뒤 도착 — 이력 보충, 세션은 ended 유지
    set_now(2026, 9, 14, 8, 35)
    late, _ = kim.observe(trip1["stops"][3], "arrived", at(25), clock=clock)
    assert late.status_code == 201 and late.json()["event"]["validation_status"] == "valid"
    assert kim.reload()["collection_status"] == "ended"
    after_end, _ = kim.observe(trip1["stops"][4], "arrived", at(33), clock=clock)
    assert "outside_collection_period" in after_end.json()["event"]["review_reason"]


def test_idempotency_key_required(client, trip1):
    kim = Collector(client, "kim")
    res = client.post("/api/v1/collection-sessions", json={"trip_vehicle_id": trip1["vehicle"]}, headers=kim.headers)
    assert res.status_code == 422 and res.json()["error"]["code"] == "VALIDATION_ERROR"
