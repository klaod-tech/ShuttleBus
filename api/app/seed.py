"""04 기준 데이터 시드. 멱등이다 — ID를 원문 키에서 결정적으로 만들고 merge로 적재한다 (FR-IN-02).

실행: python -m app.seed
"""

import uuid

from sqlalchemy.orm import Session

from app.models.calendar import ScheduleException, ScheduleRouteCoverage
from app.models.reference import (
    Route,
    RoutePattern,
    RouteStop,
    RouteVersion,
    ScheduleAnnotation,
    ScheduledStopTime,
    ScheduleTemplate,
    SourceStopLabel,
    Stop,
    TripTemplate,
)
from app.timetable import source_2026_2 as src
from app.timetable.parse import TERM_KEY, parse_all

NAMESPACE = uuid.UUID("5b2f8a61-3c1e-4d7a-9f0b-2a6c7e9d1f40")


def sid(*parts: object) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, ":".join(str(p) for p in parts))


def stop_id(name: str) -> uuid.UUID:
    return sid("stop", name)


def route_id(code: str) -> uuid.UUID:
    return sid("route", code)


def pattern_id(route: str, code: str) -> uuid.UUID:
    return sid("pattern", route, code)


def version_id(route: str, code: str, version_no: int = 1) -> uuid.UUID:
    return sid("route_version", route, code, version_no)


def route_stop_id(route: str, code: str, seq: int, version_no: int = 1) -> uuid.UUID:
    return sid("route_stop", route, code, version_no, seq)


def template_id(day_type: str) -> uuid.UUID:
    return sid("schedule_template", TERM_KEY, day_type)


