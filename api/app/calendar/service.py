"""운행 달력 판정 저장·회차 생성 (05 3~6장)."""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.calendar.resolve import (
    CalendarData,
    CoverageInfo,
    ExceptionInfo,
    Resolution,
    TemplateInfo,
    TripSummary,
    resolve,
    running_trips,
    vehicle_count,
)
from app.models.calendar import (
    ScheduledTrip,
    ScheduledTripStop,
    ScheduleException,
    ScheduleRouteCoverage,
    ServiceCalendar,
    TripVehicle,
)
from app.models.reference import (
    RoutePattern,
    RouteStop,
    RouteVersion,
    ScheduledStopTime,
    ScheduleTemplate,
    Stop,
    TripTemplate,
)
from app.timeutil import SEOUL, combine_seoul, today_seoul

TIME_COLUMN = {
    "arrival": "scheduled_arrival_at",
    "departure": "scheduled_departure_at",
    "unspecified": "scheduled_unspecified_at",
}


def load_calendar_data(session: Session) -> CalendarData:
    templates = [
        TemplateInfo(t.schedule_template_id, t.day_type, t.effective_from, t.effective_to, t.data_status)
        for t in session.scalars(select(ScheduleTemplate))
    ]
    exceptions = [
        ExceptionInfo(e.exception_date, e.route_id, e.exception_type, e.alternate_schedule_template_id, e.note)
        for e in session.scalars(select(ScheduleException))
    ]
    coverage = {
        (c.schedule_template_id, c.route_id): CoverageInfo(c.coverage_status, c.expected_trip_count)
        for c in session.scalars(select(ScheduleRouteCoverage))
    }
    trips: dict[tuple[uuid.UUID, uuid.UUID], list[TripSummary]] = defaultdict(list)
    rows = session.execute(
        select(TripTemplate, RoutePattern.route_id)
        .join(RouteVersion, RouteVersion.route_version_id == TripTemplate.route_version_id)
        .join(RoutePattern, RoutePattern.route_pattern_id == RouteVersion.route_pattern_id)
    )
    for tt, route_id in rows:
        trips[(tt.schedule_template_id, route_id)].append(
            TripSummary(
                trip_template_id=tt.trip_template_id,
                excluded_weekdays=tuple(tt.excluded_weekdays or ()),
                vehicle_count_by_weekday=dict(tt.vehicle_count_by_weekday or {}),
                origin_verified=tt.origin_route_stop_id is not None,
            )
        )
    return CalendarData(templates, exceptions, coverage, dict(trips))


def resolve_service_calendar(
    session: Session,
    route_id: uuid.UUID,
    service_date: date,
    *,
    data: CalendarData | None = None,
    today: date | None = None,
) -> Resolution:
    """판정하고 service_calendar에 기록한다.

    과거 날짜의 판정은 보존한다 — 그날 학생에게 보여준 결과가 이력이다 (05 3장).
    """
    today = today or today_seoul()
    existing = session.get(ServiceCalendar, (service_date, route_id))
    if existing is not None and service_date < today:
        return _from_row(existing)

    res = resolve(data or load_calendar_data(session), route_id, service_date)
    stmt = insert(ServiceCalendar).values(
        service_date=service_date,
        route_id=route_id,
        schedule_status=res.schedule_status,
        reason=res.reason,
        applied_schedule_template_id=res.applied_schedule_template_id,
        actual_weekday=res.actual_weekday,
        effective_service_weekday=res.effective_service_weekday,
        effective_day_type=res.effective_day_type,
        resolved_at=datetime.now(tz=SEOUL),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["service_date", "route_id"],
        set_={c: stmt.excluded[c] for c in (
            "schedule_status", "reason", "applied_schedule_template_id", "actual_weekday",
            "effective_service_weekday", "effective_day_type", "resolved_at",
        )},
    )
    session.execute(stmt)
    if existing is not None:
        session.expire(existing)
    return res


def _from_row(row: ServiceCalendar) -> Resolution:
    return Resolution(
        route_id=row.route_id,
        service_date=row.service_date,
        schedule_status=row.schedule_status,
        reason=row.reason,
        applied_schedule_template_id=row.applied_schedule_template_id,
        actual_weekday=row.actual_weekday,
        effective_service_weekday=row.effective_service_weekday,
        effective_day_type=row.effective_day_type,
    )


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


@dataclass
class GenerationReport:
    created_trips: int = 0
    data_errors: list[str] | None = None


