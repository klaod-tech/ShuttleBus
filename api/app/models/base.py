from sqlalchemy import Enum, MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def enum(name: str, values: tuple[str, ...]) -> Enum:
    """상태값은 VARCHAR + CHECK로 둔다. 네이티브 enum은 값 추가 마이그레이션이 번거롭다."""
    return Enum(*values, name=name, native_enum=False, create_constraint=True, length=32, validate_strings=True)


# 01 6장 상태값 인덱스
VERIFICATION_STATUS = ("verified", "needs_interpretation", "unverified")
POLICY = ("allowed", "not_allowed", "unknown")
PATH_SOURCE = ("recorded_track", "operator_provided", "manual_trace")
DAY_TYPE = ("weekday", "saturday", "sunday_holiday")
DATA_STATUS = ("draft", "available", "missing")
SCHEDULE_SOURCE = ("school_pdf", "operator_entry", "unknown")
PUNCTUALITY = ("user_asserted_on_time", "not_assumed")
SCHEDULED_EVENT_TYPE = ("arrival", "departure", "unspecified")
SCHEDULE_STATUS = ("available", "no_service", "unknown", "out_of_period")
EXCEPTION_TYPE = ("no_service", "alternate_schedule")
COVERAGE_STATUS = ("confirmed_service", "confirmed_no_service", "unknown")
OPERATION_STATUS = ("scheduled", "scheduled_running", "completed", "cancelled")
INFORMATION_STATUS = ("timetable_only", "observed", "stale", "unavailable")
