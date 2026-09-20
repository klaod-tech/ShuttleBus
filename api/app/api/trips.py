"""회차 목록·탑승 후보 (11 7장), 회차 상태 (03 9장)."""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.calendar.service import ensure_scheduled_trips, resolve_service_calendar
from app.candidates.service import find_boarding_candidates, trips_for_route_date
from app.config import settings
from app.clock import get_now
from app.db import get_session
from app.errors import check_service_date, invalid, not_found
from app.models.calendar import ScheduledTrip
from app.models.realtime import TripStateSnapshot
from app.models.reference import Route, Stop
from app.seed import route_id as seed_route_id
from app.realtime.cache import get_cache
from app.realtime.state import compute_live_states, content, is_current, lock_and_commit
from app.state.bundle import load_trip_bundles
from app.state.schemas import StopOut, TripStateOut, VisitOut
from app.timetable.parse import student_union_applies
from app.timetable.source_2026_2 import CAMPUS, ROUTES
from app.timeutil import SEOUL, to_seoul as _local

router = APIRouter(prefix="/api/v1")

ROUTE_CODE_BY_ID = {seed_route_id(code): code for code in ROUTES}


class RecommendedOut(BaseModel):
    trip_id: uuid.UUID
    trip_vehicle_id: uuid.UUID
    boarding_trip_stop_id: uuid.UUID
    alighting_trip_stop_id: uuid.UUID


class CandidateOut(BaseModel):
    trip_id: uuid.UUID
    trip_vehicle_id: uuid.UUID
    vehicle_slot: int
    trip_no: int
    route_id: uuid.UUID
    route_pattern_id: uuid.UUID
    boarding_trip_stop_id: uuid.UUID
    alighting_trip_stop_id: uuid.UUID
    boarding_stop_sequence: int
    alighting_stop_sequence: int
    boarding_stop: StopOut
    alighting_stop: StopOut
    boarding_visit: VisitOut
    alighting_visit: VisitOut
    route_segment_stop_names: list[str]
    is_same_stop_loop: bool
    origin_stop_name: str
    origin_scheduled_departure_at: datetime | None
    priority_group: int | None
    sort_at: datetime | None
    sort_basis_event_type: str | None
    unverified_reasons: list[str]
    scheduled_vehicle_count: int
    tracked_vehicle_count: int


class CandidatesOut(BaseModel):
    schedule_status: str
    schedule_reason: str | None
    server_time: datetime
    candidates: list[CandidateOut]
    unverified_candidates: list[CandidateOut]
    recommended_candidate: RecommendedOut | None
    refresh_after_seconds: int
    no_candidate_reason: str | None
    next_known_service_date: date | None
    has_unknown_dates_before: bool


class TripSummaryOut(BaseModel):
    trip_id: uuid.UUID
    trip_no: int
    route_pattern_id: uuid.UUID
    pattern_code: str
    operation_status: str
    scheduled_vehicle_count: int
    origin_stop_name: str
    origin_scheduled_departure_at: datetime | None
    terminal_stop_name: str
    terminal_scheduled_arrival_at: datetime | None
    note: str | None
    # 학생회관 승차 해당 여부. null = 확인 필요(휴일·온양) (04 7장, 10 6장)
    student_union_boarding: bool | None


class TripListOut(BaseModel):
    route_id: uuid.UUID
    service_date: date
    schedule_status: str
    schedule_reason: str | None
    server_time: datetime
    trips: list[TripSummaryOut]


