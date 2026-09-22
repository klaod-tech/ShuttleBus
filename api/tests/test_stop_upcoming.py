"""11 11장 정거장 단독 조회 (FR-BC-23~28) · 03 5장 실측 시각 (FR-ST-14)."""

from datetime import datetime

from app.seed import route_id, stop_id
from app.timeutil import SEOUL
from tests.test_collection import Collector, accounts, trusted_settings  # noqa: F401

MON = "2026-09-14"


def upcoming(client, stop, route="cheonan_asan", day=MON, expect=200):
    res = client.get(
        f"/api/v1/stops/{stop_id(stop)}/upcoming", params={"route_id": str(route_id(route)), "service_date": day}
    )
    assert res.status_code == expect, res.text
    return res.json()


def _at(h, m):
    return datetime(2026, 9, 14, h, m, tzinfo=SEOUL)


# ---------- 정상 미래 항목 ----------


def test_fr_bc_23_campus_morning_two_upcoming_with_heading(client, set_now):
    set_now(2026, 9, 14, 7, 0)
    body = upcoming(client, "아산캠퍼스")
    assert body["stop_name"] == "아산캠퍼스" and body["refresh_after_seconds"] == 30
    assert body["empty_reason"] is None
    assert len(body["upcoming"]) == 2
    first = body["upcoming"][0]
    # 순1 캠퍼스 08:05 출발 — 기점 공시 출발이 유효 예측이므로 prediction_basis가 출처를 말한다
    assert (first["trip_no"], first["display_at"], first["display_event_type"], first["display_basis"]) == (
        1, "2026-09-14T08:05:00+09:00", "departed", "scheduled_departure"
    )
    assert first["is_origin"] is True and first["next_stop_name"] == "탕정역" and first["terminal_stop_name"] == "아산캠퍼스"
    assert first["reason"] is None and first["visit"]["trip_stop_id"] == first["trip_stop_id"]
    # 두 항목은 시각 순이며 모두 미래
    times = [x["display_at"] for x in body["upcoming"]]
    assert times == sorted(times) and all(t >= "2026-09-14T07:00:00+09:00" for t in times)


def test_fr_bc_24_arrival_before_departure_at_station(client, set_now):
    """정거장 안내의 대표 시각은 같은 출처 안에서 도착 → 출발 순 (후보 검색의 출발 우선과 반대)."""
    set_now(2026, 9, 14, 7, 0)
    body = upcoming(client, "천안아산역")
    rows = body["upcoming"] + body["attention"] + body["reference_timetable"]
    for row in rows:
        if row["display_basis"] == "timetable" and row["stop"]["scheduled_arrival_at"]:
            assert row["display_event_type"] == "arrived", row
    # 순1은 천안아산역에 08:25 도착(중간 방문), 순2는 08:35 기점 출발 — 도착 시각이 그대로 대표 시각이다
    head = [(r["trip_no"], r["display_at"], r["display_event_type"]) for r in body["upcoming"]]
    assert head == [(1, "2026-09-14T08:25:00+09:00", "arrived"), (2, "2026-09-14T08:35:00+09:00", "departed")]
    assert body["upcoming"][0]["is_terminal"] is False and body["upcoming"][0]["next_stop_name"] == "아산캠퍼스"


def test_fr_bc_25_two_slots_are_separate_rows(client, db, set_now):
    from app.candidates.upcoming import find_stop_upcoming

    now = set_now(2026, 9, 14, 7, 0)
    # 상한 2개 때문에 API 응답에는 순4가 안 보이므로 상한을 풀고 직접 확인한다
    result = find_stop_upcoming(db, route_id("cheonan_asan"), datetime(2026, 9, 14).date(), stop_id("천안아산역"), now, limit=100)
    rows = [r for r in result.upcoming + result.attention + result.reference_timetable if r["trip_no"] == 4]
    assert sorted(r["vehicle_slot"] for r in rows) == [1, 2]
    assert len({r["trip_vehicle_id"] for r in rows}) == 2
    # API 응답은 정상 미래 항목을 2개로 자른다
    assert len(upcoming(client, "천안아산역")["upcoming"]) == 2


# ---------- 확인 항목·제외 ----------


def test_fr_bc_26_passed_scheduled_time_goes_to_attention_not_upcoming(client, set_now):
    set_now(2026, 9, 14, 8, 10)
    body = upcoming(client, "아산캠퍼스")
    trip1 = [r for r in body["upcoming"] if r["trip_no"] == 1 and r["is_origin"]]
    assert trip1 == []  # 08:05 공시 출발이 지났고 관측이 없다 — 미래 목록에 되살리지 않는다
    waiting = [r for r in body["attention"] if r["trip_no"] == 1 and r["is_origin"]]
    assert len(waiting) == 1
    assert (waiting[0]["reason"], waiting[0]["display_at"]) == ("prediction_expired", "2026-09-14T08:05:00+09:00")
    assert body["upcoming"][0]["display_at"] >= "2026-09-14T08:10:00+09:00"


