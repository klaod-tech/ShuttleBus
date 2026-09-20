"""정거장 단독 조회 — 가까운 예정 방문 (11 11장). 학생 조회, 인증 없음."""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.candidates.upcoming import find_stop_upcoming
from app.clock import get_now
from app.db import get_session
from app.errors import check_service_date, not_found
from app.models.reference import Route, Stop
from app.state.schemas import StopOut, VisitOut
from app.timeutil import SEOUL

router = APIRouter(prefix="/api/v1")


class UpcomingItemOut(BaseModel):
    trip_id: uuid.UUID
    trip_no: int
    trip_vehicle_id: uuid.UUID
    vehicle_slot: int
    route_id: uuid.UUID
    route_pattern_id: uuid.UUID
    pattern_code: str
    trip_stop_id: uuid.UUID
    stop_sequence: int
    is_origin: bool
    is_terminal: bool
    next_stop_name: str | None
    terminal_stop_name: str
    # 대표 시각과 그 뜻. display_basis: observed_event / interpolated_event / scheduled_departure / timetable / null
    display_at: datetime | None
    display_event_type: str | None
    display_basis: str | None
    # attention·reference_timetable 항목의 사유. upcoming은 null
    reason: str | None
    # 도착 확인 항목에 붙는 보조 예상 출발 (같은 방문을 미래 목록에 다시 넣지 않는다)
    secondary_departure_at: datetime | None
    notes: list[str]
    operation_status: str
    information_status: str
    scheduled_vehicle_count: int
    tracked_vehicle_count: int
    stop: StopOut
    visit: VisitOut


class StopUpcomingOut(BaseModel):
    stop_id: uuid.UUID
    stop_name: str
    route_id: uuid.UUID
    service_date: date
    schedule_status: str
    schedule_reason: str | None
    server_time: datetime
    refresh_after_seconds: int
    upcoming: list[UpcomingItemOut]
    attention: list[UpcomingItemOut]
    reference_timetable: list[UpcomingItemOut]
    # schedule_unavailable / past_date / stop_not_on_route / unconfirmed_remaining / no_remaining_service / null
    empty_reason: str | None


@router.get(
    "/stops/{stop_id}/upcoming",
    response_model=StopUpcomingOut,
    summary="정거장 하나의 가까운 예정 방문 (최대 2개)",
    description="출발·도착 쌍 없이 정거장 하나를 눌렀을 때. 승차 보장이 아니라 방문 예정 정보다. "
    "upcoming은 정상 미래 항목 최대 2개, attention은 도착 확인·확인 중 항목, reference_timetable은 사건 종류 미확정 공시값·시각 없는 경유.",
)
def get_stop_upcoming(
    stop_id: uuid.UUID,
    route_id: uuid.UUID,
    service_date: date,
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    stop = session.get(Stop, stop_id)
    if stop is None:
        raise not_found("정거장")
    if session.get(Route, route_id) is None:
        raise not_found("노선")
    check_service_date(service_date)
    result = find_stop_upcoming(session, route_id, service_date, stop_id, now)
    session.commit()
    return StopUpcomingOut(
        stop_id=stop.stop_id,
        stop_name=stop.name,
        route_id=route_id,
        service_date=service_date,
        schedule_status=result.schedule_status,
        schedule_reason=result.schedule_reason,
        server_time=now.astimezone(SEOUL),
        refresh_after_seconds=result.refresh_after_seconds,
        upcoming=result.upcoming,
        attention=result.attention,
        reference_timetable=result.reference_timetable,
        empty_reason=result.empty_reason,
    )
