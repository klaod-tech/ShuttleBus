"""관리자 운영 기능 (13) — 차량 완료, 회차 취소, 관측 검토·복구, 완료 재검토, 공지, 검토 대상 판정.

모든 상태 변경은 회차 잠금 아래 한 트랜잭션에서 확정한다. 처리 순서는 01 4장:
인증 → 멱등 키(API 층) → 대상 조회·잠금 → 기대 버전 → 유효성 → 저장.

아직 없는 후속 단계와의 연결 지점:
- 통계 무효화 등록(travel_time_invalidations, 09 10장)과 재집계 등록은 P5에서 이 경로에 붙는다.
- outbox·스냅샷 전송(12)은 P4에서 붙는다. 지금은 state_version만 확정한다.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Principal
from app.config import settings
from app.errors import AppError, invalid, not_found
from app.models.calendar import ScheduledTrip, ScheduledTripStop, TripVehicle
from app.models.observation import CollectionSession, LocationEvent, ObservationReview
from app.models.operations import Notice, OperationDecision
from app.models.reference import Route, RoutePattern, RouteVersion
from app.observation.ingest import (
    _check_input_version,
    gap_visits,
    lock_trip,
    make_public,
    refresh_vehicle_information,
    trip_stops_by_id,
)
from app.observation.rules import EventView, progress_sequence
from app.operations.completion import FINAL, active_completion, recompute_trip_status

# ---------- 공통 ----------


def _check_control_version(trip: ScheduledTrip, expected: int) -> None:
    if trip.control_version != expected:
        raise AppError(
            409,
            "CONTROL_VERSION_CONFLICT",
            "다른 관리 변경이 먼저 반영되었습니다. 최신 상태를 확인한 뒤 다시 시도해 주세요.",
            details={"current_control_version": trip.control_version},
        )


def _state_conflict(message: str) -> AppError:
    return AppError(409, "OPERATION_STATE_CONFLICT", message)


def _bump_control(trip: ScheduledTrip) -> None:
    """관리 변경은 학생에게 보이는 상태를 바꾸므로 두 버전을 함께 올린다 (13 5장, FR-OP-08)."""
    trip.control_version += 1
    trip.state_version += 1


def _vehicle_and_trip(session: Session, trip_vehicle_id: uuid.UUID) -> tuple[TripVehicle, ScheduledTrip]:
    vehicle = session.get(TripVehicle, trip_vehicle_id)
    if vehicle is None:
        raise not_found("차량 슬롯")
    trip = lock_trip(session, vehicle.scheduled_trip_id)
    session.refresh(trip)
    session.refresh(vehicle)
    return vehicle, trip


def _terminal_id(stops: dict) -> uuid.UUID:
    return max(stops.items(), key=lambda kv: kv[1][0].stop_sequence)[0]


def _terminal_evidence(session: Session, trip: ScheduledTrip, vehicle: TripVehicle, event_id: uuid.UUID | None) -> LocationEvent:
    """관리자가 terminal_observation을 근거로 고르면 실제 종점 유효 실측을 가리켜야 한다."""
    if event_id is None:
        raise invalid("종점 관측 근거에는 evidence_event_id가 필요합니다.")
    event = session.get(LocationEvent, event_id)
    terminal_id = _terminal_id(trip_stops_by_id(session, trip.scheduled_trip_id))
    if (
        event is None
        or event.trip_vehicle_id != vehicle.trip_vehicle_id
        or event.trip_stop_id != terminal_id
        or event.validation_status != "valid"
        or event.event_type not in ("arrived", "passed")
        or event.time_confidence not in ("observed", "interpolated")
    ):
        raise invalid("근거 관측이 이 차량의 종점 유효 실측(arrived·passed)이 아닙니다.")
    return event


def _completed_at(evidence: LocationEvent | None, observed_completed_at: datetime | None, now: datetime) -> datetime | None:
    # 실제 완료 시각을 지어내지 않는다 (13 3장). 종점 관측이면 그 발생 시각이다
    if evidence is not None:
        return evidence.occurred_at
    if observed_completed_at is not None and observed_completed_at > now:
        raise invalid("실제 완료 시각은 현재 시각 이후일 수 없습니다.")
    return observed_completed_at


# ---------- 차량 완료 (13 3장) ----------


@dataclass
class DecisionResult:
    decision: OperationDecision
    trip: ScheduledTrip
    vehicles: list[TripVehicle] = field(default_factory=list)


def complete_trip_vehicle(
    session: Session,
    principal: Principal,
    trip_vehicle_id: uuid.UUID,
    evidence_type: str,
    note: str | None,
    observed_completed_at: datetime | None,
    evidence_event_id: uuid.UUID | None,
    expected_control_version: int,
    now: datetime,
) -> DecisionResult:
    vehicle, trip = _vehicle_and_trip(session, trip_vehicle_id)
    _check_control_version(trip, expected_control_version)
    if trip.operation_status == "cancelled" or vehicle.operation_status in FINAL:
        raise _state_conflict("이미 완료되었거나 취소된 운행입니다. 완료를 바꾸려면 완료 재검토를 사용해 주세요.")
    evidence = _terminal_evidence(session, trip, vehicle, evidence_event_id) if evidence_type == "terminal_observation" else None
    completed_at = _completed_at(evidence, observed_completed_at, now)
    # 차량 단위다. 다른 슬롯은 건드리지 않는다 (FR-OP-04)
    vehicle.operation_status = "completed"
    session.flush()
    recompute_trip_status(session, trip)
    _bump_control(trip)
    decision = OperationDecision(
        scheduled_trip_id=trip.scheduled_trip_id,
        trip_vehicle_id=vehicle.trip_vehicle_id,
        decision_type="complete",
        evidence_type=evidence_type,
        evidence_event_id=evidence.event_id if evidence else None,
        note=note,
        observed_completed_at=completed_at,
        decided_by=principal.account_id,
        decided_at=now,
        control_version=trip.control_version,
    )
    session.add(decision)
    session.flush()
    return DecisionResult(decision, trip, [vehicle])


# ---------- 회차 취소 (13 4장) ----------


def cancel_scheduled_trip(
    session: Session, principal: Principal, trip_id: uuid.UUID, reason: str, expected_control_version: int, now: datetime
) -> DecisionResult:
    trip = lock_trip(session, trip_id)
    session.refresh(trip)
    _check_control_version(trip, expected_control_version)
    if trip.operation_status in FINAL:
        raise _state_conflict("이미 완료되었거나 취소된 회차입니다.")
    vehicles = list(
        session.scalars(select(TripVehicle).where(TripVehicle.scheduled_trip_id == trip_id).order_by(TripVehicle.vehicle_slot))
    )
    for v in vehicles:
        # 이미 실제로 운행을 마친 슬롯의 완료 사실은 덮지 않는다 — 결정 이력으로 남는다
        if v.operation_status != "completed":
            v.operation_status = "cancelled"
    _bump_control(trip)
    session.add(
        decision := OperationDecision(
            scheduled_trip_id=trip_id,
            decision_type="cancel_trip",
            note=reason,
            decided_by=principal.account_id,
            decided_at=now,
            control_version=trip.control_version,
        )
    )
    session.flush()
    recompute_trip_status(session, trip)
    session.flush()
    return DecisionResult(decision, trip, vehicles)


# ---------- 관측 검토 (13 13장) · 복구 (13 15장) ----------


@dataclass
class ReviewResult:
    event: LocationEvent
    review: ObservationReview
    session: CollectionSession
    trip: ScheduledTrip
    skipped: list[LocationEvent] = field(default_factory=list)
    superseded: list[LocationEvent] = field(default_factory=list)


def _event_context(session: Session, event_id: uuid.UUID):
    event = session.get(LocationEvent, event_id)
    if event is None:
        raise not_found("관측 기록")
    sess = session.get(CollectionSession, event.collection_session_id)
    vehicle = session.get(TripVehicle, event.trip_vehicle_id)
    trip = lock_trip(session, vehicle.scheduled_trip_id)
    for row in (trip, event, sess, vehicle):
        session.refresh(row)
    return event, sess, vehicle, trip


def _check_consistency(event: LocationEvent, events: list[LocationEvent], seq_of: dict, duplicate_code: str, duplicate_message: str) -> None:
    """유효로 만들기 전에 재확인: 한 방문 한 유효 관측, 같은 방문 사건 모순, 다른 방문과의 시각 순서 (02 6장 재적용)."""
    if event.occurred_at is None:
        raise AppError(409, "REVIEW_CONFLICT", "발생 시각이 없는 기록은 유효로 만들 수 없습니다.")
    others = [e for e in events if e.event_id != event.event_id and e.validation_status == "valid" and e.event_type != "skipped"]
    here = {e.event_type: e for e in others if e.trip_stop_id == event.trip_stop_id}
    if event.event_type in here:
        raise AppError(409, duplicate_code, duplicate_message)
    if event.event_type == "passed" and "arrived" in here or event.event_type == "arrived" and "passed" in here:
        raise AppError(409, "REVIEW_CONFLICT", "같은 방문에 도착과 통과가 함께 유효할 수 없습니다.")
    target_seq = seq_of[event.trip_stop_id]
    for e in others:
        if e.occurred_at is None:
            continue
        seq = seq_of[e.trip_stop_id]
        if seq == target_seq:
            earlier_required = e.event_type == "arrived" and event.event_type == "departed"
            later_required = e.event_type == "departed" and event.event_type == "arrived"
            bad = earlier_required and e.occurred_at > event.occurred_at or later_required and e.occurred_at < event.occurred_at
        else:
            bad = seq > target_seq and e.occurred_at < event.occurred_at or seq < target_seq and e.occurred_at > event.occurred_at
        if bad:
            raise AppError(409, "EVENT_ORDER_CONFLICT", "다른 유효 관측과 시각 순서가 맞지 않습니다.")


def _make_valid(session, event, sess, trip, vehicle, now, duplicate_code, duplicate_message, prefix):
    """재확인 후 유효로 바꾸고 입력 경로와 같은 파생 효과를 적용한다. 진행 위치는 max라 뒤로 가지 않는다."""
    stops = trip_stops_by_id(session, trip.scheduled_trip_id)
    seq_of = {tid: ts.stop_sequence for tid, (ts, _) in stops.items()}
    events = list(session.scalars(select(LocationEvent).where(LocationEvent.trip_vehicle_id == vehicle.trip_vehicle_id)))
    _check_consistency(event, events, seq_of, duplicate_code, duplicate_message)
    others = [e for e in events if e.event_id != event.event_id]
    views = [
        EventView(e.event_id, e.trip_stop_id, seq_of[e.trip_stop_id], e.event_type, e.occurred_at, e.time_confidence, e.validation_status)
        for e in others
    ]
    skip_ids = gap_visits(trip, sess, stops, others, progress_sequence(views), seq_of[event.trip_stop_id])
    event.validation_status = "valid"
    session.flush()
    return make_public(session, event, sess, trip, vehicle, stops, events, skip_ids, now, f"{prefix}:{uuid.uuid4()}")


def _record_review(session, event, decision, previous, reason, evidence_note, principal, now, sess, trip) -> ObservationReview:
    review = ObservationReview(
        event_id=event.event_id,
        decision=decision,
        previous_validation_status=previous,
        reason=reason,
        evidence_note=evidence_note,
        reviewed_by=principal.account_id,
        reviewed_at=now,
        input_version=sess.input_version,
        control_version=trip.control_version,
    )
    session.add(review)
    session.flush()
    return review


def review_observation(
    session: Session,
    principal: Principal,
    event_id: uuid.UUID,
    decision: str,
    reason: str,
    evidence_note: str | None,
    expected_input_version: int,
    expected_control_version: int,
    now: datetime,
) -> ReviewResult:
    event, sess, vehicle, trip = _event_context(session, event_id)
    _check_input_version(sess, expected_input_version)
    _check_control_version(trip, expected_control_version)
    if event.validation_status != "needs_review":
        raise AppError(409, "REVIEW_CONFLICT", "이미 처리된 기록입니다. 최신 상태를 확인해 주세요.")

    skipped: list[LocationEvent] = []
    superseded: list[LocationEvent] = []
    if decision == "approve":
        if not (evidence_note or "").strip():
            raise invalid("승인에는 확인 근거(evidence_note)가 필요합니다.")
        superseded, skipped = _make_valid(
            session, event, sess, trip, vehicle, now,
            "REVIEW_CONFLICT", "이 방문에 이미 같은 종류의 유효 관측이 있습니다.", "system:approve",
        )
    else:
        # 원본 필드는 지우지 않는다 (13 13장)
        event.validation_status = "cancelled"
        event.cancelled_at = now
        event.cancel_reason = "observation_rejected"

    sess.input_version += 1
    _bump_control(trip)
    review = _record_review(session, event, decision, "needs_review", reason, evidence_note, principal, now, sess, trip)
    return ReviewResult(event, review, sess, trip, skipped, superseded)


def restore_observation(
    session: Session,
    principal: Principal,
    event_id: uuid.UUID,
    reason: str,
    evidence_note: str | None,
    expected_input_version: int,
    expected_control_version: int,
    now: datetime,
) -> ReviewResult:
    event, sess, vehicle, trip = _event_context(session, event_id)
    _check_input_version(sess, expected_input_version)
    _check_control_version(trip, expected_control_version)
    if event.validation_status != "cancelled":
        raise AppError(409, "REVIEW_CONFLICT", "취소된 기록만 복구할 수 있습니다.")
    if event.source == "system":
        raise invalid("자동으로 만든 누락 기록은 복구 대상이 아닙니다. 근거 기록을 복구하면 다시 계산됩니다.")
    previous = session.scalar(
        select(ObservationReview.previous_validation_status)
        .where(ObservationReview.event_id == event_id, ObservationReview.decision.in_(("cancel", "reject")))
        .order_by(ObservationReview.reviewed_at.desc())
        .limit(1)
    )
    if previous is None:
        raise AppError(409, "REVIEW_CONFLICT", "취소 이력이 없어 되돌릴 상태를 알 수 없습니다.")

    skipped: list[LocationEvent] = []
    superseded: list[LocationEvent] = []
    if previous == "valid":
        superseded, skipped = _make_valid(
            session, event, sess, trip, vehicle, now,
            "RESTORE_CONFLICT", "이 방문에 이미 다른 유효 관측이 있습니다. 대체 관측을 먼저 취소해 주세요.", "system:restore",
        )
    else:
        # 취소 직전이 검토 대기였다면 검토 대기로 돌아간다. 복구가 승인을 대신하지 않는다 (FR-OP-22)
        event.validation_status = previous
    event.cancelled_at = None
    event.cancel_reason = None
    session.flush()
    refresh_vehicle_information(session, vehicle)

    sess.input_version += 1
    _bump_control(trip)
    review = _record_review(session, event, "restore", "cancelled", reason, evidence_note, principal, now, sess, trip)
    return ReviewResult(event, review, sess, trip, skipped, superseded)


# ---------- 완료 근거 재검토 (13 14장) ----------


def review_completion(
    session: Session,
    principal: Principal,
    trip_vehicle_id: uuid.UUID,
    decision: str,
    evidence_type: str | None,
    evidence_event_id: uuid.UUID | None,
    note: str | None,
    observed_completed_at: datetime | None,
    expected_control_version: int,
    now: datetime,
) -> DecisionResult:
    vehicle, trip = _vehicle_and_trip(session, trip_vehicle_id)
    _check_control_version(trip, expected_control_version)
    if trip.operation_status == "cancelled":
        raise _state_conflict("취소된 회차에는 완료 재검토를 적용하지 않습니다.")
    if vehicle.operation_status != "completed":
        raise _state_conflict("완료된 차량만 재검토할 수 있습니다.")
    previous = active_completion(session, trip_vehicle_id)

    evidence = None
    completed_at = None
    if decision == "keep_completed":
        if evidence_type is None:
            raise invalid("완료 유지에는 새 근거(evidence_type)가 필요합니다.")
        if evidence_type == "terminal_observation":
            evidence = _terminal_evidence(session, trip, vehicle, evidence_event_id)
        completed_at = _completed_at(evidence, observed_completed_at, now)
    else:
        if not (note or "").strip():
            raise invalid("다시 운행 중으로 되돌리려면 완료 오판을 확인한 사유(note)가 필요합니다.")
        vehicle.operation_status = "scheduled"
        session.flush()
        recompute_trip_status(session, trip)

    _bump_control(trip)
    row = OperationDecision(
        scheduled_trip_id=trip.scheduled_trip_id,
        trip_vehicle_id=trip_vehicle_id,
        decision_type=decision,
        evidence_type=evidence_type if decision == "keep_completed" else None,
        evidence_event_id=evidence.event_id if evidence else None,
        note=note,
        observed_completed_at=completed_at,
        decided_by=principal.account_id,
        decided_at=now,
        supersedes_decision_id=previous.decision_id if previous else None,
        control_version=trip.control_version,
    )
    session.add(row)
    session.flush()
    return DecisionResult(row, trip, [vehicle])


# ---------- 공지 (13 6장) ----------


def trip_route_id(session: Session, trip_id: uuid.UUID) -> uuid.UUID | None:
    return session.scalar(
        select(RoutePattern.route_id)
        .join(RouteVersion, RouteVersion.route_pattern_id == RoutePattern.route_pattern_id)
        .join(ScheduledTrip, ScheduledTrip.route_version_id == RouteVersion.route_version_id)
        .where(ScheduledTrip.scheduled_trip_id == trip_id)
    )


def create_notice(
    session: Session,
    principal: Principal,
    route_id: uuid.UUID,
    trip_id: uuid.UUID | None,
    notice_type: str,
    message: str,
    expires_at: datetime,
    now: datetime,
) -> Notice:
    if session.get(Route, route_id) is None:
        raise not_found("노선")
    if trip_id is not None and trip_route_id(session, trip_id) != route_id:
        raise not_found("이 노선의 회차")
    if expires_at <= now:
        raise invalid("만료 시각은 현재 시각 이후여야 합니다.")
    # 공지 유형 cancel이어도 운행 상태는 바꾸지 않는다 (FR-OP-07)
    notice = Notice(
        route_id=route_id,
        scheduled_trip_id=trip_id,
        notice_type=notice_type,
        message=message,
        created_by=principal.account_id,
        created_at=now,
        expires_at=expires_at,
    )
    session.add(notice)
    session.flush()
    return notice


def expire_notice(session: Session, notice_id: uuid.UUID, now: datetime) -> Notice:
    notice = session.get(Notice, notice_id, with_for_update=True)
    if notice is None:
        raise not_found("공지")
    if notice.expired_early_at is None and notice.expires_at > now:
        notice.expired_early_at = now
        session.flush()
    return notice


def active_notices(session: Session, route_id: uuid.UUID, trip_id: uuid.UUID | None, now: datetime) -> list[Notice]:
    """유효: expired_early_at IS NULL AND now < expires_at.

    trip_id를 주면 노선 전체 공지 + 그 회차 공지, 생략하면 노선의 모든 유효 공지(회차 대상 포함).
    """
    query = select(Notice).where(Notice.route_id == route_id, Notice.expired_early_at.is_(None), Notice.expires_at > now)
    if trip_id is not None:
        query = query.where(Notice.scheduled_trip_id.is_(None) | (Notice.scheduled_trip_id == trip_id))
    return list(session.scalars(query.order_by(Notice.created_at.desc(), Notice.notice_id)))


# ---------- 검토 대상 판정 (13 2장) ----------

# 기준 지점부터 종점까지 예상 소요시간. P5의 travel_times가 생기기 전에는 값이 없다
RemainingDuration = Callable[[Session, TripVehicle, ScheduledTripStop | None], timedelta | None]


def no_travel_times(session: Session, vehicle: TripVehicle, from_stop: ScheduledTripStop | None) -> timedelta | None:
    return None


def mark_sessions_for_review(
    session: Session, now: datetime, remaining: RemainingDuration = no_travel_times, grace_seconds: int | None = None
) -> list[CollectionSession]:
    """기한 경과 AND 완료 근거 없음 → review_required. 운행 완료로 단정하지 않는다 (FR-OP-02·17).

    구간 소요시간이나 session_review_grace_seconds가 없으면 기한을 계산할 근거가 없어 올리지 않는다.
    """
    grace = settings.session_review_grace_seconds if grace_seconds is None else grace_seconds
    if grace is None:
        return []
    marked = []
    rows = session.execute(
        select(CollectionSession, TripVehicle, ScheduledTrip)
        .join(TripVehicle, TripVehicle.trip_vehicle_id == CollectionSession.trip_vehicle_id)
        .join(ScheduledTrip, ScheduledTrip.scheduled_trip_id == TripVehicle.scheduled_trip_id)
        .where(CollectionSession.review_required.is_(False), TripVehicle.operation_status.not_in(FINAL))
    ).all()
    for sess, vehicle, trip in rows:
        events = session.scalars(
            select(LocationEvent).where(
                LocationEvent.trip_vehicle_id == vehicle.trip_vehicle_id,
                LocationEvent.validation_status == "valid",
                LocationEvent.event_type != "skipped",
                LocationEvent.occurred_at.is_not(None),
            )
        ).all()
        last = max(events, key=lambda e: e.occurred_at, default=None)
        if last is not None:
            base_at, from_stop = last.occurred_at, session.get(ScheduledTripStop, last.trip_stop_id)
        else:
            from_stop = session.get(ScheduledTripStop, trip.origin_trip_stop_id) if trip.origin_trip_stop_id else None
            base_at = from_stop.scheduled_departure_at if from_stop else None
        duration = remaining(session, vehicle, from_stop)
        if base_at is None or duration is None or now <= base_at + duration + timedelta(seconds=grace):
            continue
        sess.review_required = True
        sess.review_reason = "review_deadline_exceeded"
        if sess.ended_at is None:
            # 이미 종료된 세션은 ended 유지 (FR-OP-17)
            sess.collection_status = "needs_review"
        marked.append(sess)
    session.flush()
    return marked