def test_fr_bc_27_arrived_observation_is_attention_with_observed_time(client, set_now, accounts, trusted_settings):  # noqa: F811
    set_now(2026, 9, 14, 7, 50)
    state_body = client.get("/api/v1/scheduled-trips", params={"route_id": str(route_id("cheonan_asan")), "service_date": MON}).json()
    trip = next(t for t in state_body["trips"] if t["trip_no"] == 1)
    state = client.get(f"/api/v1/scheduled-trips/{trip['trip_id']}/state").json()
    vehicle = state["vehicles"][0]["trip_vehicle_id"]
    station_stop = next(s for s in state["stops"] if s["stop_name"] == "천안아산역")

    kim = Collector(client, "kim")
    kim.start(vehicle)
    clock = kim.clock(set_now, _at(8, 20))
    # 앞 세 방문(캠퍼스·탕정역·시티프라디움)은 자동 누락으로 기록된다 — 상한을 넘을 수 있어 확인 옵션을 켠다
    res, _ = kim.observe(station_stop["trip_stop_id"], "arrived", _at(8, 24), clock=clock, confirm_skip=True)
    assert res.status_code == 201, res.text

    set_now(2026, 9, 14, 8, 25)
    body = upcoming(client, "천안아산역")
    row = next(r for r in body["attention"] if r["trip_vehicle_id"] == vehicle)
    assert (row["reason"], row["display_basis"], row["display_event_type"]) == ("arrived_confirmed", "observed_event", "arrived")
    assert row["display_at"] == "2026-09-14T08:24:00+09:00"
    assert row["information_status"] == "observed"
    # 같은 방문은 미래 목록에 다시 들어가지 않는다
    assert all(not (r["trip_vehicle_id"] == vehicle and r["trip_stop_id"] == station_stop["trip_stop_id"]) for r in body["upcoming"])
    # FR-ST-14 — 03 visits[]에 실측 시각이 실린다
    assert row["visit"]["observed_arrival_at"] == "2026-09-14T08:24:00+09:00"
    assert row["visit"]["observed_departure_at"] is None and row["visit"]["observed_passed_at"] is None

    # 신선도가 지나면 오래된 도착으로 바뀐다
    set_now(2026, 9, 14, 8, 40)
    body = upcoming(client, "천안아산역")
    row = next(r for r in body["attention"] if r["trip_vehicle_id"] == vehicle)
    assert row["reason"] == "arrival_observation_stale"


# ---------- 빈 결과 사유 ----------


def test_fr_bc_28_empty_reasons(client, set_now):
    set_now(2026, 9, 14, 7, 0)
    # 이 노선이 지나지 않는 정거장
    assert upcoming(client, "천안역")["empty_reason"] == "stop_not_on_route"
    # 지난 날짜
    assert upcoming(client, "아산캠퍼스", day="2026-09-11")["empty_reason"] == "past_date"
    # 운행 없는 날 (토요일 온양)
    body = upcoming(client, "온양온천역", route="onyang", day="2026-09-05")
    assert body["schedule_status"] == "no_service" and body["empty_reason"] == "schedule_unavailable"
    # 남은 운행 없음 — 밤늦게
    set_now(2026, 9, 14, 23, 50)
    late = upcoming(client, "아산캠퍼스")
    assert late["upcoming"] == []
    assert late["empty_reason"] in ("no_remaining_service", "unconfirmed_remaining")
    if late["empty_reason"] == "no_remaining_service":
        assert late["attention"] == [] and late["reference_timetable"] == []


def test_unknown_ids_are_404(client, set_now):
    import uuid

    set_now(2026, 9, 14, 7, 0)
    res = client.get(f"/api/v1/stops/{uuid.uuid4()}/upcoming", params={"route_id": str(route_id("cheonan_asan")), "service_date": MON})
    assert res.status_code == 404
    res = client.get(f"/api/v1/stops/{stop_id('아산캠퍼스')}/upcoming", params={"route_id": str(uuid.uuid4()), "service_date": MON})
    assert res.status_code == 404


def test_visit_out_has_observed_time_fields_even_without_observation(client, set_now):
    set_now(2026, 9, 14, 7, 0)
    body = client.get("/api/v1/scheduled-trips", params={"route_id": str(route_id("cheonan_asan")), "service_date": MON}).json()
    trip = next(t for t in body["trips"] if t["trip_no"] == 1)
    state = client.get(f"/api/v1/scheduled-trips/{trip['trip_id']}/state").json()
    visit = state["vehicles"][0]["visits"][0]
    assert {"observed_arrival_at", "observed_departure_at", "observed_passed_at"} <= visit.keys()
    assert visit["observed_arrival_at"] is None
