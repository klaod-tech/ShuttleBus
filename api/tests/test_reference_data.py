"""04 기준 데이터 검증 기준 (FR-RD) — 원문 대조."""

from collections import Counter
from datetime import date, time

from sqlalchemy import func, select

from app.models.reference import (
    Route,
    RoutePathPoint,
    RoutePattern,
    RouteStop,
    RouteStopSegment,
    RouteVersion,
    ScheduledStopTime,
    ScheduleTemplate,
    Stop,
    TripTemplate,
)
from app.seed import route_id, route_stop_id, seed, sid, stop_id, version_id
from app.timetable import source_2026_2 as src
from app.timetable.parse import (
    campus_departure_of,
    classify_cells,
    note_says_student_union,
    parse_all,
    parse_row,
    pattern_def,
    student_union_applies,
)

TRIPS = parse_all()


def trip(day_type, route, no):
    return next(t for t in TRIPS if (t.day_type, t.route, t.trip_no) == (day_type, route, no))


def counts(day_type, weekday=None):
    return Counter(
        t.route for t in TRIPS if t.day_type == day_type and (weekday is None or weekday not in t.excluded_weekdays)
    )


def test_fr_rd_01_weekday_rows():
    c = counts("weekday")
    assert (c["cheonan_asan"], c["cheonan"], c["terminal"], c["onyang"]) == (42, 33, 38, 7)
    assert sum(c.values()) == 120


def test_fr_rd_02_friday_rows_and_lists():
    c = counts("weekday", "fri")
    assert (c["cheonan_asan"], c["cheonan"], c["terminal"], c["onyang"]) == (21, 17, 18, 5)
    expected = {
        "cheonan_asan": {2, 3, 5, 8, 10, 13, 14, 16, 17, 19, 20, 23, 25, 27, 29, 30, 32, 34, 36, 37, 39},
        "cheonan": {2, 4, 7, 9, 11, 13, 15, 17, 19, 21, 23, 24, 26, 28, 30, 33},
        "terminal": {2, 4, 6, 8, 12, 14, 16, 18, 20, 21, 23, 24, 26, 27, 29, 30, 32, 33, 35, 38},
        "onyang": {2, 6},
    }
    for route, nos in expected.items():
        actual = {t.trip_no for t in TRIPS if t.day_type == "weekday" and t.route == route and "fri" in t.excluded_weekdays}
        assert actual == nos, route


def test_fr_rd_03_holiday_rows():
    sat, sun = counts("saturday"), counts("sunday_holiday")
    assert (sat["cheonan_asan"], sat["cheonan"], sat["terminal"], sat["onyang"]) == (4, 4, 4, 0)
    assert (sun["cheonan_asan"], sun["cheonan"], sun["terminal"], sun["onyang"]) == (6, 5, 5, 0)


def test_fr_rd_04_vehicle_slots_by_weekday():
    def slots(weekday):
        return sum(
            t.vehicle_count_by_weekday[weekday]
            for t in TRIPS
            if t.day_type == "weekday" and weekday not in t.excluded_weekdays
        )

    assert [slots(d) for d in ("mon", "tue", "wed", "thu", "fri")] == [122, 122, 121, 121, 61]


def _route_stop_count(db, route, code):
    return db.scalar(select(func.count()).select_from(RouteStop).where(RouteStop.route_version_id == version_id(route, code)))


def test_fr_rd_05_cheonan_weekday_holiday_patterns_differ(db):
    assert _route_stop_count(db, "cheonan", "weekday_general") == 7
    assert _route_stop_count(db, "cheonan", "holiday_general") == 10


def test_fr_rd_06_holiday_cheonan_visits_cheonan_asan_twice(db):
    rows = db.scalars(
        select(RouteStop).where(
            RouteStop.route_version_id == version_id("cheonan", "holiday_general"),
            RouteStop.stop_id == stop_id("천안아산역"),
        )
    ).all()
    assert [r.stop_sequence for r in rows] == [3, 9]
    assert len({r.route_stop_id for r in rows}) == 2


def test_fr_rd_07_x_cells_create_no_times(db):
    time_cells = sum(sum(1 for c in t.source_cells["columns"] if c["interpretation"] == "time") for t in TRIPS)
    remark_origins = sum(1 for t in TRIPS if t.source_cells["remark"])
    assert db.scalar(select(func.count()).select_from(ScheduledStopTime)) == time_cells + remark_origins == 424

    # 천안아산역 순2의 캠퍼스 출발 칸(X)에는 시각 행이 없다
    t2 = trip("weekday", "cheonan_asan", 2)
    campus_dep = route_stop_id("cheonan_asan", "general", 1)
    assert db.scalar(
        select(func.count()).select_from(ScheduledStopTime).where(
            ScheduledStopTime.trip_template_id == sid("trip_template", t2.source_row_key),
            ScheduledStopTime.route_stop_id == campus_dep,
        )
    ) == 0