def seed_reference_data(session: Session) -> None:
    for name in src.STOP_NAMES:
        status = "needs_interpretation" if name in src.NEEDS_INTERPRETATION_STOPS else "unverified"
        # 좌표는 실측 전 null (04 11장)
        session.merge(Stop(stop_id=stop_id(name), name=name, verification_status=status))

    for code, (name, short) in src.ROUTES.items():
        session.merge(Route(route_id=route_id(code), name=name, short_name=short, is_active=True))

    for p in src.PATTERNS:
        session.merge(
            RoutePattern(
                route_pattern_id=pattern_id(p.route, p.code),
                route_id=route_id(p.route),
                pattern_code=p.code,
                direction=p.direction,
                verification_status=p.verification_status,
            )
        )
        session.merge(
            RouteVersion(
                route_version_id=version_id(p.route, p.code),
                route_pattern_id=pattern_id(p.route, p.code),
                version_no=1,
                effective_from=p.effective[0],
                effective_to=p.effective[1],
                note=p.note,
            )
        )
        last = len(p.stops)
        for seq, name in enumerate(p.stops, start=1):
            is_origin, is_terminal = seq == 1, seq == last
            # 기점: 승차만, 종점: 하차만, 주요 외부 정거장: 양쪽 허용, 그 밖의 경유지: 양쪽 unknown (04 1장)
            if is_origin:
                boarding, alighting = "allowed", "not_allowed"
            elif is_terminal:
                boarding, alighting = "not_allowed", "allowed"
            elif name in src.MAJOR_EXTERNAL_STOPS:
                boarding, alighting = "allowed", "allowed"
            else:
                boarding, alighting = "unknown", "unknown"
            session.merge(
                RouteStop(
                    route_stop_id=route_stop_id(p.route, p.code, seq),
                    route_version_id=version_id(p.route, p.code),
                    stop_id=stop_id(name),
                    stop_sequence=seq,
                    is_origin=is_origin,
                    is_terminal=is_terminal,
                    boarding_policy=boarding,
                    alighting_policy=alighting,
                )
            )

    session.merge(
        SourceStopLabel(
            source_reference=src.SOURCE_HOLIDAY,
            raw_name=src.SUNMOON,
            provisional_stop_id=None,
            resolved_stop_id=stop_id(src.CAMPUS),
            verification_status="verified",
            note="휴일 천안터미널 열 표기. 아산캠퍼스와 같은 지점 (2026-09-15 사용자 확인)",
        )
    )

    for day_type, (name, (start, end), source) in src.TEMPLATES.items():
        session.merge(
            ScheduleTemplate(
                schedule_template_id=template_id(day_type),
                name=name,
                day_type=day_type,
                effective_from=start,
                effective_to=end,
                data_status="available",
                source_reference=source,
            )
        )

    for trip in parse_all():
        tt_id = sid("trip_template", trip.source_row_key)
        session.merge(
            TripTemplate(
                trip_template_id=tt_id,
                schedule_template_id=template_id(trip.day_type),
                route_version_id=version_id(trip.route, trip.pattern),
                trip_no=trip.trip_no,
                source_row_key=trip.source_row_key,
                origin_route_stop_id=(
                    route_stop_id(trip.route, trip.pattern, trip.origin_seq) if trip.origin_verified else None
                ),
                excluded_weekdays=trip.excluded_weekdays,
                vehicle_count_by_weekday=trip.vehicle_count_by_weekday,
                schedule_source="school_pdf",
                punctuality_assumption="user_asserted_on_time" if trip.origin_verified else "not_assumed",
                source_cells=trip.source_cells,
                note=trip.note,
            )
        )
        for st in trip.times:
            session.merge(
                ScheduledStopTime(
                    trip_template_id=tt_id,
                    route_stop_id=route_stop_id(trip.route, trip.pattern, st.pattern_seq),
                    event_type=st.event_type,
                    scheduled_time=st.time,
                    day_offset=0,
                    raw_value=st.raw_value,
                    schedule_source="school_pdf",
                )
            )

    for a in src.ANNOTATIONS:
        session.merge(
            ScheduleAnnotation(
                annotation_id=sid("schedule_annotation", a.route, a.trip_no, a.raw_text),
                source_page=src.SOURCE_WEEKDAY,
                route_id=route_id(a.route),
                trip_no=a.trip_no,
                covered_stop_ids=[stop_id(s) for s in a.covered_stops],
                raw_text=a.raw_text,
                min_seconds=a.min_seconds,
                max_seconds=a.max_seconds,
                reference_stop_id=stop_id(a.reference_stop) if a.reference_stop else None,
                verification_status="needs_interpretation",
            )
        )


def seed_calendar_data(session: Session) -> None:
    for day_type, (_, _, source) in src.TEMPLATES.items():
        for route in src.ROUTES:
            if (day_type, route) in src.NO_SERVICE_COVERAGE:
                status, expected, note = "confirmed_no_service", 0, "휴일 원본 전체 노선 범위 확인 — 온양온천역 노선 주말 미운행"
            elif (day_type, route) in src.EXPECTED_TRIP_COUNTS:
                status, expected, note = "confirmed_service", src.EXPECTED_TRIP_COUNTS[(day_type, route)], None
            else:
                continue  # 행 없음 = unknown
            session.merge(
                ScheduleRouteCoverage(
                    schedule_template_id=template_id(day_type),
                    route_id=route_id(route),
                    coverage_status=status,
                    source_reference=source,
                    expected_trip_count=expected,
                    note=note,
                )
            )

    for e in src.EXCEPTIONS:
        session.merge(
            ScheduleException(
                exception_id=sid("schedule_exception", e.day.isoformat(), "all"),
                exception_date=e.day,
                route_id=None,
                exception_type=e.exception_type,
                alternate_schedule_template_id=template_id(e.alternate_day_type) if e.alternate_day_type else None,
                source_reference=src.EXCEPTION_SOURCE,
                note=e.note,
            )
        )


def seed(session: Session) -> None:
    seed_reference_data(session)
    session.flush()
    seed_calendar_data(session)
    session.commit()


if __name__ == "__main__":
    from app.db import SessionLocal

    with SessionLocal() as s:
        seed(s)
    print("seed 완료")
