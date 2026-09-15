"""outbox 적재·전송 (12 4장). 전송은 커밋 뒤 별도 작업이 한다. 중복 전송은 허용하고 소비자가 버전으로 걸러낸다."""

import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.realtime import OutboxEvent

log = logging.getLogger("app.realtime")

LEASE_SECONDS = 30
SENT_RETENTION = timedelta(days=1)


def enqueue(session: Session, event: str, room: str, payload: dict, now: datetime) -> None:
    session.add(OutboxEvent(event=event, room=room, payload=payload, created_at=now, attempts=0))


def claim_batch(session: Session, now: datetime, limit: int = 100) -> list[OutboxEvent]:
    """미전송 항목을 잡는다. 여러 인스턴스가 같은 항목을 동시에 잡지 않도록 SKIP LOCKED + 임대 기한."""
    rows = list(
        session.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.sent_at.is_(None), (OutboxEvent.locked_until.is_(None)) | (OutboxEvent.locked_until < now))
            .order_by(OutboxEvent.outbox_id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    for row in rows:
        row.locked_until = now + timedelta(seconds=LEASE_SECONDS)
        row.attempts += 1
    session.commit()
    return rows


Emit = Callable[[str, str, dict], Awaitable[None]]


async def drain_once(session_scope: Callable[[], AbstractContextManager[Session]], emit: Emit, now: datetime) -> int:
    """잡은 순서(적재 순)대로 보낸다. 실패한 항목은 임대 기한 뒤 다시 보낸다 (FR-RT-12)."""
    with session_scope() as session:
        rows = claim_batch(session, now)
        claimed = [(r.outbox_id, r.event, r.room, r.payload) for r in rows]
    sent, failed = [], {}
    for outbox_id, event, room, payload in claimed:
        try:
            await emit(event, room, payload)
            sent.append(outbox_id)
        except Exception as exc:  # 전송 실패는 기록하고 다음 항목을 계속 보낸다
            log.warning("outbox %s 전송 실패: %s", outbox_id, exc)
            failed[outbox_id] = str(exc)[:500]
    with session_scope() as session:
        if sent:
            session.execute(update(OutboxEvent).where(OutboxEvent.outbox_id.in_(sent)).values(sent_at=now, locked_until=None))
        for outbox_id, error in failed.items():
            session.execute(update(OutboxEvent).where(OutboxEvent.outbox_id == outbox_id).values(last_error=error))
        session.commit()
    return len(sent)


def purge_sent(session: Session, now: datetime) -> int:
    """전송이 끝난 항목은 하루 뒤 지운다. 상태의 기준은 스냅샷이므로 전송 기록을 오래 둘 이유가 없다."""
    result = session.execute(delete(OutboxEvent).where(OutboxEvent.sent_at.is_not(None), OutboxEvent.sent_at < now - SENT_RETENTION))
    session.commit()
    return result.rowcount or 0
