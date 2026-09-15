"""⑤ 실시간 전송 (12 소유) — 회차 상태 확정 스냅샷과 outbox."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TripStateSnapshot(Base):
    """회차의 최신 확정 공개 상태 (12 10장). 캐시 복원은 이 값을 복사만 한다.

    회차마다 최신 한 행만 둔다. 버전별 이력을 쌓지 않는 이유는 저장 비용이며(2026-09-15 결정),
    과거 사실은 location_events·observation_reviews·operation_decisions가 보존한다.
    """

    __tablename__ = "trip_state_snapshots"

    scheduled_trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scheduled_trips.scheduled_trip_id"), primary_key=True)
    state_version: Mapped[int] = mapped_column(Integer)
    # REST /state 응답과 같은 구조. server_time은 응답 메타데이터라 넣지 않는다
    payload: Mapped[dict] = mapped_column(JSONB)
    # 후보 집합·분류 서명 (12 2장). 바뀔 때만 candidates:changed를 발행한다
    candidate_signature: Mapped[list] = mapped_column(JSONB)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OutboxEvent(Base):
    """확정과 전송을 분리한다 (12 4장). 상태 변경과 같은 트랜잭션에서 쌓고, 커밋 뒤 전송 작업이 비운다."""

    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_events_pending", "outbox_id", postgresql_where=text("sent_at IS NULL")),)

    outbox_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    event: Mapped[str] = mapped_column(Text)
    room: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # 전송 작업이 잡아 둔 기한. 작업이 죽으면 기한 뒤 다른 작업이 다시 보낸다 (중복 허용, 소비자 멱등)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
