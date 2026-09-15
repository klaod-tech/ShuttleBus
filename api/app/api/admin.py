"""13 API — 관리자 운영 기능과 학생용 공지 조회."""

import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.collection import EventOut, SessionOut, _idempotent, _local, event_out, session_out
from app.auth import Principal, require_role
from app.clock import get_now
from app.db import get_session
from app.errors import not_found
from app.models.calendar import ScheduledTrip, TripVehicle
from app.models.observation import CollectionSession, LocationEvent, ObservationReview
from app.models.operations import Notice, OperationDecision
from app.models.reference import TripTemplate
from app.operations import service
from app.operations.completion import completion_review_required

router = APIRouter(prefix="/api/v1")
admin = require_role("admin")

EvidenceType = Literal["terminal_observation", "collector_report", "operator_notice", "admin_judgement"]


# ---------- 스키마 ----------


class DecisionOut(BaseModel):
    decision_id: uuid.UUID
    trip_id: uuid.UUID
    trip_vehicle_id: uuid.UUID | None
    decision_type: str
    evidence_type: str | None
    evidence_event_id: uuid.UUID | None
    note: str | None
    observed_completed_at: datetime | None
    decided_by: uuid.UUID | None
    decided_at: datetime
    supersedes_decision_id: uuid.UUID | None
    control_version: int


class VehicleStatusOut(BaseModel):
    trip_vehicle_id: uuid.UUID
    vehicle_slot: int
    operation_status: str
    completion_review_required: bool


class DecisionResultOut(BaseModel):
    decision: DecisionOut
    trip_operation_status: str
    vehicles: list[VehicleStatusOut]
    control_version: int
    state_version: int


class CompletionIn(BaseModel):
    evidence_type: EvidenceType
    note: str | None = Field(default=None, max_length=1000)
    observed_completed_at: AwareDatetime | None = None
    # terminal_observation을 고를 때만. 종점 유효 실측을 가리킨다
    evidence_event_id: uuid.UUID | None = None
    expected_control_version: int


class CancellationIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    expected_control_version: int


class CompletionReviewIn(BaseModel):
    decision: Literal["keep_completed", "reopen"]
    evidence_type: EvidenceType | None = None
    evidence_event_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=1000)
    observed_completed_at: AwareDatetime | None = None
    expected_control_version: int


class ReviewIn(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=1, max_length=1000)
    evidence_note: str | None = Field(default=None, max_length=1000)
    expected_input_version: int
    expected_control_version: int


class RestoreIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    evidence_note: str | None = Field(default=None, max_length=1000)
    expected_input_version: int
    expected_control_version: int


class ReviewRecordOut(BaseModel):
    review_id: uuid.UUID
    event_id: uuid.UUID
    decision: str
    previous_validation_status: str
    reason: str | None
    evidence_note: str | None
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime
    input_version: int | None
    control_version: int | None


class ReviewResultOut(BaseModel):
    event: EventOut
    review: ReviewRecordOut
    skipped_events: list[EventOut]
    superseded_events: list[EventOut]
    input_version: int
    control_version: int
    state_version: int


class NoticeIn(BaseModel):
    route_id: uuid.UUID
    trip_id: uuid.UUID | None = None
    notice_type: Literal["delay", "cancel", "info"]
    message: str = Field(min_length=1, max_length=2000)
    expires_at: AwareDatetime


class NoticeOut(BaseModel):
    notice_id: uuid.UUID
    route_id: uuid.UUID
    trip_id: uuid.UUID | None
    notice_type: str
    message: str
    created_at: datetime
    expires_at: datetime
    expired_early_at: datetime | None


class NoticeListOut(BaseModel):
    server_time: datetime
    notices: list[NoticeOut]


class AdminSessionOut(SessionOut):
    trip_id: uuid.UUID
    trip_no: int
    service_date: date
    vehicle_slot: int
    vehicle_operation_status: str
    completion_review_required: bool
    last_observation: EventOut | None
    unresolved_event_count: int


class AdminSessionListOut(BaseModel):
    sessions: list[AdminSessionOut]


class AdminSessionEventsOut(BaseModel):
    session: SessionOut
    events: list[EventOut]
    reviews: list[ReviewRecordOut]


# ---------- 변환 ----------


def decision_out(d: OperationDecision) -> DecisionOut:
    return DecisionOut(
        decision_id=d.decision_id,
        trip_id=d.scheduled_trip_id,
        trip_vehicle_id=d.trip_vehicle_id,
        decision_type=d.decision_type,
        evidence_type=d.evidence_type,
        evidence_event_id=d.evidence_event_id,
        note=d.note,
        observed_completed_at=_local(d.observed_completed_at),
        decided_by=d.decided_by,
        decided_at=_local(d.decided_at),
        supersedes_decision_id=d.supersedes_decision_id,
        control_version=d.control_version,
    )


