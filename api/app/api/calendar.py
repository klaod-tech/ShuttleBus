"""05 7장 API — 노선, 운행 달력, 날짜별 정거장."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendar.resolve import running_trips
from app.calendar.service import daterange, load_calendar_data, resolve_service_calendar
from app.db import get_session
from app.errors import check_service_date, invalid, not_found
from app.models.reference import Route, RoutePathPoint, RoutePattern, RouteStop, RouteStopSegment, RouteVersion, Stop, TripTemplate

router = APIRouter(prefix="/api/v1")

MAX_CALENDAR_DAYS = 92


class RouteOut(BaseModel):
    route_id: uuid.UUID
    name: str
    short_name: str
    is_active: bool


class CalendarDayOut(BaseModel):
    service_date: date
    schedule_status: str
    schedule_reason: str | None
    applied_schedule_template_id: uuid.UUID | None
    actual_weekday: str
    effective_service_weekday: str | None
    effective_day_type: str | None


class ServiceCalendarOut(BaseModel):
    route_id: uuid.UUID
    days: list[CalendarDayOut]


class RouteStopOut(BaseModel):
    route_stop_id: uuid.UUID
    stop_id: uuid.UUID
    stop_name: str
    stop_sequence: int
    latitude: float | None
    longitude: float | None
    boarding_policy: str
    alighting_policy: str
    verification_status: str


class PatternStopsOut(BaseModel):
    route_pattern_id: uuid.UUID
    pattern_code: str
    direction: str
    route_version_id: uuid.UUID
    verification_status: str
    stops: list[RouteStopOut]


class RouteStopsOut(BaseModel):
    route_id: uuid.UUID
    service_date: date
    schedule_status: str
    schedule_reason: str | None
    patterns: list[PatternStopsOut]


def _route_or_404(session: Session, route_id: uuid.UUID) -> Route:
    route = session.get(Route, route_id)
    if route is None:
        raise not_found("노선")
    return route


@router.get("/routes", response_model=list[RouteOut])
def list_routes(session: Session = Depends(get_session)):
    return session.scalars(select(Route).order_by(Route.name)).all()


@router.get("/service-calendar", response_model=ServiceCalendarOut)
def get_service_calendar(
    route_id: uuid.UUID,
    from_date: date,
    to_date: date,
    session: Session = Depends(get_session),
):
    _route_or_404(session, route_id)
    check_service_date(from_date, to_date)
    if to_date < from_date:
        raise invalid("to_date는 from_date보다 앞설 수 없습니다.")
    if (to_date - from_date).days + 1 > MAX_CALENDAR_DAYS:
        raise invalid(f"한 번에 조회할 수 있는 기간은 {MAX_CALENDAR_DAYS}일입니다.")
    data = load_calendar_data(session)
    days = [resolve_service_calendar(session, route_id, d, data=data) for d in daterange(from_date, to_date)]
    session.commit()
    return ServiceCalendarOut(
        route_id=route_id,
        days=[
            CalendarDayOut(
                service_date=r.service_date,
                schedule_status=r.schedule_status,
                schedule_reason=r.reason,
                applied_schedule_template_id=r.applied_schedule_template_id,
                actual_weekday=r.actual_weekday,
                effective_service_weekday=r.effective_service_weekday,
                effective_day_type=r.effective_day_type,
            )
            for r in days
        ],
    )


def _active_version_ids(session: Session, data, res, route_id: uuid.UUID) -> set[uuid.UUID]:
    """그 날짜에 실제로 운행하는 회차들이 쓰는 경로 버전 (05 7장)."""
    running_ids = {
        t.trip_template_id
        for t in running_trips(data.trips.get((res.applied_schedule_template_id, route_id), []), res.effective_service_weekday)
    }
    return set(session.scalars(select(TripTemplate.route_version_id).where(TripTemplate.trip_template_id.in_(running_ids))))


@router.get("/routes/{route_id}/stops", response_model=RouteStopsOut)
def get_route_stops(
    route_id: uuid.UUID,
    # 천안역처럼 요일마다 패턴이 다르므로 날짜 없이 '오늘'을 가정하지 않는다 (05 7장)
    service_date: date = Query(...),
    route_pattern_id: uuid.UUID | None = None,
    route_version_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
):
    _route_or_404(session, route_id)
    check_service_date(service_date)
    if route_pattern_id is not None:
        pattern = session.get(RoutePattern, route_pattern_id)
        if pattern is None:
            raise not_found("노선 패턴")
        if pattern.route_id != route_id:
            raise invalid("route_pattern_id가 이 노선에 속하지 않습니다.")
    if route_version_id is not None:
        version = session.get(RouteVersion, route_version_id)
        if version is None:
            raise not_found("노선 버전")
        owner = session.get(RoutePattern, version.route_pattern_id)
        if owner.route_id != route_id or (route_pattern_id and owner.route_pattern_id != route_pattern_id):
            raise invalid("route_version_id가 이 노선·패턴에 속하지 않습니다.")

    data = load_calendar_data(session)
    res = resolve_service_calendar(session, route_id, service_date, data=data)
    session.commit()

    patterns: list[PatternStopsOut] = []
    if res.schedule_status == "available":
        version_ids = _active_version_ids(session, data, res, route_id)
        if route_version_id is not None:
            version_ids &= {route_version_id}
        rows = session.execute(
            select(RouteVersion, RoutePattern)
            .join(RoutePattern, RoutePattern.route_pattern_id == RouteVersion.route_pattern_id)
            .where(RouteVersion.route_version_id.in_(version_ids))
            .order_by(RoutePattern.pattern_code)
        ).all()
        for version, pattern in rows:
            if route_pattern_id is not None and pattern.route_pattern_id != route_pattern_id:
                continue
            stops = session.execute(
                select(RouteStop, Stop)
                .join(Stop, Stop.stop_id == RouteStop.stop_id)
                .where(RouteStop.route_version_id == version.route_version_id)
                .order_by(RouteStop.stop_sequence)
            ).all()
            patterns.append(
                PatternStopsOut(
                    route_pattern_id=pattern.route_pattern_id,
                    pattern_code=pattern.pattern_code,
                    direction=pattern.direction,
                    route_version_id=version.route_version_id,
                    verification_status=pattern.verification_status,
                    stops=[
                        RouteStopOut(
                            route_stop_id=rs.route_stop_id,
                            stop_id=stop.stop_id,
                            stop_name=stop.name,
                            stop_sequence=rs.stop_sequence,
                            latitude=stop.latitude,
                            longitude=stop.longitude,
                            boarding_policy=rs.boarding_policy,
                            alighting_policy=rs.alighting_policy,
                            verification_status=stop.verification_status,
                        )
                        for rs, stop in stops
                    ],
                )
            )

    return RouteStopsOut(
        route_id=route_id,
        service_date=service_date,
        schedule_status=res.schedule_status,
        schedule_reason=res.reason,
        patterns=patterns,
    )


# ---------- 경로 폴리라인 (04 1장, 10 5장, PLAN-route-data ③) ----------


class PathSegmentOut(BaseModel):
    from_route_stop_id: uuid.UUID
    to_route_stop_id: uuid.UUID
    path_from_seq: int
    path_to_seq: int
    distance_m: float | None
    path_source: str
    verification_status: str


class PatternPathOut(BaseModel):
    route_pattern_id: uuid.UUID
    pattern_code: str
    route_version_id: uuid.UUID
    # 행이 없으면 null. 화면은 manual_trace를 '추정 경로'로 표시한다 (10 5장)
    path_source: str | None
    point_count: int
    points: list[list[float]]  # [[lat, lng], …] path_seq 순
    segments: list[PathSegmentOut]
    # verified: 모든 구간 verified / partial: 일부 / unverified: 구간은 있으나 verified 없음 / none: 경로 행 없음
    verification: str


class RoutePathOut(BaseModel):
    route_id: uuid.UUID
    service_date: date
    schedule_status: str
    schedule_reason: str | None
    patterns: list[PatternPathOut]


@router.get(
    "/routes/{route_id}/path",
    response_model=RoutePathOut,
    summary="그 날짜 패턴별 경로 폴리라인",
    description="route_path_points가 비어 있으면 points=[]·verification=none 이다. 화면은 그때 아무 선도 긋지 않는다 (직선 연결도 금지).",
)
def get_route_path(
    route_id: uuid.UUID,
    service_date: date = Query(...),
    session: Session = Depends(get_session),
):
    _route_or_404(session, route_id)
    check_service_date(service_date)
    data = load_calendar_data(session)
    res = resolve_service_calendar(session, route_id, service_date, data=data)
    session.commit()

    patterns: list[PatternPathOut] = []
    if res.schedule_status == "available":
        version_ids = _active_version_ids(session, data, res, route_id)
        rows = session.execute(
            select(RouteVersion, RoutePattern)
            .join(RoutePattern, RoutePattern.route_pattern_id == RouteVersion.route_pattern_id)
            .where(RouteVersion.route_version_id.in_(version_ids))
            .order_by(RoutePattern.pattern_code)
        ).all()
        for version, pattern in rows:
            points = session.scalars(
                select(RoutePathPoint).where(RoutePathPoint.route_version_id == version.route_version_id).order_by(RoutePathPoint.path_seq)
            ).all()
            segments = session.scalars(
                select(RouteStopSegment).where(RouteStopSegment.route_version_id == version.route_version_id).order_by(RouteStopSegment.path_from_seq)
            ).all()
            if not points:
                verification = "none"
            elif segments and all(s.verification_status == "verified" for s in segments):
                verification = "verified"
            elif any(s.verification_status == "verified" for s in segments):
                verification = "partial"
            else:
                verification = "unverified"
            patterns.append(
                PatternPathOut(
                    route_pattern_id=pattern.route_pattern_id,
                    pattern_code=pattern.pattern_code,
                    route_version_id=version.route_version_id,
                    path_source=points[0].path_source if points else None,
                    point_count=len(points),
                    points=[[p.latitude, p.longitude] for p in points],
                    segments=[
                        PathSegmentOut(
                            from_route_stop_id=s.from_route_stop_id, to_route_stop_id=s.to_route_stop_id,
                            path_from_seq=s.path_from_seq, path_to_seq=s.path_to_seq, distance_m=s.distance_m,
                            path_source=s.path_source, verification_status=s.verification_status,
                        )
                        for s in segments
                    ],
                    verification=verification,
                )
            )
    return RoutePathOut(route_id=route_id, service_date=service_date, schedule_status=res.schedule_status, schedule_reason=res.reason, patterns=patterns)
