"""서버 시각의 단일 출처. API 의존성·배치·달력 판정이 모두 여기서 읽는다.

시험은 set_fixed_now로 고정한다. 벽시계를 직접 읽는 코드가 섞이면 '오늘'과 '지금'이 어긋난다
(예: 과거 날짜 판정 보존이 실제 날짜로, 상태 계산은 고정 시각으로 돌아가는 문제).
"""

from datetime import datetime

from app.timeutil import SEOUL

_fixed: datetime | None = None


def get_now() -> datetime:
    return _fixed if _fixed is not None else datetime.now(tz=SEOUL)


def set_fixed_now(moment: datetime | None) -> None:
    global _fixed
    _fixed = moment