def ensure_scheduled_trips(
    session: Session, route_id: uuid.UUID, from_date: date, to_date: date, *, today: date | None = None
) -> GenerationReport:
    """available인 날짜의 누락 회차만 만든다. 멱등 (FR-SC-07)."""
    report = GenerationReport(data_errors=[])
    data = load_calendar_data(session)
    stop_status = dict(session.execute(select(Stop.stop_id, Stop.verification_status)).all())
    for d in daterange(from_date, to_date):
        res = resolve_service_calendar(session, route_id, d, data=data, today=today)
        if res.schedule_status != "available":
            continue
        weekday = res.effective_service_weekday
        summaries = data.trips.get((res.applied_schedule_template_id, route_id), [])
        for summary in running_trips(summaries, weekday):
            count = vehicle_count(summary, weekday)
            if count is None:
                report.data_errors.append(f"{d} {summary.trip_template_id}: vehicle_count_by_weekday[{weekday}]")
                continue
            tt = session.get(TripTemplate, summary.trip_template_id)
            if _create_trip(session, tt, d, count, stop_status):
                report.created_trips += 1
    session.flush()
    return report


def _create_trip(
    session: Session, tt: TripTemplate, service_date: date, vehicles: int, stop_status: dict[uuid.UUID, str]
) -> bool:
    inserted = session.execute(
        insert(ScheduledTrip)
        .values(
            scheduled_trip_id=uuid.uuid4(),
            trip_template_id=tt.trip_template_id,
            service_date=service_date,
            route_version_id=tt.route_version_id,
            operation_status="scheduled",
            scheduled_vehicle_count=vehicles,
            state_version=1,
            control_version=1,
            source_row_key=tt.source_row_key,
        )
        .on_conflict_do_nothing()
        .returning(ScheduledTrip.scheduled_trip_id)
    ).scalar_one_or_none()
    if inserted is None:
        return False

    route_stops = session.scalars(
        select(RouteStop).where(RouteStop.route_version_id == tt.route_version_id).order_by(RouteStop.stop_sequence)
    ).all()
    origin = next(rs for rs in route_stops if rs.route_stop_id == tt.origin_route_stop_id)
    times = defaultdict(dict)
    for st in session.scalars(select(ScheduledStopTime).where(ScheduledStopTime.trip_template_id == tt.trip_template_id)):
        times[st.route_stop_id][st.event_type] = combine_seoul(service_date, st.scheduled_time, st.day_offset)

    origin_trip_stop_id = None
    for rs in route_stops:
        if rs.stop_sequence < origin.stop_sequence:
            continue  # 기점 이전 방문은 만들지 않는다 (05 4장)
        visit_times = times.get(rs.route_stop_id, {})
        is_origin = rs.route_stop_id == origin.route_stop_id
        only_unspecified = bool(visit_times) and set(visit_times) == {"unspecified"}
        trip_stop_id = uuid.uuid4()
        session.add(
            ScheduledTripStop(
                trip_stop_id=trip_stop_id,
                scheduled_trip_id=inserted,
                route_stop_id=rs.route_stop_id,
                stop_sequence=rs.stop_sequence,
                boarding_policy="allowed" if is_origin else rs.boarding_policy,
                alighting_policy="not_allowed" if is_origin else rs.alighting_policy,
                # 정거장 자체가 미확정이거나 시각의 사건 의미가 미확정이면 확인 필요
                verification_status=(
                    "needs_interpretation"
                    if stop_status.get(rs.stop_id) == "needs_interpretation" or only_unspecified
                    else "verified"
                ),
                **{TIME_COLUMN[k]: v for k, v in visit_times.items()},
            )
        )
        if is_origin:
            origin_trip_stop_id = trip_stop_id
    session.flush()
    session.execute(
        update(ScheduledTrip)
        .where(ScheduledTrip.scheduled_trip_id == inserted)
        .values(origin_trip_stop_id=origin_trip_stop_id)
    )
    for slot in range(1, vehicles + 1):
        session.add(TripVehicle(scheduled_trip_id=inserted, vehicle_slot=slot))
    return True


def find_next_service_date(
    session: Session, route_id: uuid.UUID, after: date, *, horizon_days: int = 400
) -> tuple[date | None, bool]:
    """(next_known_service_date, has_unknown_dates_before). 자료 없는 날짜를 조용히 건너뛰지 않는다 (05 6장)."""
    data = load_calendar_data(session)
    has_unknown = False
    for d in daterange(after + timedelta(days=1), after + timedelta(days=horizon_days)):
        res = resolve(data, route_id, d)
        if res.schedule_status == "available":
            return d, has_unknown
        if res.schedule_status == "unknown":
            has_unknown = True
        if res.schedule_status == "out_of_period" and data.templates and d > max(t.effective_to for t in data.templates):
            break
    return None, has_unknown
