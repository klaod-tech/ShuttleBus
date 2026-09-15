"""⑤ 운영 층 (13 소유) — 공지, 완료·취소·재검토 결정 이력."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import DECISION_TYPE, EVIDENCE_TYPE, NOTICE_TYPE, Base, enum


class Notice(Base):
    """노선 전체 또는 특정 회차 공지 (13 6장). 공지 유형 cancel은 안내일 뿐 상태를 바꾸지 않는다."""

    __tablename__ = "notices"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        Index(None, "route_id", "expires_at"),
    )

    notice_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    route_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("routes.route_id"))
    scheduled_trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scheduled_trips.scheduled_trip_id"))
    notice_type: Mapped[str] = mapped_column(enum("notice_type", NOTICE_TYPE))
    message: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_accounts.account_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expired_early_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationDecision(Base):
    """완료·취소·정정 결정 이력 (13 14장). 덮어쓰지 않고 supersedes_decision_id로 잇는다.

    decision_type: complete(차량 완료) / cancel_trip(회차 취소) / keep_completed·reopen(완료 재검토).
    decided_by가 null이면 서버 자동 결정(terminal_observation)이다.
    """

    __tablename__ = "operation_decisions"
    __table_args__ = (
        CheckConstraint(
            "decision_type = 'cancel_trip' OR trip_vehicle_id IS NOT NULL", name="vehicle_decision_has_vehicle"
        ),
        CheckConstraint(
            "decision_type NOT IN ('complete', 'keep_completed') OR evidence_type IS NOT NULL",
            name="completion_has_evidence",
        ),
        Index(None, "scheduled_trip_id", "decided_at"),
    )

    decision_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scheduled_trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scheduled_trips.scheduled_trip_id"))
    trip_vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trip_vehicles.trip_vehicle_id"))
    decision_type: Mapped[str] = mapped_column(enum("decision_type", DECISION_TYPE))
    evidence_type: Mapped[str | None] = mapped_column(enum("evidence_type", EVIDENCE_TYPE))
    evidence_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("location_events.event_id"))
    note: Mapped[str | None] = mapped_column(Text)
    observed_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_accounts.account_id"))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    supersedes_decision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("operation_decisions.decision_id"))
    control_version: Mapped[int] = mapped_column(Integer)
