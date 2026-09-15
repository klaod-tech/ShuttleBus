"""TripBundle → 03 응답 조립."""

from datetime import datetime

from app.calendar.resolve import Resolution
from app.observation.rules import EventView
from app.state.bundle import TripBundle, VisitRow
from app.state.schemas import BasisObservationOut, StopOut, TripStateOut, VehicleOut, VisitOut
from app.state.visits import VisitState, evaluate_vehicle_visits, information_status_for
from app.timeutil import SEOUL


def _local(dt: datetime | None) -> datetime | None:
    return dt.astimezone(SEOUL) if dt else None


def stop_out(visit: VisitRow) -> StopOut:
    ts, stop = visit.trip_stop, visit.stop
    return StopOut(
        trip_stop_id=ts.trip_stop_id,
        stop_id=stop.stop_id,
        stop_name=stop.name,
        stop_sequence=ts.stop_sequence,
        latitude=stop.latitude,
        longitude=stop.longitude,
        boarding_policy=ts.boarding_policy,
        alighting_policy=ts.alighting_policy,
        verification_status=ts.verification_status,
        scheduled_arrival_at=_local(ts.scheduled_arrival_at),
        scheduled_departure_at=_local(ts.scheduled_departure_at),
        scheduled_unspecified_at=_local(ts.scheduled_unspecified_at),
    )


def observation_out(bundle: TripBundle, event: EventView | None) -> BasisObservationOut | None:
    if event is None:
        return None
    visit = bundle.visits[bundle.visit_index(event.trip_stop_id)]
    return BasisObservationOut(
        event_id=event.event_id,
        trip_stop_id=event.trip_stop_id,
        stop_id=visit.stop.stop_id,
        stop_name=visit.stop.name,
        stop_sequence=event.stop_sequence,
        event_type=event.event_type,
        occurred_at=_local(event.occurred_at),
        time_confidence=event.time_confidence,
    )


def visit_out(bundle: TripBundle, state: VisitState) -> VisitOut:
    return VisitOut(
        trip_stop_id=state.trip_stop_id,
        visit_status=state.visit_status,
        estimated_event_at=_local(state.estimated_event_at),
        target_event_type=state.target_event_type,
        prediction_basis=state.prediction_basis,
        basis_observation=observation_out(bundle, state.basis_observation),
        unavailable_reason=state.unavailable_reason,
    )


def tracked_vehicle_count(bundle: TripBundle, now: datetime) -> int:
    """신선한 공개 관측을 가진 차량 수. 오래된 관측만 있는 차량은 세지 않는다 (03 2장)."""
    return sum(1 for v in bundle.vehicles if information_status_for(bundle, v, now)[0] == "observed")


def build_trip_state(bundle: TripBundle, calendar: Resolution, now: datetime) -> TripStateOut:
    trip = bundle.trip
    vehicles = []
    for v in bundle.vehicles:
        info_status, last = information_status_for(bundle, v, now)
        vehicles.append(
            VehicleOut(
                trip_vehicle_id=v.trip_vehicle_id,
                vehicle_slot=v.vehicle_slot,
                shuttle_id=v.shuttle_id,
                operation_status=v.operation_status,
                cancellation_reason=None,
                information_status=info_status,
                last_observation=observation_out(bundle, last),
                # Phase 1은 좌표 수집이 없다 (03 4장)
                position_status="not_enabled",
                last_position=None,
                visits=[visit_out(bundle, s) for s in evaluate_vehicle_visits(bundle, v, now)],
            )
        )
    return TripStateOut(
        trip_id=trip.scheduled_trip_id,
        route_id=bundle.route_id,
        route_version_id=trip.route_version_id,
        service_date=trip.service_date,
        trip_no=bundle.template.trip_no,
        state_version=trip.state_version,
        control_version=trip.control_version,
        server_time=now.astimezone(SEOUL),
        schedule_status=calendar.schedule_status,
        schedule_reason=calendar.reason,
        operation_status=trip.operation_status,
        cancellation_reason=None,
        scheduled_vehicle_count=trip.scheduled_vehicle_count,
        tracked_vehicle_count=tracked_vehicle_count(bundle, now),
        stops=[stop_out(v) for v in bundle.visits],
        vehicles=vehicles,
    )
