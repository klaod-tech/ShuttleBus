"""06 7장 API — 로그인, 수집 세션, 관측 입력·취소, 수집 종료, 시계 검증."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Principal, authenticate, issue_token, require_role
from app.clock import get_now
from app.db import get_session
from app.errors import AppError, not_found
from app.idempotency import remember, replay, request_hash, require_key
from app.models.observation import ClockCheck, CollectionSession, LocationEvent
from app.observation import ingest
from app.timeutil import SEOUL

router = APIRouter(prefix="/api/v1")
staff = require_role("collector", "admin")


def _local(dt: datetime | None) -> datetime | None:
    return dt.astimezone(SEOUL) if dt else None


# ---------- 스키마 ----------


class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str


class SessionStartIn(BaseModel):
    trip_vehicle_id: uuid.UUID
    shuttle_id: uuid.UUID | None = None
    collection_start_trip_stop_id: uuid.UUID | None = None
    # 새로고침·재시작 시 로컬에 보관한 값을 다시 보낸다. 처음 시작이면 생략
    writer_instance_id: uuid.UUID | None = None


class EventOut(BaseModel):
    event_id: uuid.UUID
    trip_stop_id: uuid.UUID
    event_type: str
    occurred_at: AwareDatetime | None
    time_confidence: str
    received_at: datetime
    source: str
    client_event_id: str
    client_sequence: int | None
    validation_status: str
    review_reason: str | None
    parent_event_id: uuid.UUID | None
    cancelled_at: datetime | None
    cancel_reason: str | None


class SessionOut(BaseModel):
    collection_session_id: uuid.UUID
    trip_vehicle_id: uuid.UUID
    shuttle_id: uuid.UUID | None
    collector_id: uuid.UUID | None
    producer_type: str
    comparison_policy: str
    collection_start_trip_stop_id: uuid.UUID | None
    collection_status: str
    input_version: int
    writer_instance_id: uuid.UUID | None
    review_required: bool
    started_at: datetime
    ended_at: AwareDatetime | None


class SessionDetailOut(SessionOut):
    last_observation: EventOut | None
    unresolved_events: list[EventOut]
    events: list[EventOut]


class ObservationIn(BaseModel):
    trip_stop_id: uuid.UUID
    event_type: Literal["arrived", "departed", "passed"]
    occurred_at: AwareDatetime
    client_event_id: str = Field(min_length=1, max_length=200)
    client_sequence: int = Field(ge=1)
    expected_input_version: int
    confirm_skip: bool = False
    writer_instance_id: uuid.UUID
    clock_check_id: uuid.UUID | None = None


class ObservationOut(BaseModel):
    event: EventOut
    skipped_events: list[EventOut]
    superseded_events: list[EventOut]
    input_version: int
    state_version: int


class CancelIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    expected_input_version: int


class CancelOut(BaseModel):
    event: EventOut
    cascaded_events: list[EventOut]
    input_version: int
    state_version: int


class EndIn(BaseModel):
    ended_at: AwareDatetime
    expected_input_version: int


class ClockBeginIn(BaseModel):
    device_sent_at: AwareDatetime


class ClockCompleteIn(BaseModel):
    device_received_at: AwareDatetime


class ClockCheckOut(BaseModel):
    clock_check_id: uuid.UUID
    collection_session_id: uuid.UUID
    device_sent_at: AwareDatetime
    server_received_at: datetime
    server_responded_at: datetime
    device_received_at: AwareDatetime | None
    checked_at: datetime | None
    estimated_offset_seconds: float | None
    uncertainty_seconds: float | None
    valid_until: datetime | None


def event_out(e: LocationEvent) -> EventOut:
    return EventOut(
        event_id=e.event_id,
        trip_stop_id=e.trip_stop_id,
        event_type=e.event_type,
        occurred_at=_local(e.occurred_at),
        time_confidence=e.time_confidence,
        received_at=_local(e.received_at),
        source=e.source,
        client_event_id=e.client_event_id,
        client_sequence=e.client_sequence,
        validation_status=e.validation_status,
        review_reason=e.review_reason,
        parent_event_id=e.parent_event_id,
        cancelled_at=_local(e.cancelled_at),
        cancel_reason=e.cancel_reason,
    )


def session_out(s: CollectionSession) -> SessionOut:
    return SessionOut(
        collection_session_id=s.collection_session_id,
        trip_vehicle_id=s.trip_vehicle_id,
        shuttle_id=s.shuttle_id,
        collector_id=s.collector_id,
        producer_type=s.producer_type,
        comparison_policy=s.comparison_policy,
        collection_start_trip_stop_id=s.collection_start_trip_stop_id,
        collection_status=s.collection_status,
        input_version=s.input_version,
        writer_instance_id=s.writer_instance_id,
        review_required=s.review_required,
        started_at=_local(s.started_at),
        ended_at=_local(s.ended_at),
    )


def clock_out(c: ClockCheck) -> ClockCheckOut:
    return ClockCheckOut(
        clock_check_id=c.clock_check_id,
        collection_session_id=c.collection_session_id,
        device_sent_at=_local(c.device_sent_at),
        server_received_at=_local(c.server_received_at),
        server_responded_at=_local(c.server_responded_at),
        device_received_at=_local(c.device_received_at),
        checked_at=_local(c.checked_at),
        estimated_offset_seconds=c.estimated_offset_seconds,
        uncertainty_seconds=c.uncertainty_seconds,
        valid_until=_local(c.valid_until),
    )


def _idempotent(session, principal, key, endpoint, body, handler):
    """01 4장 2단계: 같은 키·같은 본문이면 저장된 응답을 그대로 돌려준다."""
    key = require_key(key)
    digest = request_hash(endpoint, body)
    stored = replay(session, principal.account_id, key, endpoint, digest)
    if stored is not None:
        return JSONResponse(status_code=stored[0], content=stored[1], media_type="application/json; charset=utf-8")
    try:
        status, payload = handler()
    except Exception:
        session.rollback()  # 거절된 요청의 잠금·중간 변경을 남기지 않는다
        raise
    remember(session, principal.account_id, key, endpoint, digest, status, payload)
    session.commit()
    return JSONResponse(status_code=status, content=_jsonable(payload), media_type="application/json; charset=utf-8")


def _jsonable(payload):
    from fastapi.encoders import jsonable_encoder

    return jsonable_encoder(payload)


# ---------- 경로 ----------


@router.post("/auth/login", response_model=LoginOut, summary="입력자·관리자 로그인")
def login(body: LoginIn, session: Session = Depends(get_session), now: datetime = Depends(get_now)):
    account = authenticate(session, body.username, body.password)
    if account is None:
        raise AppError(401, "AUTH_REQUIRED", "아이디 또는 비밀번호가 올바르지 않습니다.")
    token, ttl = issue_token(account, now)
    return LoginOut(access_token=token, expires_in=ttl, role=account.role)


@router.post("/collection-sessions", response_model=SessionOut, status_code=201, summary="수집 시작 또는 기존 열린 세션 반환")
def start_collection(
    body: SessionStartIn,
    idempotency_key: str | None = Header(default=None),
    principal: Principal = Depends(staff),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    def handler():
        result = ingest.start_session(
            session, principal, body.trip_vehicle_id, body.shuttle_id, body.collection_start_trip_stop_id,
            body.writer_instance_id, now,
        )
        return (201 if result.created else 200), session_out(result.session)

    return _idempotent(session, principal, idempotency_key, "POST /collection-sessions", body.model_dump(), handler)


@router.get("/collection-sessions/{session_id}", response_model=SessionDetailOut, summary="수집 세션 조회")
def get_collection(
    session_id: uuid.UUID,
    principal: Principal = Depends(staff),
    session: Session = Depends(get_session),
):
    sess = session.get(CollectionSession, session_id)
    if sess is None:
        raise not_found("수집 세션")
    if principal.role != "admin" and sess.collector_id != principal.account_id:
        raise AppError(403, "FORBIDDEN", "다른 입력자의 수집 세션입니다.")
    events = list(
        session.scalars(
            select(LocationEvent)
            .where(LocationEvent.collection_session_id == session_id)
            .order_by(LocationEvent.received_at, LocationEvent.client_sequence)
        )
    )
    progress = [e for e in events if e.validation_status == "valid" and e.event_type != "skipped" and e.occurred_at]
    last = max(progress, key=lambda e: (e.occurred_at, e.client_sequence or 0), default=None)
    return SessionDetailOut(
        **session_out(sess).model_dump(),
        last_observation=event_out(last) if last else None,
        unresolved_events=[event_out(e) for e in events if e.validation_status == "needs_review"],
        events=[event_out(e) for e in events],
    )


@router.post("/collection-sessions/{session_id}/events", response_model=ObservationOut, status_code=201, summary="관측 입력")
def post_observation(
    session_id: uuid.UUID,
    body: ObservationIn,
    idempotency_key: str | None = Header(default=None),
    principal: Principal = Depends(staff),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    def handler():
        r = ingest.submit_observation(
            session, principal, session_id,
            ingest.ObservationInput(**body.model_dump()),
            now,
        )
        payload = ObservationOut(
            event=event_out(r.event),
            skipped_events=[event_out(e) for e in r.skipped],
            superseded_events=[event_out(e) for e in r.superseded],
            input_version=r.session.input_version,
            state_version=r.trip.state_version,
        )
        return (200 if r.replayed else 201), payload

    return _idempotent(
        session, principal, idempotency_key, f"POST /collection-sessions/{session_id}/events", body.model_dump(), handler
    )


@router.post("/events/{event_id}/cancel", response_model=CancelOut, summary="입력 취소 — 원본 보존")
def post_cancel(
    event_id: uuid.UUID,
    body: CancelIn,
    idempotency_key: str | None = Header(default=None),
    principal: Principal = Depends(staff),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    def handler():
        r = ingest.cancel_observation(session, principal, event_id, body.reason, body.expected_input_version, now)
        return 200, CancelOut(
            event=event_out(r.event),
            cascaded_events=[event_out(e) for e in r.cascaded],
            input_version=r.session.input_version,
            state_version=r.trip.state_version,
        )

    return _idempotent(session, principal, idempotency_key, f"POST /events/{event_id}/cancel", body.model_dump(), handler)


@router.post("/collection-sessions/{session_id}/end", response_model=SessionOut, summary="수집 종료 (운행 완료 아님)")
def post_end(
    session_id: uuid.UUID,
    body: EndIn,
    idempotency_key: str | None = Header(default=None),
    principal: Principal = Depends(staff),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    def handler():
        sess = ingest.end_session(session, principal, session_id, body.ended_at, body.expected_input_version, now)
        return 200, session_out(sess)

    return _idempotent(
        session, principal, idempotency_key, f"POST /collection-sessions/{session_id}/end", body.model_dump(), handler
    )


@router.post(
    "/collection-sessions/{session_id}/clock-checks", response_model=ClockCheckOut, status_code=201,
    summary="시계 확인 1단계 — 단말 송신 시각을 보내고 서버 수신·응답 시각을 받는다",
)
def post_clock_begin(
    session_id: uuid.UUID,
    body: ClockBeginIn,
    principal: Principal = Depends(staff),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    check = ingest.begin_clock_check(session, principal, session_id, body.device_sent_at, now)
    session.commit()
    return clock_out(check)


@router.post(
    "/clock-checks/{clock_check_id}/complete", response_model=ClockCheckOut,
    summary="시계 확인 2단계 — 단말 수신 시각으로 오차·불확실성 계산",
)
def post_clock_complete(
    clock_check_id: uuid.UUID,
    body: ClockCompleteIn,
    principal: Principal = Depends(staff),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
):
    check = ingest.complete_clock_check(session, principal, clock_check_id, body.device_received_at, now)
    session.commit()
    return clock_out(check)
