from datetime import datetime

from app.timeutil import SEOUL


def get_now() -> datetime:
    """서버 시각. 시험에서 의존성 교체로 고정한다."""
    return datetime.now(tz=SEOUL)