def review_out(r: ObservationReview) -> ReviewRecordOut:
    return ReviewRecordOut(
        review_id=r.review_id,
        event_id=r.event_id,
        decision=r.decision,
        previous_validation_status=r.previous_validation_status,
        reason=r.reason,
        evidence_note=r.evidence_note,
        reviewed_by=r.reviewed_by,
        reviewed_at=_local(r.reviewed_at),
        input_version=r.input_version,
        control_version=r.control_version,
    )


def notice_out(n: Notice) -> NoticeOut:
    return NoticeOut(
        notice_id=n.notice_id,
        route_id=n.route_id,
        trip_id=n.scheduled_trip_id,
        notice_type=n.notice_type,
        message=n.message,
        created_at=_local(n.created_at),
        expires_at=_local(n.expires_at),
        expired_early_at=_local(n.expired_early_at),
    )


def decision_result_out(session: Session, r: service.DecisionResult) -> DecisionResultOut:
    return DecisionResultOut(
        decision=decision_out(r.decision),
        trip_operation_status=r.trip.operation_status,
        vehicles=[
            VehicleStatusOut(
                trip_vehicle_id=v.trip_vehicle_id,
                vehicle_slot=v.vehicle_slot,
                operation_status=v.operation_status,
                completion_review_required=completion_review_required(session, v),
            )
            for v in r.vehicles
        ],
        control_version=r.trip.control_version,
        state_version=r.trip.state_version,
    )


def review_result_out(r: service.ReviewResult) -> ReviewResultOut:
    return ReviewResultOut(
        event=event_out(r.event),
        review=review_out(r.review),
        skipped_events=[event_out(e) for e in r.skipped],
        superseded_events=[event_out(e) for e in r.superseded],
        input_version=r.session.input_version,
        control_version=r.trip.control_version,
        state_version=r.trip.state_version,
    )


# ---------- 운행 상태 ----------