@router.get(
    "/scheduled-trips",
    response_model=CandidatesOut | TripListOut,
    summary="회차 목록 또는 출발·도착 탑승 후보",
    description="origin_stop_id와 destination_stop_id를 둘 다 주면 후보 응답, 둘 다 생략하면 날짜별 회차 목록. 하나만 주면 422.",
)
def get_scheduled_trips(
    route_id: uuid.UUID,
    service_date: date,
    origin_stop_id: uuid.UUID | None = None,
    destination_stop_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    if session.get(Route, route_id) is None:
        raise not_found("노선")
    check_service_date(service_date)
    if (origin_stop_id is None) != (destination_stop_id is None):
        raise invalid("origin_stop_id와 destination_stop_id는 함께 보내거나 함께 생략해야 합니다.")

    if origin_stop_id is not None:
        for stop_id in (origin_stop_id, destination_stop_id):
            if session.get(Stop, stop_id) is None:
                raise not_found("정거장")
        result = find_boarding_candidates(session, route_id, service_date, origin_stop_id, destination_stop_id, now)
        session.commit()
        return CandidatesOut(
            schedule_status=result.schedule_status,
            schedule_reason=result.schedule_reason,
            server_time=now.astimezone(SEOUL),
            candidates=result.candidates,
            unverified_candidates=result.unverified_candidates,
            recommended_candidate=result.recommended_candidate,
            refresh_after_seconds=settings.refresh_after_seconds,
            no_candidate_reason=result.no_candidate_reason,
            next_known_service_date=result.next_known_service_date,
            has_unknown_dates_before=result.has_unknown_dates_before,
        )

    calendar = resolve_service_calendar(session, route_id, service_date)
    trips: list[TripSummaryOut] = []
    if calendar.schedule_status == "available":
        ensure_scheduled_trips(session, route_id, service_date, service_date)
        bundles = load_trip_bundles(session, trips_for_route_date(session, route_id, service_date))
        route_code = ROUTE_CODE_BY_ID.get(route_id)
        for b in bundles.values():
            origin, terminal = b.origin, b.terminal
            departure = _local(origin.trip_stop.scheduled_departure_at)
            campus_departure = departure.time() if departure and origin.stop.name == CAMPUS else None
            trips.append(
                TripSummaryOut(
                    trip_id=b.trip.scheduled_trip_id,
                    trip_no=b.template.trip_no,
                    route_pattern_id=b.pattern.route_pattern_id,
                    pattern_code=b.pattern.pattern_code,
                    operation_status=b.trip.operation_status,
                    scheduled_vehicle_count=b.trip.scheduled_vehicle_count,
                    origin_stop_name=origin.stop.name,
                    origin_scheduled_departure_at=departure,
                    terminal_stop_name=terminal.stop.name,
                    terminal_scheduled_arrival_at=_local(terminal.trip_stop.scheduled_arrival_at),
                    note=b.template.note,
                    student_union_boarding=(
                        student_union_applies(calendar.effective_day_type, route_code, campus_departure)
                        if route_code else None
                    ),
                )
            )
        trips.sort(key=lambda t: (t.origin_scheduled_departure_at, t.trip_no))
    session.commit()
    return TripListOut(
        route_id=route_id,
        service_date=service_date,
        schedule_status=calendar.schedule_status,
        schedule_reason=calendar.reason,
        server_time=now.astimezone(SEOUL),
        trips=trips,
    )


@router.get("/scheduled-trips/{trip_id}/state", response_model=TripStateOut, summary="회차 상태 (03)")
def get_trip_state(
    trip_id: uuid.UUID,
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    """확정된 상태 버전만 돌려준다 (12 10장). 같은 버전 번호로 다른 내용을 돌려주지 않는다.

    캐시(같은 버전·같은 내용) → DB 스냅샷 → 내용이 달라졌으면(시간 경과) 잠금 뒤 새 버전 확정.
    """
    trip = session.get(ScheduledTrip, trip_id)
    if trip is None:
        raise not_found("회차")
    server_time = now.astimezone(SEOUL)
    live = compute_live_states(session, [trip_id], now)[trip_id]
    cache = get_cache()
    cached = cache.get(trip_id)
    if cached is not None and cached[0] == trip.state_version and content(cached[1]) == content(live.payload):
        session.commit()
        return {**cached[1], "server_time": server_time}
    snapshot = session.get(TripStateSnapshot, trip_id)
    if is_current(snapshot, live, trip):
        # 캐시 누락·뒤처짐은 DB 확정 스냅샷을 복사해 복구한다. 새 버전을 만들지 않는다 (FR-RT-07·09)
        cache.put(trip_id, snapshot.state_version, snapshot.payload)
        session.commit()
        return {**snapshot.payload, "server_time": server_time}
    result = lock_and_commit(session, trip_id, now)
    session.commit()
    return {**result.payload, "server_time": server_time}
