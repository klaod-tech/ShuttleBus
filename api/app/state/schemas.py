"""03 상태 계약 응답 구조. REST와 실시간 전송이 같은 구조를 쓴다."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel


class BasisObservationOut(BaseModel):
    event_id: uuid.UUID
    trip_stop_id: uuid.UUID
    stop_id: uuid.UUID
    stop_name: str
    stop_sequence: int
    event_type: str
    occurred_at: datetime
    time_confidence: str


class StopOut(BaseModel):
    trip_stop_id: uuid.UUID
    stop_id: uuid.UUID
    stop_name: str
    stop_sequence: int
    latitude: float | None
    longitude: float | None
    boarding_policy: str
    alighting_policy: str
    verification_status: str
    scheduled_arrival_at: datetime | None
    scheduled_departure_at: datetime | None
    scheduled_unspecified_at: datetime | None


class VisitOut(BaseModel):
    trip_stop_id: uuid.UUID
    visit_status: str
    estimated_event_at: datetime | None
    target_event_type: str | None
    prediction_basis: str | None
    basis_observation: BasisObservationOut | None
    unavailable_reason: str | None
    # 이 방문·이 차량의 유효 실측 시각 (03 5장, 2026-09-18 추가). 없으면 null. 예측이 아니라 지난 기록 표시용
    observed_arrival_at: datetime | None = None
    observed_departure_at: datetime | None = None
    observed_passed_at: datetime | None = None


class LastPositionOut(BaseModel):
    latitude: float
    longitude: float
    measured_at: datetime


class VehicleOut(BaseModel):
    trip_vehicle_id: uuid.UUID
    vehicle_slot: int
    shuttle_id: uuid.UUID | None
    operation_status: str
    cancellation_reason: str | None
    information_status: str
    last_observation: BasisObservationOut | None
    position_status: str
    last_position: LastPositionOut | None
    visits: list[VisitOut]


class TripStateOut(BaseModel):
    trip_id: uuid.UUID
    route_id: uuid.UUID
    route_version_id: uuid.UUID
    service_date: date
    trip_no: int
    state_version: int
    control_version: int
    server_time: datetime
    schedule_status: str
    schedule_reason: str | None
    operation_status: str
    cancellation_reason: str | None
    scheduled_vehicle_count: int
    tracked_vehicle_count: int
    stops: list[StopOut]
    vehicles: list[VehicleOut]
