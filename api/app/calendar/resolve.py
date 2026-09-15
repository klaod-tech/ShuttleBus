"""날짜별 운행 판정 (05 2장). 순수 함수 — DB는 service.py가 읽어 CalendarData로 넘긴다."""

import uuid
from dataclasses import dataclass, field
from datetime import date

from app.timeutil import weekday_key

DAY_TYPE_WEEKDAY = {"saturday": "sat", "sunday_holiday": "sun"}


@dataclass(frozen=True)
class TemplateInfo:
    schedule_template_id: uuid.UUID
    day_type: str
    effective_from: date
    effective_to: date
    data_status: str


@dataclass(frozen=True)
class ExceptionInfo:
    exception_date: date
    route_id: uuid.UUID | None
    exception_type: str
    alternate_schedule_template_id: uuid.UUID | None
    note: str | None


@dataclass(frozen=True)
class CoverageInfo:
    coverage_status: str
    expected_trip_count: int | None


@dataclass(frozen=True)
class TripSummary:
    trip_template_id: uuid.UUID
    excluded_weekdays: tuple[str, ...]
    vehicle_count_by_weekday: dict
    origin_verified: bool


@dataclass
class CalendarData:
    templates: list[TemplateInfo]
    exceptions: list[ExceptionInfo]
    coverage: dict[tuple[uuid.UUID, uuid.UUID], CoverageInfo]
    trips: dict[tuple[uuid.UUID, uuid.UUID], list[TripSummary]] = field(default_factory=dict)


@dataclass(frozen=True)
class Resolution:
    route_id: uuid.UUID
    service_date: date
    schedule_status: str
    reason: str | None
    applied_schedule_template_id: uuid.UUID | None
    actual_weekday: str
    effective_service_weekday: str | None
    effective_day_type: str | None


def day_type_for(d: date) -> str:
    wd = d.weekday()
    return "weekday" if wd < 5 else "saturday" if wd == 5 else "sunday_holiday"


def effective_service_weekday(actual: str, day_type: str) -> str:
    return actual if day_type == "weekday" else DAY_TYPE_WEEKDAY[day_type]


def vehicle_count(trip: TripSummary, weekday: str) -> int | None:
    """필요한 키가 없거나 양의 정수가 아니면 None — 0대나 기본값으로 대신하지 않는다."""
    value = trip.vehicle_count_by_weekday.get(weekday)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def running_trips(trips: list[TripSummary], weekday: str) -> list[TripSummary]:
    return [t for t in trips if weekday not in t.excluded_weekdays]


def resolve(data: CalendarData, route_id: uuid.UUID, d: date) -> Resolution:
    actual = weekday_key(d)

    def result(status, reason, template=None, day_type=None):
        return Resolution(
            route_id=route_id,
            service_date=d,
            schedule_status=status,
            reason=reason,
            applied_schedule_template_id=template.schedule_template_id if template else None,
            actual_weekday=actual,
            effective_service_weekday=effective_service_weekday(actual, day_type) if day_type else None,
            effective_day_type=day_type,
        )

    # 1. 학기 범위 — 등록된 템플릿 적용 기간의 합집합, 양 끝 포함
    if not data.templates:
        return result("out_of_period", "no_registered_schedule")
    period_start = min(t.effective_from for t in data.templates)
    period_end = max(t.effective_to for t in data.templates)
    if not period_start <= d <= period_end:
        return result("out_of_period", "outside_registered_period")

    # 2. 학교 운행 예외 — 노선 전용이 전체보다 우선
    todays = [e for e in data.exceptions if e.exception_date == d and e.route_id in (route_id, None)]
    exception = next((e for e in todays if e.route_id == route_id), None) or next(iter(todays), None)
    if exception and exception.exception_type == "no_service":
        return result("no_service", f"school_exception:{exception.note or ''}")

    # 3. 적용 템플릿 — 대체 지정은 참조 템플릿의 day_type 규칙으로 평가한다
    if exception and exception.exception_type == "alternate_schedule":
        template = next(
            (t for t in data.templates if t.schedule_template_id == exception.alternate_schedule_template_id), None
        )
        if template is None:
            return result("unknown", "alternate_template_missing")
        reason_prefix = f"alternate_schedule:{exception.note or ''}"
    else:
        day_type = day_type_for(d)
        candidates = [t for t in data.templates if t.day_type == day_type and t.effective_from <= d <= t.effective_to]
        if not candidates:
            return result("unknown", "template_not_found")
        template = candidates[0]
        reason_prefix = None

    day_type = template.day_type
    service_weekday = effective_service_weekday(actual, day_type)

    # 4. 템플릿 유효기간
    if not template.effective_from <= d <= template.effective_to:
        return result("unknown", "template_out_of_range", template, day_type)

    # 5. 템플릿 자료 상태
    if template.data_status != "available":
        return result("unknown", "template_data_not_available", template, day_type)

    # 6. 노선 자료 범위 — 빈 회차 목록 자체를 미운행 근거로 쓰지 않는다
    coverage = data.coverage.get((template.schedule_template_id, route_id))
    if coverage is None or coverage.coverage_status == "unknown":
        return result("unknown", "route_coverage_unknown", template, day_type)
    if coverage.coverage_status == "confirmed_no_service":
        return result("no_service", "route_coverage_no_service", template, day_type)

    trips = data.trips.get((template.schedule_template_id, route_id), [])
    if coverage.expected_trip_count is None or len(trips) != coverage.expected_trip_count:
        return result("unknown", "route_data_incomplete", template, day_type)
    for trip in running_trips(trips, service_weekday):
        if vehicle_count(trip, service_weekday) is None:
            return result("unknown", "vehicle_count_invalid", template, day_type)
        if not trip.origin_verified:
            return result("unknown", "origin_unverified", template, day_type)

    # 7.
    return result("available", reason_prefix, template, day_type)