@router.post("/admin/trip-vehicles/{trip_vehicle_id}/completion", response_model=DecisionResultOut, summary="차량 완료 확정")
def post_completion(
    trip_vehicle_id: uuid.UUID,
    body: CompletionIn,
    idempotency_key: str | None = Header(default=None),
    principal: Principal = Depends(admin),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    def handler():
        r = service.complete_trip_vehicle(
            session, principal, trip_vehicle_id, body.evidence_type, body.note, body.observed_completed_at,
            body.evidence_event_id, body.expected_control_version, now,
        )
        return 200, decision_result_out(session, r)

    endpoint = f"POST /admin/trip-vehicles/{trip_vehicle_id}/completion"
    return _idempotent(session, principal, idempotency_key, endpoint, body.model_dump(), handler)


@router.post("/admin/trip-vehicles/{trip_vehicle_id}/completion-review", response_model=DecisionResultOut, summary="완료 근거 재검토")
def post_completion_review(
    trip_vehicle_id: uuid.UUID,
    body: CompletionReviewIn,
    idempotency_key: str | None = Header(default=None),
    principal: Principal = Depends(admin),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    def handler():
        r = service.review_completion(
            session, principal, trip_vehicle_id, body.decision, body.evidence_type, body.evidence_event_id,
            body.note, body.observed_completed_at, body.expected_control_version, now,
        )
        return 200, decision_result_out(session, r)

    endpoint = f"POST /admin/trip-vehicles/{trip_vehicle_id}/completion-review"
    return _idempotent(session, principal, idempotency_key, endpoint, body.model_dump(), handler)


@router.post("/admin/scheduled-trips/{trip_id}/cancellation", response_model=DecisionResultOut, summary="회차 취소")
def post_cancellation(
    trip_id: uuid.UUID,
    body: CancellationIn,
    idempotency_key: str | None = Header(default=None),
    principal: Principal = Depends(admin),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    def handler():
        r = service.cancel_scheduled_trip(session, principal, trip_id, body.reason, body.expected_control_version, now)
        return 200, decision_result_out(session, r)

    endpoint = f"POST /admin/scheduled-trips/{trip_id}/cancellation"
    return _idempotent(session, principal, idempotency_key, endpoint, body.model_dump(), handler)


# ---------- 관측 검토 ----------


@router.post("/admin/events/{event_id}/review", response_model=ReviewResultOut, summary="검토 대기 관측 승인·기각")
def post_review(
    event_id: uuid.UUID,
    body: ReviewIn,
    idempotency_key: str | None = Header(default=None),
    principal: Principal = Depends(admin),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    def handler():
        r = service.review_observation(
            session, principal, event_id, body.decision, body.reason, body.evidence_note,
            body.expected_input_version, body.expected_control_version, now,
        )
        return 200, review_result_out(r)

    return _idempotent(session, principal, idempotency_key, f"POST /admin/events/{event_id}/review", body.model_dump(), handler)


@router.post("/admin/events/{event_id}/restore", response_model=ReviewResultOut, summary="오취소 복구 — 취소 직전 상태로")
def post_restore(
    event_id: uuid.UUID,
    body: RestoreIn,
    idempotency_key: str | None = Header(default=None),
    principal: Principal = Depends(admin),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    def handler():
        r = service.restore_observation(
            session, principal, event_id, body.reason, body.evidence_note,
            body.expected_input_version, body.expected_control_version, now,
        )
        return 200, review_result_out(r)

    return _idempotent(session, principal, idempotency_key, f"POST /admin/events/{event_id}/restore", body.model_dump(), handler)


# ---------- 공지 ----------


@router.get("/notices", response_model=NoticeListOut, summary="현재 유효 공지 (인증 불필요)")
def get_notices(
    route_id: uuid.UUID,
    trip_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    notices = service.active_notices(session, route_id, trip_id, now)
    return NoticeListOut(server_time=_local(now), notices=[notice_out(n) for n in notices])


@router.post("/admin/notices", response_model=NoticeOut, status_code=201, summary="공지 생성")
def post_notice(
    body: NoticeIn,
    idempotency_key: str | None = Header(default=None),
    principal: Principal = Depends(admin),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    def handler():
        n = service.create_notice(session, principal, body.route_id, body.trip_id, body.notice_type, body.message, body.expires_at, now)
        return 201, notice_out(n)

    return _idempotent(session, principal, idempotency_key, "POST /admin/notices", body.model_dump(), handler)


@router.post("/admin/notices/{notice_id}/expire", response_model=NoticeOut, summary="공지 조기 만료")
def post_notice_expire(
    notice_id: uuid.UUID,
    idempotency_key: str | None = Header(default=None),
    principal: Principal = Depends(admin),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    def handler():
        return 200, notice_out(service.expire_notice(session, notice_id, now))

    return _idempotent(session, principal, idempotency_key, f"POST /admin/notices/{notice_id}/expire", {}, handler)


# ---------- 기록 조회 ----------


@router.get("/admin/collection-sessions", response_model=AdminSessionListOut, summary="수집 기록 목록 — 검토 대상 필터")
def list_admin_sessions(
    service_date: date,
    collection_status: Literal["not_started", "collecting", "ended", "needs_review"] | None = None,
    review_required: bool | None = Query(default=None),
    principal: Principal = Depends(admin),
    session: Session = Depends(get_session),
):
    query = (
        select(CollectionSession, TripVehicle, ScheduledTrip, TripTemplate)
        .join(TripVehicle, TripVehicle.trip_vehicle_id == CollectionSession.trip_vehicle_id)
        .join(ScheduledTrip, ScheduledTrip.scheduled_trip_id == TripVehicle.scheduled_trip_id)
        .join(TripTemplate, TripTemplate.trip_template_id == ScheduledTrip.trip_template_id)
        .where(ScheduledTrip.service_date == service_date)
        .order_by(TripTemplate.trip_no, TripVehicle.vehicle_slot, CollectionSession.started_at)
    )
    if collection_status is not None:
        query = query.where(CollectionSession.collection_status == collection_status)
    if review_required is not None:
        query = query.where(CollectionSession.review_required.is_(review_required))

    rows = []
    for sess, vehicle, trip, template in session.execute(query):
        progress = session.scalars(
            select(LocationEvent).where(
                LocationEvent.collection_session_id == sess.collection_session_id,
                LocationEvent.validation_status == "valid",
                LocationEvent.event_type != "skipped",
                LocationEvent.occurred_at.is_not(None),
            )
        ).all()
        last = max(progress, key=lambda e: (e.occurred_at, e.client_sequence or 0), default=None)
        unresolved = session.scalar(
            select(func.count()).where(
                LocationEvent.collection_session_id == sess.collection_session_id,
                LocationEvent.validation_status == "needs_review",
            )
        )
        rows.append(
            AdminSessionOut(
                **session_out(sess).model_dump(),
                trip_id=trip.scheduled_trip_id,
                trip_no=template.trip_no,
                service_date=trip.service_date,
                vehicle_slot=vehicle.vehicle_slot,
                vehicle_operation_status=vehicle.operation_status,
                completion_review_required=completion_review_required(session, vehicle),
                last_observation=event_out(last) if last else None,
                unresolved_event_count=unresolved,
            )
        )
    return AdminSessionListOut(sessions=rows)


@router.get("/admin/collection-sessions/{session_id}/events", response_model=AdminSessionEventsOut, summary="취소·누락 포함 전체 이력")
def admin_session_events(
    session_id: uuid.UUID,
    principal: Principal = Depends(admin),
    session: Session = Depends(get_session),
):
    sess = session.get(CollectionSession, session_id)
    if sess is None:
        raise not_found("수집 세션")
    events = list(
        session.scalars(
            select(LocationEvent)
            .where(LocationEvent.collection_session_id == session_id)
            .order_by(LocationEvent.received_at, LocationEvent.client_sequence)
        )
    )
    reviews = session.scalars(
        select(ObservationReview)
        .where(ObservationReview.event_id.in_([e.event_id for e in events]))
        .order_by(ObservationReview.reviewed_at, ObservationReview.review_id)
    )
    return AdminSessionEventsOut(
        session=session_out(sess),
        events=[event_out(e) for e in events],
        reviews=[review_out(r) for r in reviews],
    )
