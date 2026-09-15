"""Redis 상태 캐시 (12 5장). 확정 스냅샷의 복제본일 뿐이며 기준 데이터가 아니다.

- 더 새 state_version만 쓴다. 복원 작업의 과거 상태가 동시 확정의 새 상태를 덮지 않는다 (Lua 비교).
- 캐시가 비었거나 Redis가 없으면 DB 스냅샷을 읽는다. Redis 장애는 조회 실패가 아니다.
"""

import json
import logging
import uuid

from sqlalchemy.orm import Session

from app.models.realtime import TripStateSnapshot

log = logging.getLogger("app.realtime")

KEY = "shuttlebus:trip_state:{}"
TTL_SECONDS = 2 * 24 * 3600

# 저장된 버전보다 클 때만 쓴다
_SET_IF_NEWER = """
local current = redis.call('HGET', KEYS[1], 'state_version')
if current and tonumber(current) >= tonumber(ARGV[1]) then
  return 0
end
redis.call('HSET', KEYS[1], 'state_version', ARGV[1], 'payload', ARGV[2])
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""


class StateCache:
    def __init__(self, client):
        self.client = client
        self._script = client.register_script(_SET_IF_NEWER) if client is not None else None

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def put(self, trip_id: uuid.UUID | str, state_version: int, payload: dict) -> bool:
        if not self.enabled:
            return False
        try:
            return bool(self._script(keys=[KEY.format(trip_id)], args=[state_version, json.dumps(payload, ensure_ascii=False), TTL_SECONDS]))
        except Exception as exc:
            log.warning("캐시 쓰기 실패: %s", exc)
            return False

    def get(self, trip_id: uuid.UUID | str) -> tuple[int, dict] | None:
        if not self.enabled:
            return None
        try:
            raw = self.client.hgetall(KEY.format(trip_id))
        except Exception as exc:
            log.warning("캐시 읽기 실패: %s", exc)
            return None
        if not raw:
            return None
        version = raw.get(b"state_version") or raw.get("state_version")
        payload = raw.get(b"payload") or raw.get("payload")
        return int(version), json.loads(payload)

    def rebuild(self, session: Session, trip_id: uuid.UUID) -> tuple[int, dict] | None:
        """DB 확정 스냅샷을 그대로 복사한다. 새 버전·새 예측을 만들지 않는다 (FR-RT-08·09)."""
        snapshot = session.get(TripStateSnapshot, trip_id)
        if snapshot is None:
            return None
        self.put(trip_id, snapshot.state_version, snapshot.payload)
        return snapshot.state_version, snapshot.payload


_cache = StateCache(None)


def get_cache() -> StateCache:
    return _cache


def set_cache(cache: StateCache) -> None:
    global _cache
    _cache = cache


def connect_from_settings(redis_url: str | None) -> StateCache:
    if not redis_url:
        return StateCache(None)
    import redis

    return StateCache(redis.Redis.from_url(redis_url, socket_timeout=2, socket_connect_timeout=2))
