"""Idempotency-Key 처리 (01 4장).

같은 키·같은 본문 → 저장된 응답 그대로. 같은 키·다른 본문 → IDEMPOTENCY_KEY_REUSED.
기록은 요청 처리와 같은 트랜잭션에 넣는다 — 처리가 롤백되면 키도 남지 않는다.
"""

import hashlib
import json
import uuid

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.errors import AppError, invalid
from app.models.observation import IdempotencyRecord


def request_hash(endpoint: str, body: dict) -> str:
    canonical = json.dumps({"endpoint": endpoint, "body": jsonable_encoder(body)}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def require_key(key: str | None) -> str:
    if not key or len(key) > 200:
        raise invalid("변경 요청에는 Idempotency-Key 헤더가 필요합니다.")
    return key


def replay(session: Session, account_id: uuid.UUID, key: str, endpoint: str, digest: str) -> tuple[int, dict] | None:
    record = session.get(IdempotencyRecord, (account_id, key))
    if record is None:
        return None
    if record.endpoint != endpoint or record.request_hash != digest:
        raise AppError(409, "IDEMPOTENCY_KEY_REUSED", "이미 다른 요청에 사용한 Idempotency-Key입니다. 새 키로 보내 주세요.")
    return record.response_status, record.response_body


def remember(session: Session, account_id: uuid.UUID, key: str, endpoint: str, digest: str, status: int, body) -> None:
    session.add(
        IdempotencyRecord(
            account_id=account_id,
            idempotency_key=key,
            endpoint=endpoint,
            request_hash=digest,
            response_status=status,
            response_body=jsonable_encoder(body),
        )
    )
