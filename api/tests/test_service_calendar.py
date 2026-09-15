"""05 운행 달력 검증 기준 (FR-SC) + 날짜별 정거장 API."""

import dataclasses
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select, update

from app.calendar.resolve import CoverageInfo, resolve
from app.calendar.service import (
    ensure_scheduled_trips,
    find_next_service_date,
    load_calendar_data,
    resolve_service_calendar,
)
from app.models.calendar import ScheduledTrip, ScheduledTripStop, ServiceCalendar, TripVehicle
from app.models.reference import RouteStop, Stop, TripTemplate
from app.seed import route_id, route_stop_id, sid, stop_id, template_id, version_id
from app.timetable.source_2026_2 import ROUTES

ALL_ROUTES = [route_id(code) for code in ROUTES]
TODAY = date(2026, 9, 1)  # 과거 판정 보존 규칙이 시험 날짜에 끼어들지 않게 고정


def status(db, route, d):
    return resolve(load_calendar_data(db), route_id(route), d).schedule_status


def generate_all(db, d, to=None):
    for r in ALL_ROUTES:
        ensure_scheduled_trips(db, r, d, to or d, today=TODAY)


def trips_on(db, d):
    return db.scalars(select(ScheduledTrip).where(ScheduledTrip.service_date == d)).all()


def slots_on(db, d):
    return db.scalar(
        select(func.count())
        .select_from(TripVehicle)
        .join(ScheduledTrip, ScheduledTrip.scheduled_trip_id == TripVehicle.scheduled_trip_id)
        .where(ScheduledTrip.service_date == d)
    )


def trip_for(db, source_row_key, d):
    return db.scalar(
        select(ScheduledTrip).where(ScheduledTrip.source_row_key == source_row_key, ScheduledTrip.service_date == d)
    )


def test_fr_sc_01_four_statuses_distinct(db):
    assert status(db, "cheonan_asan", date(2026, 9, 10)) == "available"
    assert status(db, "cheonan_asan", date(2026, 9, 24)) == "no_service"
    assert status(db, "cheonan_asan", date(2026, 8, 31)) == "out_of_period"
    assert status(db, "cheonan_asan", date(2026, 12, 15)) == "out_of_period"

    data = load_calendar_data(db)
    data.coverage.pop((template_id("weekday"), route_id("cheonan_asan")))
    res = resolve(data, route_id("cheonan_asan"), date(2026, 9, 10))
    assert res.schedule_status == "unknown"


def test_semester_boundaries_inclusive(db):
    assert status(db, "cheonan_asan", date(2026, 9, 1)) == "available"
    assert status(db, "cheonan_asan", date(2026, 12, 14)) == "available"


def test_fr_sc_02_exception_beats_weekend_template(db):
    for d in (date(2026, 9, 26), date(2026, 10, 3), date(2026, 10, 4)):
        assert status(db, "cheonan_asan", d) == "no_service"


def test_fr_sc_03_and_13_alternate_holiday_uses_sunday_rules(db):
    d = date(2026, 10, 5)
    res = resolve(load_calendar_data(db), route_id("cheonan"), d)
    assert (res.schedule_status, res.actual_weekday, res.effective_service_weekday, res.effective_day_type) == (
        "available", "mon", "sun", "sunday_holiday"
    )
    assert res.applied_schedule_template_id == template_id("sunday_holiday")
    generate_all(db, d)
    assert len(trips_on(db, d)) == 16
    assert slots_on(db, d) == 16  # 월요일 2대 조건 미적용


def test_fr_sc_04_weekend_onyang_no_service(db):
    assert status(db, "onyang", date(2026, 9, 5)) == "no_service"
    assert status(db, "onyang", date(2026, 9, 6)) == "no_service"
    assert status(db, "onyang", date(2026, 9, 7)) == "available"


def test_fr_sc_05_friday_excludes_fri_x_trips(db):
    d = date(2026, 9, 11)
    generate_all(db, d)
    assert len(trips_on(db, d)) == 61
    assert trip_for(db, "2026-2:weekday:cheonan_asan:2", d) is None
    assert trip_for(db, "2026-2:weekday:cheonan_asan:1", d) is not None


