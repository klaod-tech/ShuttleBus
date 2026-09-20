"""시각 규칙 (01 2장): UTC 저장, Asia/Seoul 판정. 서버 시간대에 의존하지 않는다."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


# 조회·저장을 허용하는 운행 날짜 범위. 날짜 계산 넘침과 익명 조회의 무한 행 생성을 막는다
MIN_SERVICE_DATE = date(2020, 1, 1)
MAX_SERVICE_DATE = date(2100, 12, 31)


def to_seoul(dt: datetime | None) -> datetime | None:
    """응답용 서울 시각. None은 그대로. (여러 모듈이 각자 _local을 두던 것을 2026-09-18에 한 곳으로 모았다)"""
    return dt.astimezone(SEOUL) if dt else None


def today_seoul(now: datetime | None = None) -> date:
    if now is None:
        from app.clock import get_now

        now = get_now()
    return now.astimezone(SEOUL).date()


def weekday_key(d: date) -> str:
    return WEEKDAYS[d.weekday()]


def combine_seoul(service_date: date, t: time, day_offset: int = 0) -> datetime:
    """시간표 TIME을 운행일과 결합한다. 자정 넘김은 day_offset으로만 표현한다."""
    local = datetime.combine(service_date + timedelta(days=day_offset), t, tzinfo=SEOUL)
    return local


def parse_hhmm(text: str) -> time:
    hour, minute = text.split(":")
    return time(int(hour), int(minute))
