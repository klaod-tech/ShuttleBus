"""방문 상태·예측 판정 (02 8장, 03 4·5장, 08 6장).

입력: 공시 시간표 + 유효 관측(P3). 구간 통계(④)는 아직 없다(P5).
  - 관측이 있어도 다음 방문으로 잇는 구간 통계가 없으므로 미래 방문은 missing_baseline
  - 기점 방문은 관측이 없을 때 공시 출발을 근거로 쓴다 (08 1장)
통계가 붙으면 이 모듈이 확장된다. 호출하는 쪽의 계약은 바뀌지 않는다.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.config import settings
from app.observation.rules import EventView, last_observation, progress_sequence
from app.state.bundle import TripBundle


@dataclass(frozen=True)
class VisitState:
    trip_stop_id: object
    visit_status: str
    estimated_event_at: datetime | None
    target_event_type: str | None
    prediction_basis: str | None
    basis_observation: EventView | None
    unavailable_reason: str | None
    arrived_observed_at: datetime | None = None


def _reference_time(bundle: TripBundle, index: int) -> datetime | None:
    """방문의 미도래 판단 기준. 자기 공시 시각이 없으면(경유) 뒤 방문 중 첫 공시 시각을 상한으로 쓴다."""
    for visit in bundle.visits[index:]:
        times = visit.scheduled_times
        if times:
            return max(times)
    return None


def visit_status_for(bundle: TripBundle, vehicle_id, index: int, now: datetime) -> str:
    seq = bundle.visits[index].trip_stop.stop_sequence
    events = bundle.events.get(vehicle_id, [])
    here = {e.event_type for e in events if e.trip_stop_id == bundle.visits[index].trip_stop.trip_stop_id}
    progress = progress_sequence(events)
    later_progress = progress is not None and progress > seq

    if "departed" in here:
        return "departed"
    if "passed" in here:
        return "passed"
    if "arrived" in here:
        # 출발 누락이어도 후속 방문이 확인되면 지나간 것 — 실제 출발 시각은 만들지 않는다 (02 8장)
        return "passed_inferred" if later_progress else "arrived"
    if "skipped" in here:
        return "passed_inferred"
    start = bundle.collection_start_seq.get(vehicle_id)
    if start is not None and seq < start:
        return "not_collected"
    if later_progress:
        return "unknown"
    reference = _reference_time(bundle, index)
    return "upcoming" if reference is None or reference >= now else "unknown"


def information_status_for(bundle: TripBundle, vehicle, now: datetime) -> tuple[str, EventView | None]:
    last = last_observation(bundle.events.get(vehicle.trip_vehicle_id, []))
    if last is None:
        return "timetable_only", None
    fresh = now - last.occurred_at <= timedelta(seconds=settings.observation_grace_seconds)
    return ("observed" if fresh else "stale"), last


def evaluate_visit(bundle: TripBundle, vehicle, index: int, now: datetime) -> VisitState:
    visit = bundle.visits[index]
    ts = visit.trip_stop
    vehicle_id = vehicle.trip_vehicle_id
    vehicle_status = vehicle.operation_status
    is_origin = ts.trip_stop_id == bundle.trip.origin_trip_stop_id
    is_terminal = index == len(bundle.visits) - 1
    status = visit_status_for(bundle, vehicle_id, index, now)
    events = bundle.events.get(vehicle_id, [])
    here = {e.event_type: e for e in events if e.trip_stop_id == ts.trip_stop_id and e.event_type != "skipped"}
    arrived_at = here["arrived"].occurred_at if "arrived" in here else None

    target = "departed" if is_origin else "arrived" if is_terminal else None

    def unavailable(reason: str, basis: str | None = None, observation: EventView | None = None) -> VisitState:
        return VisitState(ts.trip_stop_id, status, None, target, basis, observation, reason, arrived_at)

    # 08 6장 표 순서
    if bundle.trip.operation_status == "cancelled" or vehicle_status == "cancelled":
        return unavailable("trip_cancelled")
    if vehicle_status == "completed":
        return unavailable("trip_completed")
    if status in ("departed", "passed", "passed_inferred"):
        return unavailable("already_passed")
    if target is not None and target in here:
        return unavailable("event_confirmed", observation=here[target])

    last = last_observation(events)
    if last is not None:
        # 관측 근거는 있으나 이 방문까지 잇는 구간 통계가 없다
        return unavailable("missing_baseline")

    if is_origin:
        departure = ts.scheduled_departure_at
        if departure is None:
            return unavailable("no_observation")
        if departure >= now:
            return VisitState(ts.trip_stop_id, status, departure, "departed", "scheduled_departure", None, None, arrived_at)
        return unavailable("prediction_expired", "scheduled_departure")

    if bundle.trip.origin_trip_stop_id is None or bundle.origin.trip_stop.scheduled_departure_at is None:
        return unavailable("no_observation")
    # 기점 공시 출발이 근거로 있지만 사건을 잇는 구간 통계가 없다
    return unavailable("missing_baseline")


def evaluate_vehicle_visits(bundle: TripBundle, vehicle, now: datetime) -> list[VisitState]:
    return [evaluate_visit(bundle, vehicle, i, now) for i in range(len(bundle.visits))]