@pytest.mark.parametrize(
    "d,expected",
    [
        (date(2026, 9, 14), 122),  # 월
        (date(2026, 9, 15), 122),  # 화
        (date(2026, 9, 16), 121),  # 수
        (date(2026, 9, 17), 121),  # 목
        (date(2026, 9, 11), 61),   # 금
        (date(2026, 9, 12), 12),   # 토
        (date(2026, 9, 13), 16),   # 일
    ],
)
def test_fr_sc_06_slots_by_weekday(db, d, expected):
    generate_all(db, d)
    assert slots_on(db, d) == expected


def test_two_vehicle_trip_has_two_slots(db):
    d = date(2026, 9, 14)
    ensure_scheduled_trips(db, route_id("cheonan_asan"), d, d, today=TODAY)
    t4 = trip_for(db, "2026-2:weekday:cheonan_asan:4", d)
    slots = db.scalars(select(TripVehicle.vehicle_slot).where(TripVehicle.scheduled_trip_id == t4.scheduled_trip_id)).all()
    assert sorted(slots) == [1, 2] and t4.scheduled_vehicle_count == 2
    assert all(v.information_status == "timetable_only" for v in db.scalars(select(TripVehicle).where(TripVehicle.scheduled_trip_id == t4.scheduled_trip_id)))


def test_fr_sc_07_generation_idempotent(db):
    d = date(2026, 9, 14)
    generate_all(db, d)
    first = (len(trips_on(db, d)), slots_on(db, d), db.scalar(select(func.count()).select_from(ScheduledTripStop)))
    generate_all(db, d)
    second = (len(trips_on(db, d)), slots_on(db, d), db.scalar(select(func.count()).select_from(ScheduledTripStop)))
    assert first == second


def test_fr_sc_08_backfill_after_missed_runs(db):
    r = route_id("cheonan_asan")
    ensure_scheduled_trips(db, r, date(2026, 9, 14), date(2026, 9, 14), today=TODAY)
    report = ensure_scheduled_trips(db, r, date(2026, 9, 14), date(2026, 9, 18), today=TODAY)
    # 화·수·목 42회씩, 금 21회. 월요일은 이미 있으므로 새로 만들지 않는다
    assert report.created_trips == 42 * 3 + 21


def test_fr_sc_09_no_visits_before_origin(db):
    d = date(2026, 9, 14)
    ensure_scheduled_trips(db, route_id("cheonan_asan"), d, d, today=TODAY)
    ensure_scheduled_trips(db, route_id("onyang"), d, d, today=TODAY)

    def visit_names(key):
        t = trip_for(db, key, d)
        rows = db.execute(
            select(Stop.name, ScheduledTripStop.stop_sequence)
            .join(RouteStop, RouteStop.route_stop_id == ScheduledTripStop.route_stop_id)
            .join(Stop, Stop.stop_id == RouteStop.stop_id)
            .where(ScheduledTripStop.scheduled_trip_id == t.scheduled_trip_id)
            .order_by(ScheduledTripStop.stop_sequence)
        ).all()
        return t, [n for n, _ in rows]

    t2, names = visit_names("2026-2:weekday:cheonan_asan:2")
    assert names == ["천안아산역", "아산캠퍼스"]
    origin = db.get(ScheduledTripStop, t2.origin_trip_stop_id)
    assert origin.stop_sequence == 4
    assert (origin.boarding_policy, origin.alighting_policy) == ("allowed", "not_allowed")

    _, onyang2 = visit_names("2026-2:weekday:onyang:2")
    assert onyang2 == ["온양온천역", "아산터미널", "권곡초 버스정류장", "아산캠퍼스"]

    _, onyang1 = visit_names("2026-2:weekday:onyang:1")
    assert onyang1[0] == "주은아파트 버스정류장"


def test_fr_sc_10_existing_trip_not_rewritten(db):
    d = date(2026, 9, 14)
    ensure_scheduled_trips(db, route_id("cheonan_asan"), d, d, today=TODAY)
    t1 = trip_for(db, "2026-2:weekday:cheonan_asan:1", d)
    origin = db.get(ScheduledTripStop, t1.origin_trip_stop_id)
    before = origin.scheduled_departure_at
    db.execute(update(TripTemplate).where(TripTemplate.trip_template_id == t1.trip_template_id).values(note="개정"))
    ensure_scheduled_trips(db, route_id("cheonan_asan"), d, d, today=TODAY)
    db.refresh(origin)
    assert origin.scheduled_departure_at == before


