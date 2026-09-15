"""11 탑승 후보 (FR-BC)."""

from datetime import datetime, timedelta

from sqlalchemy import update

from app.candidates.classify import CandidateInput, classify
from app.models.calendar import ScheduledTrip
from app.seed import route_id, stop_id
from app.timeutil import SEOUL

MON = "2026-09-14"
NOW = datetime(2026, 9, 14, 12, 0, tzinfo=SEOUL)


def search(client, origin, destination, route="cheonan_asan", day=MON):
    res = client.get(
        "/api/v1/scheduled-trips",
        params={
            "route_id": str(route_id(route)),
            "service_date": day,
            "origin_stop_id": str(stop_id(origin)),
            "destination_stop_id": str(stop_id(destination)),
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def base_input(**kw) -> CandidateInput:
    values = dict(
        trip_operation_status="scheduled",
        vehicle_operation_status="scheduled",
        boarding_policy="allowed",
        alighting_policy="allowed",
        boarding_visit_status="upcoming",
        boarding_arrived_observed_at=None,
        boarding_estimated_event_at=None,
        boarding_target_event_type=None,
        boarding_unavailable_reason="missing_baseline",
        scheduled_departure_at=None,
        scheduled_arrival_at=None,
        scheduled_unspecified_at=None,
    )
    values.update(kw)
    return CandidateInput(**values)


# ---------- API ----------


def test_campus_to_station_morning(client, set_now):
    set_now(2026, 9, 14, 7, 0)
    body = search(client, "아산캠퍼스", "천안아산역")
    first = body["candidates"][0]
    # 캠퍼스 출발이 있는 회차만 쌍이 생긴다 (순2~10은 천안아산역 기점)
    assert first["trip_no"] == 1
    assert (first["sort_at"], first["sort_basis_event_type"], first["priority_group"]) == (
        "2026-09-14T08:05:00+09:00", "departed", 1
    )
    assert first["route_segment_stop_names"] == ["아산캠퍼스", "탕정역", "시티프라디움", "천안아산역"]
    assert body["recommended_candidate"]["trip_vehicle_id"] == first["trip_vehicle_id"]
    assert body["refresh_after_seconds"] == 30
    assert body["no_candidate_reason"] is None
    assert {c["trip_no"] for c in body["candidates"]} == {1, *range(11, 43)}


def test_fr_bc_10_two_slots_are_independent(client, set_now):
    set_now(2026, 9, 14, 7, 0)
    body = search(client, "천안아산역", "아산캠퍼스")
    trip4 = [c for c in body["candidates"] if c["trip_no"] == 4]
    assert [c["vehicle_slot"] for c in trip4] == [1, 2]
    assert trip4[0]["trip_vehicle_id"] != trip4[1]["trip_vehicle_id"]


def test_station_to_campus_sorted_by_station_time(client, set_now):
    set_now(2026, 9, 14, 7, 0)
    body = search(client, "천안아산역", "아산캠퍼스")
    assert body["unverified_candidates"] == []
    assert all(c["boarding_stop"]["boarding_policy"] == "allowed" for c in body["candidates"])
    # 순1은 천안아산역 도착 08:25(중간 방문), 순2부터는 천안아산역 기점 출발 08:35…
    head = [(c["trip_no"], c["sort_at"], c["sort_basis_event_type"]) for c in body["candidates"][:3]]
    assert head == [
        (1, "2026-09-14T08:25:00+09:00", "arrived"),
        (2, "2026-09-14T08:35:00+09:00", "departed"),
        (3, "2026-09-14T08:40:00+09:00", "departed"),
    ]


def test_station_to_campus_afternoon(client, set_now):
    set_now(2026, 9, 14, 13, 0)
    body = search(client, "천안아산역", "아산캠퍼스")
    first = body["candidates"][0]
    assert (first["trip_no"], first["sort_at"]) == (21, "2026-09-14T13:30:00+09:00")


def test_fr_bc_01_02_onyang_station_ordering(client, set_now):
    set_now(2026, 9, 14, 7, 0)
    body = search(client, "온양온천역", "아산캠퍼스", route="onyang")
    order = [(c["trip_no"], c["sort_at"]) for c in body["candidates"]]
    # 순1 08:10 → 순2 08:45(기점 출발) → 순3 08:50(온양온천역 도착). 순3 기점 주은아파트 08:40을 끌어오지 않는다
    assert order[:3] == [
        (1, "2026-09-14T08:10:00+09:00"),
        (2, "2026-09-14T08:45:00+09:00"),
        (3, "2026-09-14T08:50:00+09:00"),
    ]
    trip3 = next(c for c in body["candidates"] if c["trip_no"] == 3)
    assert trip3["origin_scheduled_departure_at"] == "2026-09-14T08:40:00+09:00"


def test_fr_bc_03_destination_before_origin(client, set_now):
    set_now(2026, 9, 14, 7, 0)
    body = search(client, "천안아산역", "탕정역")
    assert body["candidates"] == [] and body["unverified_candidates"] == []
    assert body["no_candidate_reason"] == "no_matching_journey"


def test_fr_bc_04_only_requested_route(client, set_now):
    set_now(2026, 9, 14, 7, 0)
    body = search(client, "아산캠퍼스", "천안아산역")
    assert {c["route_id"] for c in body["candidates"] + body["unverified_candidates"]} == {str(route_id("cheonan_asan"))}


def test_fr_bc_05_16_loop_journey_holiday_cheonan(client, set_now):
    set_now(2026, 9, 13, 7, 0)
    body = search(client, "천안아산역", "천안아산역", route="cheonan", day="2026-09-13")
    items = body["candidates"] + body["unverified_candidates"]
    assert items and all(c["is_same_stop_loop"] for c in items)
    assert all((c["boarding_stop_sequence"], c["alighting_stop_sequence"]) == (3, 9) for c in items)
    assert all(c["boarding_trip_stop_id"] != c["alighting_trip_stop_id"] for c in items)


def test_fr_bc_09_unknown_policy_is_unverified(client, set_now):
    set_now(2026, 9, 14, 7, 0)
    body = search(client, "아산캠퍼스", "탕정역")
    assert body["candidates"] == []
    assert all("alighting_policy_unknown" in c["unverified_reasons"] for c in body["unverified_candidates"])
    assert body["no_candidate_reason"] is None  # FR-BC-12 확인 필요가 있으면 종료 단정 없음


def test_fr_bc_11_unavailable_date_is_200(client, set_now):
    set_now(2026, 9, 24, 7, 0)
    body = search(client, "아산캠퍼스", "천안아산역", day="2026-09-24")
    assert body["schedule_status"] == "no_service"
    assert body["no_candidate_reason"] == "schedule_unavailable"
    assert (body["next_known_service_date"], body["has_unknown_dates_before"]) == ("2026-09-27", False)


def test_fr_bc_12_evening_keeps_past_trips_as_unverified(client, set_now):
    set_now(2026, 9, 14, 23, 0)
    body = search(client, "아산캠퍼스", "천안아산역")
    assert body["candidates"] == [] and body["unverified_candidates"]
    assert body["no_candidate_reason"] is None
    assert body["next_known_service_date"] == "2026-09-15"


def test_fr_bc_14_deterministic_order(client, set_now):
    set_now(2026, 9, 14, 7, 0)
    a = search(client, "천안아산역", "아산캠퍼스")
    b = search(client, "천안아산역", "아산캠퍼스")
    key = lambda body: [(c["trip_vehicle_id"], c["boarding_trip_stop_id"]) for c in body["candidates"] + body["unverified_candidates"]]
    assert key(a) == key(b)
    nulls = [c["sort_at"] is None for c in a["unverified_candidates"]]
    assert nulls == sorted(nulls)  # null은 마지막


def test_fr_bc_15_only_origin_is_422(client):
    res = client.get(
        "/api/v1/scheduled-trips",
        params={"route_id": str(route_id("cheonan_asan")), "service_date": MON, "origin_stop_id": str(stop_id("아산캠퍼스"))},
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_cancelled_trip_excluded(client, db, set_now):
    set_now(2026, 9, 14, 7, 0)
    body = search(client, "아산캠퍼스", "천안아산역")
    victim = body["candidates"][0]["trip_id"]
    db.execute(update(ScheduledTrip).where(ScheduledTrip.scheduled_trip_id == victim).values(operation_status="cancelled"))
    after = search(client, "아산캠퍼스", "천안아산역")
    assert victim not in {c["trip_id"] for c in after["candidates"] + after["unverified_candidates"]}


def test_unknown_stop_is_404(client):
    res = client.get(
        "/api/v1/scheduled-trips",
        params={
            "route_id": str(route_id("cheonan_asan")), "service_date": MON,
            "origin_stop_id": "00000000-0000-0000-0000-000000000000", "destination_stop_id": str(stop_id("아산캠퍼스")),
        },
    )
    assert res.status_code == 404


# ---------- 분류 순수 함수 ----------


def test_fr_bc_06_fresh_arrived_is_group_0():
    arrived = NOW - timedelta(seconds=60)
    r = classify(base_input(boarding_visit_status="arrived", boarding_arrived_observed_at=arrived), NOW)
    assert (r.kind, r.priority_group, r.sort_at, r.sort_basis_event_type) == ("candidate", 0, arrived, "arrived")


def test_fr_bc_07_stale_arrived_is_unverified():
    arrived = NOW - timedelta(seconds=181)
    r = classify(base_input(boarding_visit_status="arrived", boarding_arrived_observed_at=arrived), NOW)
    assert (r.kind, r.reasons) == ("unverified", ("arrival_observation_stale",))


def test_fr_bc_08_not_allowed_excluded():
    assert classify(base_input(alighting_policy="not_allowed"), NOW).kind == "excluded"
    assert classify(base_input(boarding_policy="not_allowed"), NOW).kind == "excluded"


def test_boarding_visit_passed_excluded():
    for status in ("departed", "passed", "passed_inferred"):
        assert classify(base_input(boarding_visit_status=status), NOW).kind == "excluded"


def test_fr_bc_17_departure_before_arrival_in_same_source():
    r = classify(base_input(scheduled_departure_at=NOW + timedelta(minutes=10), scheduled_arrival_at=NOW + timedelta(minutes=5)), NOW)
    assert (r.sort_at, r.sort_basis_event_type) == (NOW + timedelta(minutes=10), "departed")


def test_fr_bc_18_passed_prediction_basis():
    eta = NOW + timedelta(minutes=7)
    r = classify(base_input(boarding_estimated_event_at=eta, boarding_target_event_type="passed", boarding_unavailable_reason=None), NOW)
    assert (r.kind, r.sort_basis_event_type) == ("candidate", "passed")


def test_fr_bc_19_unspecified_only_is_unverified():
    r = classify(base_input(scheduled_unspecified_at=NOW + timedelta(minutes=10)), NOW)
    assert (r.kind, r.sort_at, r.reasons) == ("unverified", None, ("scheduled_event_type_unspecified",))


def test_fr_bc_20_prediction_beats_published_departure():
    r = classify(
        base_input(
            boarding_estimated_event_at=NOW + timedelta(minutes=20),
            boarding_target_event_type="arrived",
            boarding_unavailable_reason=None,
            scheduled_departure_at=NOW + timedelta(minutes=10),
        ),
        NOW,
    )
    assert (r.sort_at, r.sort_basis_event_type) == (NOW + timedelta(minutes=20), "arrived")


def test_fr_bc_21_fresh_arrived_sorted_by_arrival_even_with_departure_eta():
    arrived = NOW - timedelta(seconds=30)
    r = classify(
        base_input(
            boarding_visit_status="arrived",
            boarding_arrived_observed_at=arrived,
            boarding_estimated_event_at=NOW + timedelta(minutes=2),
            boarding_target_event_type="departed",
        ),
        NOW,
    )
    assert (r.priority_group, r.sort_at) == (0, arrived)


def test_fr_bc_22_contrary_evidence_blocks_future_published():
    for reason in ("prediction_expired", "stale_observation", "position_unverified", "awaiting_departure"):
        r = classify(base_input(boarding_unavailable_reason=reason, scheduled_departure_at=NOW + timedelta(minutes=30)), NOW)
        assert (r.kind, r.reasons, r.sort_at) == ("unverified", (reason,), NOW + timedelta(minutes=30))


def test_past_published_time_is_reference_only():
    r = classify(base_input(scheduled_departure_at=NOW - timedelta(minutes=1)), NOW)
    assert (r.kind, r.reasons) == ("unverified", ("scheduled_time_passed",))
