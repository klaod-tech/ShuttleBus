"""차량 완료·회차 상태 집계 (13 3·14장). 관측 입력 경로와 관리 경로가 함께 쓴다."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.calendar import ScheduledTrip, TripVehicle
from app.models.observation import LocationEvent
from app.models.operations import OperationDecision

FINAL = ("completed", "cancelled")
COMPLETION_DECISIONS = ("complete", "keep_completed")


def recompute_trip_status(session: Session, trip: ScheduledTrip) -> None:
    """회차 명시 취소면 cancelled. 아니면 모든 슬롯이 완료·취소이고 한 슬롯 이상 완료일 때 completed.

    모든 슬롯이 취소면 cancelled (FR-OP-14). 나머지는 예정·운행 상태로 둔다. 빈 슬롯 집합은 완료가 아니다.
    """
    if _trip_cancelled_explicitly(session, trip):
        trip.operation_status = "cancelled"
        return
    statuses = [v.operation_status for v in session.scalars(select(TripVehicle).where(TripVehicle.scheduled_trip_id == trip.scheduled_trip_id))]
    if statuses and all(s in FINAL for s in statuses):
        trip.operation_status = "completed" if "completed" in statuses else "cancelled"
    elif trip.operation_status in FINAL:
        trip.operation_status = "scheduled_running" if "scheduled_running" in statuses else "scheduled"


def _trip_cancelled_explicitly(session: Session, trip: ScheduledTrip) -> bool:
    return (
        session.scalar(
            select(OperationDecision.decision_id).where(
                OperationDecision.scheduled_trip_id == trip.scheduled_trip_id,
                OperationDecision.decision_type == "cancel_trip",
            ).limit(1)
        )
        is not None
    )


def auto_complete_on_terminal(
    session: Session, trip: ScheduledTrip, vehicle: TripVehicle, event: LocationEvent, stops: dict, now: datetime
) -> OperationDecision | None:
    """종점 방문의 유효 실측은 시간 경과가 아니라 완료 근거다 (13 1·3장, FR-OP-18·19·20).

    inferred·skipped는 근거가 아니다. 관측 입력이 control_version을 올리지 않으므로(FR-OP-09) 자동 결정은
    당시 control_version을 기록만 한다. 완료·취소 슬롯과 취소 회차는 건드리지 않는다.
    """
    terminal_id = max(stops.items(), key=lambda kv: kv[1][0].stop_sequence)[0]
    if (
        event.trip_stop_id != terminal_id
        or event.validation_status != "valid"
        or event.event_type not in ("arrived", "passed")
        or event.time_confidence not in ("observed", "interpolated")
        or vehicle.operation_status in FINAL
        or trip.operation_status == "cancelled"
    ):
        return None
    decision = OperationDecision(
        scheduled_trip_id=trip.scheduled_trip_id,
        trip_vehicle_id=vehicle.trip_vehicle_id,
        decision_type="complete",
        evidence_type="terminal_observation",
        evidence_event_id=event.event_id,
        note="보간 관측 근거" if event.time_confidence == "interpolated" else None,
        observed_completed_at=event.occurred_at,
        decided_by=None,
        decided_at=now,
        control_version=trip.control_version,
    )
    session.add(decision)
    vehicle.operation_status = "completed"
    session.flush()
    recompute_trip_status(session, trip)
    return decision


def active_completion(session: Session, trip_vehicle_id: uuid.UUID) -> OperationDecision | None:
    """대체되지 않은 가장 최근 완료 결정 (complete / keep_completed)."""
    superseded = select(OperationDecision.supersedes_decision_id).where(OperationDecision.supersedes_decision_id.is_not(None))
    return session.scalar(
        select(OperationDecision)
        .where(
            OperationDecision.trip_vehicle_id == trip_vehicle_id,
            OperationDecision.decision_type.in_(COMPLETION_DECISIONS),
            OperationDecision.decision_id.not_in(superseded),
        )
        .order_by(OperationDecision.decided_at.desc())
        .limit(1)
    )


def completion_review_required(session: Session, vehicle: TripVehicle) -> bool:
    """완료 근거로 쓴 관측이 이후 취소·기각되면 재검토 대상 (13 3·14장, FR-OP-12·16). 자동 해제하지 않는다."""
    if vehicle.operation_status != "completed":
        return False
    decision = active_completion(session, vehicle.trip_vehicle_id)
    if decision is None or decision.evidence_event_id is None:
        return False
    status = session.scalar(select(LocationEvent.validation_status).where(LocationEvent.event_id == decision.evidence_event_id))
    return status != "valid"


def trip_cancellation_reason(session: Session, trip_id: uuid.UUID) -> str | None:
    return session.scalar(
        select(OperationDecision.note)
        .where(OperationDecision.scheduled_trip_id == trip_id, OperationDecision.decision_type == "cancel_trip")
        .order_by(OperationDecision.decided_at.desc())
        .limit(1)
    )
