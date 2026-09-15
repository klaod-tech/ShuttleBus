"""출발·도착 정거장별 탑승 후보 조회 (11 2~7장)."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendar.resolve import resolve, running_trips
from app.calendar.service import ensure_scheduled_trips, load_calendar_data, resolve_service_calendar
from app.candidates.classify import CandidateInput, candidate_sort_key, classify, unverified_sort_key
from app.models.calendar import ScheduledTrip
from app.models.reference import RoutePattern, RouteStop, RouteVersion, TripTemplate
from app.state.build import stop_out, tracked_vehicle_count, visit_out
from app.state.bundle import TripBundle, load_trip_bundles
from app.state.visits import evaluate_vehicle_visits
from app.timeutil import SEOUL

REFRESH_AFTER_SECONDS = 30  # 시험값 (11 5장)
NEXT_DATE_HORIZON_DAYS = 120


@dataclass
class CandidateResult:
    schedule_status: str
    schedule_reason: str | None
    candidates: list[dict]
    unverified_candidates: list[dict]
    recommended_candidate: dict | None
    no_candidate_reason: str | None
    next_known_service_date: date | None
    has_unknown_dates_before: bool


def trips_for_route_date(session: Session, route_id: uuid.UUID, service_date: date) -> list[uuid.UUID]:
    return list(
        session.scalars(
            select(ScheduledTrip.scheduled_trip_id)
            .join(RouteVersion, RouteVersion.route_version_id == ScheduledTrip.route_version_id)
            .join(RoutePattern, RoutePattern.route_pattern_id == RouteVersion.route_pattern_id)
            .where(RoutePattern.route_id == route_id, ScheduledTrip.service_date == service_date)
        )
    )


def _local(dt: datetime | None) -> datetime | None:
    return dt.astimezone(SEOUL) if dt else None


def journey_pairs(bundle: TripBundle, origin_stop_id: uuid.UUID, destination_stop_id: uuid.UUID):
    """같은 회차 안에서 순서가 맞는 (승차, 하차) 방문 쌍. 인접 방문도 허용한다 (11 2장)."""
    for i, boarding in enumerate(bundle.visits):
        if boarding.stop.stop_id != origin_stop_id:
            continue
        for j in range(i + 1, len(bundle.visits)):
            if bundle.visits[j].stop.stop_id == destination_stop_id:
                yield i, j


def find_boarding_candidates(
    session: Session,
    route_id: uuid.UUID,
    service_date: date,
    origin_stop_id: uuid.UUID,
    destination_stop_id: uuid.UUID,
    now: datetime,
) -> CandidateResult:
    calendar = resolve_service_calendar(session, route_id, service_date)
    if calendar.schedule_status != "available":
        next_date, has_unknown = next_service_date_for_pair(session, route_id, service_date, origin_stop_id, destination_stop_id)
        return CandidateResult(
            calendar.schedule_status, calendar.reason, [], [], None, "schedule_unavailable", next_date, has_unknown
        )

    # 조회 대상 날짜가 미생성이면 즉시 보충한다 (05 5장)
    ensure_scheduled_trips(session, route_id, service_date, service_date)
    bundles = load_trip_bundles(session, trips_for_route_date(session, route_id, service_date))

    candidates: list[dict] = []
    unverified: list[dict] = []
    matched_pair = False
    for bundle in bundles.values():
        pairs = list(journey_pairs(bundle, origin_stop_id, destination_stop_id))
        if not pairs:
            continue
        matched_pair = True
        origin = bundle.origin
        tracked = tracked_vehicle_count(bundle, now)
        for vehicle in bundle.vehicles:
            states = evaluate_vehicle_visits(bundle, vehicle, now)
            for i, j in pairs:
                boarding, alighting = bundle.visits[i], bundle.visits[j]
                b_state = states[i]
                result = classify(
                    CandidateInput(
                        trip_operation_status=bundle.trip.operation_status,
                        vehicle_operation_status=vehicle.operation_status,
                        boarding_policy=boarding.trip_stop.boarding_policy,
                        alighting_policy=alighting.trip_stop.alighting_policy,
                        boarding_visit_status=b_state.visit_status,
                        boarding_arrived_observed_at=b_state.arrived_observed_at,
                        boarding_estimated_event_at=b_state.estimated_event_at,
                        boarding_target_event_type=b_state.target_event_type,
                        boarding_unavailable_reason=b_state.unavailable_reason,
                        scheduled_departure_at=boarding.trip_stop.scheduled_departure_at,
                        scheduled_arrival_at=boarding.trip_stop.scheduled_arrival_at,
                        scheduled_unspecified_at=boarding.trip_stop.scheduled_unspecified_at,
                    ),
                    now,
                )
                if result.kind == "excluded":
                    continue
                item = {
                    "trip_id": bundle.trip.scheduled_trip_id,
                    "trip_vehicle_id": vehicle.trip_vehicle_id,
                    "vehicle_slot": vehicle.vehicle_slot,
                    "trip_no": bundle.template.trip_no,
                    "route_id": bundle.route_id,
                    "route_pattern_id": bundle.pattern.route_pattern_id,
                    "boarding_trip_stop_id": boarding.trip_stop.trip_stop_id,
                    "alighting_trip_stop_id": alighting.trip_stop.trip_stop_id,
                    "boarding_stop_sequence": boarding.trip_stop.stop_sequence,
                    "alighting_stop_sequence": alighting.trip_stop.stop_sequence,
                    "boarding_stop": stop_out(boarding),
                    "alighting_stop": stop_out(alighting),
                    "boarding_visit": visit_out(bundle, b_state),
                    "alighting_visit": visit_out(bundle, states[j]),
                    "route_segment_stop_names": [v.stop.name for v in bundle.visits[i : j + 1]],
                    "is_same_stop_loop": boarding.stop.stop_id == alighting.stop.stop_id,
                    "origin_stop_name": origin.stop.name,
                    "origin_scheduled_departure_at": _local(origin.trip_stop.scheduled_departure_at),
                    "priority_group": result.priority_group,
                    "sort_at": result.sort_at,
                    "sort_basis_event_type": result.sort_basis_event_type,
                    "unverified_reasons": list(result.reasons),
                    "scheduled_vehicle_count": bundle.trip.scheduled_vehicle_count,
                    "tracked_vehicle_count": tracked,
                }
                (candidates if result.kind == "candidate" else unverified).append(item)

    candidates.sort(key=candidate_sort_key)
    unverified.sort(key=unverified_sort_key)
    for item in candidates + unverified:
        item["sort_at"] = _local(item["sort_at"])

    recommended = None
    if candidates:
        first = candidates[0]
        recommended = {k: first[k] for k in ("trip_id", "trip_vehicle_id", "boarding_trip_stop_id", "alighting_trip_stop_id")}

    no_reason = None
    next_date, has_unknown = None, False
    if not candidates:
        if not unverified:
            # 확인 필요 항목이 있으면 '운행 종료'로 단정하지 않는다 (11 6장)
            no_reason = "no_remaining_service" if matched_pair else "no_matching_journey"
        next_date, has_unknown = next_service_date_for_pair(session, route_id, service_date, origin_stop_id, destination_stop_id)

    return CandidateResult(
        calendar.schedule_status, calendar.reason, candidates, unverified, recommended, no_reason, next_date, has_unknown
    )


def next_service_date_for_pair(
    session: Session, route_id: uuid.UUID, after: date, origin_stop_id: uuid.UUID, destination_stop_id: uuid.UUID
) -> tuple[date | None, bool]:
    """같은 노선·승하차 쌍을 제공하는 다음 확인된 날짜 (11 6장). 중간 unknown 날짜는 표시한다."""
    data = load_calendar_data(session)
    templates = {
        tt.trip_template_id: tt
        for tt in session.scalars(select(TripTemplate).where(TripTemplate.origin_route_stop_id.is_not(None)))
    }
    route_stops: dict[uuid.UUID, list[RouteStop]] = {}
    for rs in session.scalars(select(RouteStop).order_by(RouteStop.stop_sequence)):
        route_stops.setdefault(rs.route_version_id, []).append(rs)
    seq_of = {rs.route_stop_id: rs.stop_sequence for rows in route_stops.values() for rs in rows}

    def template_serves_pair(tt: TripTemplate) -> bool:
        origin_seq = seq_of[tt.origin_route_stop_id]
        stops = [rs.stop_id for rs in route_stops[tt.route_version_id] if rs.stop_sequence >= origin_seq]
        return any(s == origin_stop_id and destination_stop_id in stops[i + 1 :] for i, s in enumerate(stops))

    has_unknown = False
    period_end = max((t.effective_to for t in data.templates), default=after)
    d = after
    for _ in range(NEXT_DATE_HORIZON_DAYS):
        d += timedelta(days=1)
        if d > period_end:
            break
        res = resolve(data, route_id, d)
        if res.schedule_status == "unknown":
            has_unknown = True
        if res.schedule_status != "available":
            continue
        summaries = running_trips(data.trips.get((res.applied_schedule_template_id, route_id), []), res.effective_service_weekday)
        if any(template_serves_pair(templates[s.trip_template_id]) for s in summaries if s.trip_template_id in templates):
            return d, has_unknown
    return None, has_unknown
