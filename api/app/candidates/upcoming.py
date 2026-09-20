"""정거장 단독 조회 — 한 정거장의 가까운 예정 방문 (11 11장).

출발·도착 쌍을 고르기 전에 정거장 하나를 눌러 "다음 버스"를 보는 화면용이다. 11 2~4장의 탑승 후보와
역할이 다르다 — 승차 가능을 보장하는 추천이 아니라 **방문 예정 정보**이며, 대표 시각은 "언제 오나"에
맞춰 같은 출처 안에서 도착 → 통과 → 출발 순으로 고른다 (후보 검색의 출발 우선과 반대).
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.calendar.service import ensure_scheduled_trips, resolve_service_calendar
from app.candidates.classify import CONTRARY_REASONS, PASSED_STATUSES
from app.candidates.service import trips_for_route_date
from app.config import settings
from app.state.build import stop_out, tracked_vehicle_count, visit_out
from app.state.bundle import TripBundle, load_trip_bundles
from app.state.visits import VisitState, evaluate_vehicle_visits, information_status_for
from app.timeutil import today_seoul, to_seoul as _local

UPCOMING_LIMIT = 2  # 정상 미래 항목 상한 (md_frontend/02). 확인 항목·참고 시간표는 이 상한과 별개


@dataclass
class UpcomingResult:
    schedule_status: str
    schedule_reason: str | None
    upcoming: list[dict]
    attention: list[dict]
    reference_timetable: list[dict]
    empty_reason: str | None
    refresh_after_seconds: int = 0


def _timetable_time(ts) -> tuple[datetime, str] | None:
    """의미가 확인된 공시 시각. 정거장 안내는 도착 → 출발 순 (11 11장). unspecified는 쓰지 않는다."""
    if ts.scheduled_arrival_at:
        return ts.scheduled_arrival_at, "arrived"
    if ts.scheduled_departure_at:
        return ts.scheduled_departure_at, "departed"
    return None


def _notes(ts) -> list[str]:
    notes = []
    if ts.boarding_policy == "not_allowed":
        notes.append("boarding_not_allowed")
    elif ts.boarding_policy == "unknown":
        notes.append("boarding_policy_unknown")
    return notes


def _item(
    bundle: TripBundle, vehicle, index: int, state: VisitState, info_status: str, tracked: int,
    display_at: datetime | None, display_event_type: str | None, display_basis: str | None,
    reason: str | None, secondary_departure_at: datetime | None = None,
) -> dict:
    visit = bundle.visits[index]
    nxt = bundle.visits[index + 1] if index + 1 < len(bundle.visits) else None
    return {
        "trip_id": bundle.trip.scheduled_trip_id,
        "trip_no": bundle.template.trip_no,
        "trip_vehicle_id": vehicle.trip_vehicle_id,
        "vehicle_slot": vehicle.vehicle_slot,
        "route_id": bundle.route_id,
        "route_pattern_id": bundle.pattern.route_pattern_id,
        "pattern_code": bundle.pattern.pattern_code,
        "trip_stop_id": visit.trip_stop.trip_stop_id,
        "stop_sequence": visit.trip_stop.stop_sequence,
        "is_origin": visit.trip_stop.trip_stop_id == bundle.trip.origin_trip_stop_id,
        "is_terminal": nxt is None,
        # 방향 문구는 새 자료 없이 방문 순서만으로 만든다 — "다음 정거장"과 회차의 종점
        "next_stop_name": nxt.stop.name if nxt else None,
        "terminal_stop_name": bundle.terminal.stop.name,
        "display_at": _local(display_at),
        "display_event_type": display_event_type,
        "display_basis": display_basis,
        "reason": reason,
        "secondary_departure_at": _local(secondary_departure_at),
        "notes": _notes(visit.trip_stop),
        "operation_status": vehicle.operation_status,
        "information_status": info_status,
        "scheduled_vehicle_count": bundle.trip.scheduled_vehicle_count,
        "tracked_vehicle_count": tracked,
        "stop": stop_out(visit),
        "visit": visit_out(bundle, state),
    }


def _sort_key(item: dict) -> tuple:
    at = item["display_at"]
    return (at is None, at.timestamp() if at else 0.0, item["trip_no"], item["vehicle_slot"], item["stop_sequence"], str(item["trip_vehicle_id"]))


def find_stop_upcoming(
    session: Session, route_id: uuid.UUID, service_date: date, stop_id: uuid.UUID, now: datetime,
    *, freshness_seconds: int | None = None, limit: int = UPCOMING_LIMIT,
) -> UpcomingResult:
    freshness_seconds = settings.arrived_freshness_seconds if freshness_seconds is None else freshness_seconds
    calendar = resolve_service_calendar(session, route_id, service_date)
    if calendar.schedule_status != "available":
        return UpcomingResult(calendar.schedule_status, calendar.reason, [], [], [], "schedule_unavailable", settings.refresh_after_seconds)
    if service_date < today_seoul(now):
        # 지난 날짜는 '다음 버스'가 아니라 시간표 열람으로 안내한다 (md_frontend/02)
        return UpcomingResult(calendar.schedule_status, calendar.reason, [], [], [], "past_date", settings.refresh_after_seconds)

    ensure_scheduled_trips(session, route_id, service_date, service_date)
    bundles = load_trip_bundles(session, trips_for_route_date(session, route_id, service_date))

    upcoming: list[dict] = []
    attention: list[dict] = []
    reference: list[dict] = []
    matched_visits = 0
    for bundle in bundles.values():
        indexes = [i for i, v in enumerate(bundle.visits) if v.stop.stop_id == stop_id]
        if not indexes:
            continue
        matched_visits += len(indexes)
        tracked = tracked_vehicle_count(bundle, now)
        for vehicle in bundle.vehicles:
            if bundle.trip.operation_status in ("completed", "cancelled") or vehicle.operation_status in ("completed", "cancelled"):
                continue
            info_status, _ = information_status_for(bundle, vehicle, now)
            states = evaluate_vehicle_visits(bundle, vehicle, now)
            for i in indexes:
                state = states[i]
                ts = bundle.visits[i].trip_stop
                if state.visit_status in PASSED_STATUSES:
                    continue  # 이미 출발·통과한 방문은 미래 목록이 아니다

                def make(**kw):
                    return _item(bundle, vehicle, i, state, info_status, tracked, **kw)

                # 1. 도착 확인 — 신선하면 '도착 확인', 아니면 오래된 도착. 예상 출발은 보조 표시 (11 11장)
                if state.visit_status == "arrived" and state.arrived_observed_at:
                    fresh = now - state.arrived_observed_at <= timedelta(seconds=freshness_seconds)
                    secondary = state.estimated_event_at if state.target_event_type == "departed" and state.estimated_event_at and state.estimated_event_at >= now else None
                    attention.append(make(
                        display_at=state.arrived_observed_at, display_event_type="arrived", display_basis="observed_event",
                        reason="arrived_confirmed" if fresh else "arrival_observation_stale", secondary_departure_at=secondary,
                    ))
                    continue

                # 2. 유효 미래 예측 (기점 공시 출발 포함 — prediction_basis가 출처를 말한다)
                if state.estimated_event_at and state.estimated_event_at >= now:
                    upcoming.append(make(
                        display_at=state.estimated_event_at, display_event_type=state.target_event_type,
                        display_basis=state.prediction_basis, reason=None,
                    ))
                    continue

                published = _timetable_time(ts)

                # 3. 실시간 근거 무효 — 미래 공시값으로 정상 항목을 되살리지 않는다 (11 3장 7)
                if state.unavailable_reason in CONTRARY_REASONS:
                    at, et = published if published else (None, None)
                    attention.append(make(display_at=at, display_event_type=et, display_basis="timetable" if published else None, reason=state.unavailable_reason))
                    continue

                # 4. 확인된 공시 시각 — 미래면 정상, 지났으면 '확인 중'
                if published:
                    at, et = published
                    if at >= now:
                        upcoming.append(make(display_at=at, display_event_type=et, display_basis="timetable", reason=None))
                    else:
                        attention.append(make(display_at=at, display_event_type=et, display_basis="timetable", reason="scheduled_time_passed"))
                    continue

                # 5. 사건 종류 미확정 공시값 · 시각 없는 경유 — 참고 시간표
                if ts.scheduled_unspecified_at:
                    reference.append(make(display_at=ts.scheduled_unspecified_at, display_event_type=None, display_basis="timetable", reason="scheduled_event_type_unspecified"))
                else:
                    reference.append(make(display_at=None, display_event_type=None, display_basis=None, reason="no_scheduled_time"))

    upcoming.sort(key=_sort_key)
    attention.sort(key=_sort_key)
    reference.sort(key=_sort_key)
    upcoming = upcoming[:limit]

    empty_reason = None
    if not upcoming:
        if matched_visits == 0:
            empty_reason = "stop_not_on_route"
        elif attention or reference:
            empty_reason = "unconfirmed_remaining"  # '모든 버스 종료'로 표시하지 않는다
        else:
            empty_reason = "no_remaining_service"
    return UpcomingResult(calendar.schedule_status, calendar.reason, upcoming, attention, reference, empty_reason, settings.refresh_after_seconds)
