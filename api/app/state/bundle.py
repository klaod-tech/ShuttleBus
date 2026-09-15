"""회차 상태 계산에 필요한 행을 한 번에 읽는다."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.calendar import ScheduledTrip, ScheduledTripStop, TripVehicle
from app.models.observation import CollectionSession, LocationEvent
from app.models.reference import RoutePattern, RouteStop, RouteVersion, Stop, TripTemplate
from app.observation.rules import EventView


@dataclass
class VisitRow:
    trip_stop: ScheduledTripStop
    route_stop: RouteStop
    stop: Stop

    @property
    def scheduled_times(self) -> list[datetime]:
        ts = self.trip_stop
        return [t for t in (ts.scheduled_arrival_at, ts.scheduled_departure_at, ts.scheduled_unspecified_at) if t]


@dataclass
class TripBundle:
    trip: ScheduledTrip
    template: TripTemplate
    pattern: RoutePattern
    route_id: uuid.UUID
    visits: list[VisitRow] = field(default_factory=list)
    vehicles: list[TripVehicle] = field(default_factory=list)
    # 차량별 유효 관측(skipped 포함)과 수집 시작 방문 순번 (중간 탑승)
    events: dict[uuid.UUID, list[EventView]] = field(default_factory=dict)
    collection_start_seq: dict[uuid.UUID, int] = field(default_factory=dict)

    def visit_index(self, trip_stop_id) -> int:
        return next(i for i, v in enumerate(self.visits) if v.trip_stop.trip_stop_id == trip_stop_id)

    @property
    def origin(self) -> VisitRow:
        return next(v for v in self.visits if v.trip_stop.trip_stop_id == self.trip.origin_trip_stop_id)

    @property
    def terminal(self) -> VisitRow:
        return self.visits[-1]


def load_trip_bundles(session: Session, trip_ids: list[uuid.UUID]) -> dict[uuid.UUID, TripBundle]:
    if not trip_ids:
        return {}
    bundles: dict[uuid.UUID, TripBundle] = {}
    rows = session.execute(
        select(ScheduledTrip, TripTemplate, RoutePattern)
        .join(TripTemplate, TripTemplate.trip_template_id == ScheduledTrip.trip_template_id)
        .join(RouteVersion, RouteVersion.route_version_id == ScheduledTrip.route_version_id)
        .join(RoutePattern, RoutePattern.route_pattern_id == RouteVersion.route_pattern_id)
        .where(ScheduledTrip.scheduled_trip_id.in_(trip_ids))
    )
    for trip, template, pattern in rows:
        bundles[trip.scheduled_trip_id] = TripBundle(trip, template, pattern, pattern.route_id)

    visit_rows = session.execute(
        select(ScheduledTripStop, RouteStop, Stop)
        .join(RouteStop, RouteStop.route_stop_id == ScheduledTripStop.route_stop_id)
        .join(Stop, Stop.stop_id == RouteStop.stop_id)
        .where(ScheduledTripStop.scheduled_trip_id.in_(trip_ids))
        .order_by(ScheduledTripStop.scheduled_trip_id, ScheduledTripStop.stop_sequence)
    )
    for ts, rs, stop in visit_rows:
        bundles[ts.scheduled_trip_id].visits.append(VisitRow(ts, rs, stop))

    for vehicle in session.scalars(
        select(TripVehicle)
        .where(TripVehicle.scheduled_trip_id.in_(trip_ids))
        .order_by(TripVehicle.scheduled_trip_id, TripVehicle.vehicle_slot)
    ):
        bundles[vehicle.scheduled_trip_id].vehicles.append(vehicle)

    vehicle_trip = {v.trip_vehicle_id: b for b in bundles.values() for v in b.vehicles}
    seq_of = {v.trip_stop.trip_stop_id: v.trip_stop.stop_sequence for b in bundles.values() for v in b.visits}
    if vehicle_trip:
        for e in session.scalars(
            select(LocationEvent).where(
                LocationEvent.trip_vehicle_id.in_(vehicle_trip), LocationEvent.validation_status == "valid"
            )
        ):
            vehicle_trip[e.trip_vehicle_id].events.setdefault(e.trip_vehicle_id, []).append(
                EventView(e.event_id, e.trip_stop_id, seq_of[e.trip_stop_id], e.event_type, e.occurred_at, e.time_confidence, e.validation_status)
            )
        for s in session.scalars(
            select(CollectionSession).where(
                CollectionSession.trip_vehicle_id.in_(vehicle_trip), CollectionSession.collection_start_trip_stop_id.is_not(None)
            )
        ):
            bundle = vehicle_trip[s.trip_vehicle_id]
            seq = seq_of[s.collection_start_trip_stop_id]
            bundle.collection_start_seq[s.trip_vehicle_id] = min(seq, bundle.collection_start_seq.get(s.trip_vehicle_id, seq))
    return bundles
