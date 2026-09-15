"""관측 진행 규칙 (02 3·8장). 저장·상태 계산이 같은 규칙을 쓴다."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

# 같은 방문 안의 사건 전이 순서. arrived → departed. passed는 비정차 통과
TRANSITION_RANK = {"arrived": 0, "departed": 1, "passed": 1}
PROGRESS_TYPES = {"arrived", "departed", "passed"}


@dataclass(frozen=True)
class EventView:
    event_id: object
    trip_stop_id: object
    stop_sequence: int
    event_type: str
    occurred_at: datetime | None
    time_confidence: str
    validation_status: str


def valid_progress(events: Iterable[EventView]) -> list[EventView]:
    """마지막 확인 지점을 전진시키는 유효 관측. skipped는 전진시키지 않는다."""
    return [e for e in events if e.validation_status == "valid" and e.event_type in PROGRESS_TYPES and e.occurred_at]


def progress_sequence(events: Iterable[EventView]) -> int | None:
    progress = valid_progress(events)
    return max((e.stop_sequence for e in progress), default=None)


def last_observation(events: Iterable[EventView]) -> EventView | None:
    """방문 순서 → 방문 안 전이 순서 → 발생 시각 순으로 가장 앞선 관측 (08 4장 기준 후보 순서)."""
    progress = valid_progress(events)
    if not progress:
        return None
    return max(progress, key=lambda e: (e.stop_sequence, TRANSITION_RANK[e.event_type], e.occurred_at, str(e.event_id)))