def test_fr_sc_11_stops_require_service_date(client):
    res = client.get(f"/api/v1/routes/{route_id('cheonan')}/stops")
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"
    assert res.json()["error"]["retryable"] is False


def test_fr_sc_12_times_stored_as_utc_from_seoul(db, monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    d = date(2026, 9, 10)
    ensure_scheduled_trips(db, route_id("cheonan_asan"), d, d, today=TODAY)
    t1 = trip_for(db, "2026-2:weekday:cheonan_asan:1", d)
    origin = db.get(ScheduledTripStop, t1.origin_trip_stop_id)
    assert origin.scheduled_departure_at.astimezone(timezone.utc) == datetime(2026, 9, 9, 23, 5, tzinfo=timezone.utc)
    campus_arrival = db.scalar(
        select(ScheduledTripStop).where(
            ScheduledTripStop.scheduled_trip_id == t1.scheduled_trip_id,
            ScheduledTripStop.route_stop_id == route_stop_id("cheonan_asan", "general", 5),
        )
    )
    assert campus_arrival.scheduled_arrival_at.astimezone(timezone.utc) == datetime(2026, 9, 9, 23, 40, tzinfo=timezone.utc)
    station = db.scalar(
        select(ScheduledTripStop).where(
            ScheduledTripStop.scheduled_trip_id == t1.scheduled_trip_id,
            ScheduledTripStop.route_stop_id == route_stop_id("cheonan_asan", "general", 4),
        )
    )
    # 외부역 열 시각은 도착 시각이다. 출발 칸에 복제하지 않는다
    assert station.scheduled_arrival_at.astimezone(timezone.utc) == datetime(2026, 9, 9, 23, 25, tzinfo=timezone.utc)
    assert station.scheduled_unspecified_at is None and station.scheduled_departure_at is None
    assert station.verification_status == "verified"


def test_fr_sc_14_partial_import_is_unknown(db):
    data = load_calendar_data(db)
    key = (template_id("weekday"), route_id("cheonan_asan"))
    data.trips[key] = data.trips[key][:-1]
    assert resolve(data, route_id("cheonan_asan"), date(2026, 9, 10)).schedule_status == "unknown"

    data = load_calendar_data(db)
    data.coverage[key] = CoverageInfo("confirmed_service", None)
    assert resolve(data, route_id("cheonan_asan"), date(2026, 9, 10)).schedule_status == "unknown"


def test_fr_sc_15_missing_sun_vehicle_key_is_data_error(db):
    d = date(2026, 9, 13)
    victim = sid("trip_template", "2026-2:sunday_holiday:cheonan:1")
    db.execute(update(TripTemplate).where(TripTemplate.trip_template_id == victim).values(vehicle_count_by_weekday={}))
    report = ensure_scheduled_trips(db, route_id("cheonan"), d, d, today=TODAY)
    assert report.created_trips == 0
    assert db.get(ServiceCalendar, (d, route_id("cheonan"))).schedule_status == "unknown"
    assert all(t.source_row_key.split(":")[2] != "cheonan" for t in trips_on(db, d))


def test_unverified_origin_is_unknown(db):
    data = load_calendar_data(db)
    key = (template_id("weekday"), route_id("terminal"))
    data.trips[key] = [dataclasses.replace(data.trips[key][0], origin_verified=False), *data.trips[key][1:]]
    assert resolve(data, route_id("terminal"), date(2026, 9, 10)).schedule_status == "unknown"


def test_route_specific_exception_beats_global(db):
    from app.calendar.resolve import ExceptionInfo

    data = load_calendar_data(db)
    d = date(2026, 9, 24)
    data.exceptions.append(ExceptionInfo(d, route_id("cheonan_asan"), "alternate_schedule", template_id("sunday_holiday"), "노선 전용 대체"))
    assert resolve(data, route_id("cheonan_asan"), d).schedule_status == "available"
    assert resolve(data, route_id("cheonan"), d).schedule_status == "no_service"


def test_past_resolution_preserved(db):
    r, d = route_id("cheonan_asan"), date(2026, 9, 10)
    resolve_service_calendar(db, r, d, today=date(2026, 9, 1))
    db.execute(update(ServiceCalendar).where(ServiceCalendar.service_date == d).values(reason="그날 보여준 판정"))
    kept = resolve_service_calendar(db, r, d, today=date(2026, 9, 15))
    assert kept.reason == "그날 보여준 판정"
    fresh = resolve_service_calendar(db, r, d, today=date(2026, 9, 1))
    assert fresh.reason is None


def test_next_service_date(db):
    assert find_next_service_date(db, route_id("cheonan_asan"), date(2026, 9, 23)) == (date(2026, 9, 27), False)
    assert find_next_service_date(db, route_id("cheonan_asan"), date(2026, 12, 13)) == (date(2026, 12, 14), False)
    assert find_next_service_date(db, route_id("cheonan_asan"), date(2026, 12, 14)) == (None, False)
    assert find_next_service_date(db, route_id("onyang"), date(2026, 9, 4)) == (date(2026, 9, 7), False)


def test_next_service_date_flags_unknown_gap(db):
    from app.models.calendar import ScheduleRouteCoverage

    db.execute(
        update(ScheduleRouteCoverage)
        .where(ScheduleRouteCoverage.schedule_template_id == template_id("saturday"), ScheduleRouteCoverage.route_id == route_id("cheonan"))
        .values(coverage_status="unknown")
    )
    assert find_next_service_date(db, route_id("cheonan"), date(2026, 9, 11)) == (date(2026, 9, 13), True)


# ---------- API ----------


def test_routes_api(client):
    body = client.get("/api/v1/routes").json()
    assert {r["name"] for r in body} == {"천안아산역", "천안역", "천안터미널", "온양온천역"}


def test_service_calendar_api(client):
    res = client.get(
        "/api/v1/service-calendar",
        params={"route_id": str(route_id("onyang")), "from_date": "2026-09-04", "to_date": "2026-09-07"},
    )
    assert res.status_code == 200
    assert [d["schedule_status"] for d in res.json()["days"]] == ["available", "no_service", "no_service", "available"]


def test_service_calendar_api_unknown_route_is_404(client):
    res = client.get(
        "/api/v1/service-calendar",
        params={"route_id": "00000000-0000-0000-0000-000000000000", "from_date": "2026-09-04", "to_date": "2026-09-07"},
    )
    assert res.status_code == 404 and res.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_service_calendar_out_of_period_is_200(client):
    res = client.get(
        "/api/v1/service-calendar",
        params={"route_id": str(route_id("cheonan")), "from_date": "2026-12-15", "to_date": "2026-12-15"},
    )
    assert res.status_code == 200 and res.json()["days"][0]["schedule_status"] == "out_of_period"


def test_fr_sd_03_stops_differ_by_date(client):
    weekday = client.get(f"/api/v1/routes/{route_id('cheonan')}/stops", params={"service_date": "2026-09-10"}).json()
    patterns = {p["pattern_code"]: len(p["stops"]) for p in weekday["patterns"]}
    assert patterns == {"weekday_general": 7, "middle_only": 3}

    saturday = client.get(f"/api/v1/routes/{route_id('cheonan')}/stops", params={"service_date": "2026-09-12"}).json()
    assert {p["pattern_code"]: len(p["stops"]) for p in saturday["patterns"]} == {"holiday_general": 10}
    names = [s["stop_name"] for s in saturday["patterns"][0]["stops"]]
    assert names.count("천안아산역") == 2


def test_stops_api_no_service_returns_status(client):
    body = client.get(f"/api/v1/routes/{route_id('onyang')}/stops", params={"service_date": "2026-09-05"}).json()
    assert body["schedule_status"] == "no_service" and body["patterns"] == []


def test_stops_api_rejects_foreign_version(client):
    res = client.get(
        f"/api/v1/routes/{route_id('cheonan')}/stops",
        params={"service_date": "2026-09-10", "route_version_id": str(version_id("terminal", "general"))},
    )
    assert res.status_code == 422


def test_stops_have_null_coordinates_until_surveyed(client):
    body = client.get(f"/api/v1/routes/{route_id('cheonan_asan')}/stops", params={"service_date": "2026-09-10"}).json()
    assert all(s["latitude"] is None and s["longitude"] is None for p in body["patterns"] for s in p["stops"])
