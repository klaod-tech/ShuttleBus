"""03 상태 계약 (FR-ST) — 시간표만 있는 단계."""

from sqlalchemy import update

from app.models.calendar import ScheduledTripStop
from app.seed import route_id

MON = "2026-09-14"


def trip_list(client, route="cheonan_asan", day=MON):
    body = client.get("/api/v1/scheduled-trips", params={"route_id": str(route_id(route)), "service_date": day}).json()
    return {t["trip_no"]: t for t in body["trips"]}, body


def state(client, trip_id):
    res = client.get(f"/api/v1/scheduled-trips/{trip_id}/state")
    assert res.status_code == 200
    return res.json()


def test_trip_list_mode(client, set_now):
    set_now(2026, 9, 14, 7, 0)
    trips, body = trip_list(client)
    assert body["schedule_status"] == "available" and len(trips) == 42
    assert trips[2]["origin_stop_name"] == "천안아산역"
    assert trips[4]["scheduled_vehicle_count"] == 2
    assert trips[26]["student_union_boarding"] is True
    assert trips[27]["student_union_boarding"] is False
    assert trips[2]["student_union_boarding"] is False  # 캠퍼스 출발이 없는 회차

    sunday, _ = trip_list(client, day="2026-09-13")
    assert all(t["student_union_boarding"] is None for t in sunday.values())


def test_trip_list_not_available(client, set_now):
    set_now(2026, 9, 24, 7, 0)
    _, body = trip_list(client, day="2026-09-24")
    assert body["schedule_status"] == "no_service" and body["trips"] == []


def test_fr_st_01_two_vehicles_share_stops(client, set_now):
    set_now(2026, 9, 14, 7, 0)
    trips, _ = trip_list(client)
    s = state(client, trips[4]["trip_id"])
    assert [v["vehicle_slot"] for v in s["vehicles"]] == [1, 2]
    stop_ids = [x["trip_stop_id"] for x in s["stops"]]
    for v in s["vehicles"]:
        assert [x["trip_stop_id"] for x in v["visits"]] == stop_ids


def test_fr_st_02_state_shape(client, set_now):
    set_now(2026, 9, 14, 7, 0)
    trips, _ = trip_list(client)
    s = state(client, trips[1]["trip_id"])
    assert {"trip_id", "route_id", "route_version_id", "service_date", "state_version", "control_version",
            "server_time", "schedule_status", "operation_status", "scheduled_vehicle_count",
            "tracked_vehicle_count", "stops", "vehicles"} <= set(s)
    assert s["server_time"] == "2026-09-14T07:00:00+09:00"
    assert s["tracked_vehicle_count"] == 0
    v = s["vehicles"][0]
    assert (v["information_status"], v["position_status"], v["last_observation"], v["last_position"]) == (
        "timetable_only", "not_enabled", None, None
    )
    assert [x["stop_name"] for x in s["stops"]] == ["아산캠퍼스", "탕정역", "시티프라디움", "천안아산역", "아산캠퍼스"]


def test_fr_st_13_origin_uses_scheduled_departure(client, set_now):
    set_now(2026, 9, 14, 7, 0)
    trips, _ = trip_list(client)
    visits = state(client, trips[1]["trip_id"])["vehicles"][0]["visits"]
    origin = visits[0]
    assert (origin["estimated_event_at"], origin["target_event_type"], origin["prediction_basis"],
            origin["basis_observation"], origin["unavailable_reason"]) == (
        "2026-09-14T08:05:00+09:00", "departed", "scheduled_departure", None, None
    )
    # 구간 통계가 없으므로 나머지 방문은 missing_baseline. 종점 목표 사건은 arrived
    assert [v["unavailable_reason"] for v in visits[1:]] == ["missing_baseline"] * 4
    assert visits[-1]["target_event_type"] == "arrived"
    assert all(v["visit_status"] == "upcoming" for v in visits)


def test_fr_st_03_and_05_past_visits_kept_and_expired(client, set_now):
    set_now(2026, 9, 14, 9, 0)
    trips, _ = trip_list(client)
    s = state(client, trips[1]["trip_id"])  # 08:05 출발 · 08:40 도착
    assert len(s["stops"]) == 5  # 지난 방문도 응답에서 지우지 않는다
    visits = s["vehicles"][0]["visits"]
    assert (visits[0]["estimated_event_at"], visits[0]["unavailable_reason"]) == (None, "prediction_expired")
    assert s["stops"][0]["scheduled_departure_at"] == "2026-09-14T08:05:00+09:00"  # 공시 시각은 유지
    # 예정 시각이 지났다고 통과로 확정하지 않는다
    assert all(v["visit_status"] == "unknown" for v in visits)


def test_via_visit_uses_next_published_time_for_upcoming(client, set_now):
    set_now(2026, 9, 14, 8, 20)
    trips, _ = trip_list(client)
    visits = state(client, trips[1]["trip_id"])["vehicles"][0]["visits"]
    # 08:05 출발은 지났고 탕정역·시티프라디움은 자기 시각이 없어 다음 공시(천안아산역 08:25)를 상한으로 본다
    assert [v["visit_status"] for v in visits] == ["unknown", "upcoming", "upcoming", "upcoming", "upcoming"]


def test_fr_st_12_no_basis_is_null_not_timetable(client, db, set_now):
    set_now(2026, 9, 14, 7, 0)
    trips, _ = trip_list(client)
    s = state(client, trips[1]["trip_id"])
    origin_id = s["stops"][0]["trip_stop_id"]
    db.execute(update(ScheduledTripStop).where(ScheduledTripStop.trip_stop_id == origin_id).values(scheduled_departure_at=None))
    origin = state(client, trips[1]["trip_id"])["vehicles"][0]["visits"][0]
    assert (origin["prediction_basis"], origin["basis_observation"], origin["unavailable_reason"]) == (None, None, "no_observation")


def test_state_unknown_trip_is_404(client):
    res = client.get("/api/v1/scheduled-trips/00000000-0000-0000-0000-000000000000/state")
    assert res.status_code == 404 and res.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_cancelled_trip_reason(client, db, set_now):
    from app.models.calendar import ScheduledTrip

    set_now(2026, 9, 14, 7, 0)
    trips, _ = trip_list(client)
    db.execute(update(ScheduledTrip).where(ScheduledTrip.scheduled_trip_id == trips[1]["trip_id"]).values(operation_status="cancelled"))
    visits = state(client, trips[1]["trip_id"])["vehicles"][0]["visits"]
    assert all(v["unavailable_reason"] == "trip_cancelled" and v["estimated_event_at"] is None for v in visits)
