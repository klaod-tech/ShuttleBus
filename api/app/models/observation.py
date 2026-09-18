"""③ 관측 층 (02·06 소유) · 입력자 계정 · 멱등 기록 · 관측 결정 이력."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    COLLECTION_STATUS,
    COMPARISON_POLICY,
    END_REASON,
    EVENT_SOURCE,
    OBSERVED_EVENT_TYPE,
    PRODUCER_TYPE,
    REVIEW_DECISION,
    STAFF_ROLE,
    TIME_CONFIDENCE,
    VALIDATION_STATUS,
    Base,
    enum,
)


class StaffAccount(Base):
    """입력자·관리자 계정 (06 7장 로그인). 날짜와 무관한 기준 자료로 ① 층에 둔다."""

    __tablename__ = "staff_accounts"

    account_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(enum("role", STAFF_ROLE))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # 비밀번호·역할·사용 여부를 바꾼 시각. 계정 관리 이력의 최소 근거다
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CollectionSession(Base):
    __tablename__ = "collection_sessions"
    __table_args__ = (
        # 차량 슬롯당 열린 세션은 생산자 종류별로 하나 (06 1장)
        Index(
            "uq_collection_sessions_open_per_producer",
            "trip_vehicle_id",
            "producer_type",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        CheckConstraint("(collection_status = 'ended') = (ended_at IS NOT NULL)", name="ended_matches_status"),
    )

    collection_session_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    trip_vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trip_vehicles.trip_vehicle_id"))
    shuttle_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    collector_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_accounts.account_id"))
    producer_type: Mapped[str] = mapped_column(enum("producer_type", PRODUCER_TYPE))
    device_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    comparison_policy: Mapped[str] = mapped_column(enum("comparison_policy", COMPARISON_POLICY))
    review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reason: Mapped[str | None] = mapped_column(Text)
    collection_start_trip_stop_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scheduled_trip_stops.trip_stop_id")
    )
    collection_status: Mapped[str] = mapped_column(enum("collection_status", COLLECTION_STATUS))
    input_version: Mapped[int] = mapped_column(Integer, default=1)
    writer_instance_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    end_reason: Mapped[str | None] = mapped_column(enum("end_reason", END_REASON))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClockCheck(Base):
    """서버가 측정한 단말 시계 오차 근거 (02 12장). 네 시각 교환으로 오차와 불확실성을 구한다."""

    __tablename__ = "clock_checks"

    clock_check_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    collection_session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collection_sessions.collection_session_id"))
    device_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    server_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    server_responded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    device_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_offset_seconds: Mapped[float | None] = mapped_column(Double)
    uncertainty_seconds: Mapped[float | None] = mapped_column(Double)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LocationEvent(Base):
    __tablename__ = "location_events"
    __table_args__ = (
        UniqueConstraint("collection_session_id", "client_event_id"),
        Index(
            "uq_location_events_session_client_sequence",
            "collection_session_id",
            "client_sequence",
            unique=True,
            postgresql_where=text("client_sequence IS NOT NULL"),
        ),
        # 같은 방문·차량·종류의 유효 관측은 하나 (02 2장)
        Index(
            "uq_location_events_valid_visit_event",
            "trip_stop_id",
            "trip_vehicle_id",
            "event_type",
            unique=True,
            postgresql_where=text("validation_status = 'valid'"),
        ),
        CheckConstraint(
            "(occurred_at IS NULL) = (time_confidence = 'inferred')", name="inferred_has_no_time"
        ),
        CheckConstraint("(source = 'system') = (client_sequence IS NULL)", name="system_has_no_sequence"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    collection_session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collection_sessions.collection_session_id"))
    trip_vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trip_vehicles.trip_vehicle_id"))
    trip_stop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scheduled_trip_stops.trip_stop_id"))
    event_type: Mapped[str] = mapped_column(enum("event_type", OBSERVED_EVENT_TYPE))
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    time_confidence: Mapped[str] = mapped_column(enum("time_confidence", TIME_CONFIDENCE))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(enum("source", EVENT_SOURCE))
    client_event_id: Mapped[str] = mapped_column(Text)
    client_sequence: Mapped[int | None] = mapped_column(Integer)
    clock_check_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clock_checks.clock_check_id"))
    review_reason: Mapped[str | None] = mapped_column(Text)
    validation_status: Mapped[str] = mapped_column(enum("validation_status", VALIDATION_STATUS))
    parent_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("location_events.event_id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)


class ObservationReview(Base):
    """관측 취소·검토·복구 결정 이력 (13 13·15장). 덮지 않고 추가한다."""

    __tablename__ = "observation_reviews"

    review_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("location_events.event_id"))
    decision: Mapped[str] = mapped_column(enum("decision", REVIEW_DECISION))
    previous_validation_status: Mapped[str] = mapped_column(enum("previous_validation_status", VALIDATION_STATUS))
    reason: Mapped[str | None] = mapped_column(Text)
    evidence_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_accounts.account_id"))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    input_version: Mapped[int | None] = mapped_column(Integer)
    control_version: Mapped[int | None] = mapped_column(Integer)


class IdempotencyRecord(Base):
    """변경 요청의 Idempotency-Key 재사용 판정 (01 4장). 같은 키·같은 본문이면 저장된 응답을 돌려준다."""

    __tablename__ = "idempotency_records"

    account_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(Text, primary_key=True)
    endpoint: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(Text)
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