def test_fr_rd_08_middle_only_origin_is_remark(db):
    for route, no, stop, hhmm in (("cheonan", 5, "하이렉스파건너편", time(8, 50)), ("terminal", 9, "두정동 맥도날드", time(8, 55))):
        t = trip("weekday", route, no)
        tt = db.get(TripTemplate, sid("trip_template", t.source_row_key))
        origin = db.get(RouteStop, tt.origin_route_stop_id)
        assert db.get(Stop, origin.stop_id).name == stop
        assert tt.route_version_id == version_id(route, "middle_only")
        st = db.get(ScheduledStopTime, (tt.trip_template_id, origin.route_stop_id, "departure"))
        assert st.scheduled_time == hhmm


def test_fr_rd_09_student_union_window_inclusive():
    assert student_union_applies("weekday", "cheonan_asan", campus_departure_of(trip("weekday", "cheonan_asan", 26))) is True
    assert student_union_applies("weekday", "cheonan_asan", campus_departure_of(trip("weekday", "cheonan_asan", 27))) is False
    assert student_union_applies("weekday", "cheonan_asan", time(13, 30)) is True
    assert student_union_applies("weekday", "cheonan_asan", time(13, 29)) is False
    assert student_union_applies("weekday", "cheonan", time(19, 30)) is True
    assert student_union_applies("saturday", "cheonan_asan", time(14, 0)) is None
    assert student_union_applies("weekday", "onyang", time(15, 30)) is None
    # 계산 결과가 원문 비고 '학생회관'과 모두 일치한다
    for t in TRIPS:
        if t.day_type == "weekday" and t.route != "onyang":
            assert student_union_applies(t.day_type, t.route, campus_departure_of(t)) == note_says_student_union(t), t.source_row_key


def test_fr_rd_10_onyang_2_jueun_is_before_origin():
    t = trip("weekday", "onyang", 2)
    kinds = {c["label"]: c["interpretation"] for c in t.source_cells["columns"]}
    assert kinds["주은아파트"] == "before_origin"
    assert kinds["캠퍼스 출발"] == "before_origin"
    assert pattern_def("onyang", "general").stops[t.origin_seq - 1] == "온양온천역"


def test_fr_rd_11_template_periods(db):
    periods = {t.day_type: (t.effective_from, t.effective_to) for t in db.scalars(select(ScheduleTemplate))}
    assert periods == {
        "weekday": (date(2026, 9, 1), date(2026, 12, 14)),
        "saturday": (date(2026, 9, 5), date(2026, 12, 13)),
        "sunday_holiday": (date(2026, 9, 5), date(2026, 12, 13)),
    }


def test_fr_rd_12_published_times_kept(db):
    tt_id = sid("trip_template", trip("weekday", "cheonan", 1).source_row_key)
    times = {
        (st.route_stop_id, st.event_type): st.scheduled_time
        for st in db.scalars(select(ScheduledStopTime).where(ScheduledStopTime.trip_template_id == tt_id))
    }
    assert times[(route_stop_id("cheonan", "weekday_general", 1), "departure")] == time(7, 40)
    assert times[(route_stop_id("cheonan", "weekday_general", 4), "unspecified")] == time(8, 15)


def test_fr_rd_13_route_paths_not_yet_loaded(db):
    assert db.scalar(select(func.count()).select_from(RoutePathPoint)) == 0
    assert db.scalar(select(func.count()).select_from(RouteStopSegment)) == 0


def test_fr_rd_23_x_between_times_is_not_visited():
    assert classify_cells(("8:00", "X", "8:30")) == ["time", "not_visited", "time"]
    table = next(t for t in src.TABLES if t.day_type == "weekday" and t.route == "cheonan_asan")
    fake = src.SourceRow(trip_no=99, cells=("8:00", "X", "8:40"))
    parsed = parse_row(table, fake)
    assert parsed.issues and parsed.origin_seq is None and not parsed.origin_verified


def test_no_parse_issues_in_source():
    assert [t.source_row_key for t in TRIPS if t.issues] == []


def test_external_column_times_are_unspecified():
    """외부 정거장 열 시각은 기점이 아니면 도착·출발로 단정하지 않는다 (04 11장)."""
    t = trip("weekday", "cheonan_asan", 1)
    assert [(s.pattern_seq, s.event_type) for s in t.times] == [(1, "departure"), (4, "unspecified"), (5, "arrival")]
    t2 = trip("weekday", "cheonan_asan", 2)
    assert [(s.pattern_seq, s.event_type) for s in t2.times] == [(4, "departure"), (5, "arrival")]


def test_sunmoon_is_provisional_not_merged(db):
    stop = db.get(Stop, stop_id(src.SUNMOON))
    assert stop.verification_status == "needs_interpretation"
    pattern = db.get(RoutePattern, sid("pattern", "terminal", "holiday_provisional"))
    assert pattern.verification_status == "needs_interpretation"
    assert stop.stop_id != stop_id(src.CAMPUS)


def test_fr_in_02_seed_idempotent(db):
    tables = (Stop, Route, RoutePattern, RouteVersion, RouteStop, ScheduleTemplate, TripTemplate, ScheduledStopTime)
    before = [db.scalar(select(func.count()).select_from(m)) for m in tables]
    seed(db)
    after = [db.scalar(select(func.count()).select_from(m)) for m in tables]
    assert before == after


def test_route_ids_are_stable():
    assert route_id("cheonan") == route_id("cheonan")
    assert route_id("cheonan") != route_id("terminal")
