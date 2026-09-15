"""탑승 후보 분류·정렬 시각 (11 3·4장). 순수 함수 — DB 없이 시험한다."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

ARRIVED_FRESHNESS_SECONDS = 180  # 시험값 (11 3장)

# 실시간 근거를 무효로 만드는 사유. 이때는 미래 공시값이 있어도 정상 추천으로 되살리지 않는다 (11 3장 7)
CONTRARY_REASONS = {"stale_observation", "prediction_expired", "position_unverified", "awaiting_departure"}
PASSED_STATUSES = {"departed", "passed", "passed_inferred"}
EVENT_OF_PUBLISHED = {"departure": "departed", "arrival": "arrived"}


@dataclass(frozen=True)
class CandidateInput:
    trip_operation_status: str
    vehicle_operation_status: str
    boarding_policy: str
    alighting_policy: str
    boarding_visit_status: str
    # 승차 방문의 유효 arrived 관측 시각 (P3부터 채워진다)
    boarding_arrived_observed_at: datetime | None
    boarding_estimated_event_at: datetime | None
    boarding_target_event_type: str | None
    boarding_unavailable_reason: str | None
    scheduled_departure_at: datetime | None
    scheduled_arrival_at: datetime | None
    scheduled_unspecified_at: datetime | None


@dataclass(frozen=True)
class Classification:
    kind: str  # excluded / candidate / unverified
    priority_group: int | None = None
    sort_at: datetime | None = None
    sort_basis_event_type: str | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)
    excluded_because: str | None = None


def _published(c: CandidateInput) -> tuple[datetime, str] | None:
    """의미가 확인된 공시 시각. 같은 출처 안에서 출발 → 도착 순 (11 4장). unspecified는 쓰지 않는다."""
    if c.scheduled_departure_at:
        return c.scheduled_departure_at, "departed"
    if c.scheduled_arrival_at:
        return c.scheduled_arrival_at, "arrived"
    return None


def classify(c: CandidateInput, now: datetime, freshness_seconds: int = ARRIVED_FRESHNESS_SECONDS) -> Classification:
    # 2. 완료·취소
    if c.trip_operation_status in ("completed", "cancelled") or c.vehicle_operation_status in ("completed", "cancelled"):
        return Classification("excluded", excluded_because="operation_ended")

    # 3. 승하차 정책
    if c.boarding_policy == "not_allowed" or c.alighting_policy == "not_allowed":
        return Classification("excluded", excluded_because="policy_not_allowed")
    reasons: list[str] = []
    if c.boarding_policy == "unknown":
        reasons.append("boarding_policy_unknown")
    if c.alighting_policy == "unknown":
        reasons.append("alighting_policy_unknown")

    # 4. 이미 떠난 방문. 예상 시각 경과만으로는 여기에 오지 않는다
    if c.boarding_visit_status in PASSED_STATUSES:
        return Classification("excluded", excluded_because="boarding_visit_passed")

    def result(sort_at, basis, extra=(), group=None):
        all_reasons = tuple(reasons) + tuple(extra)
        if all_reasons:
            return Classification("unverified", None, sort_at, basis, all_reasons)
        return Classification("candidate", group, sort_at, basis, ())

    # 5. 도착 확인 — 신선하면 group 0, 도착 관측 시각으로 정렬 (예상 출발이 있어도)
    if c.boarding_visit_status == "arrived" and c.boarding_arrived_observed_at:
        age = now - c.boarding_arrived_observed_at
        if age <= timedelta(seconds=freshness_seconds):
            return result(c.boarding_arrived_observed_at, "arrived", group=0)
        return result(c.boarding_arrived_observed_at, "arrived", ("arrival_observation_stale",))

    # 6. 유효 미래 예측
    if c.boarding_estimated_event_at and c.boarding_estimated_event_at >= now:
        return result(c.boarding_estimated_event_at, c.boarding_target_event_type, group=1)

    published = _published(c)

    # 7. 실시간 근거 무효 — 공시값은 참고 정렬에만
    if c.boarding_unavailable_reason in CONTRARY_REASONS:
        sort_at, basis = published if published else (None, None)
        return result(sort_at, basis, (c.boarding_unavailable_reason,))

    # 6. 시간표 후보
    if published:
        sort_at, basis = published
        if sort_at >= now:
            return result(sort_at, basis, group=1)
        # 지난 공시 시각은 참고값. 곧 도착으로 바꾸지 않는다 (11 4장)
        return result(sort_at, basis, ("scheduled_time_passed",))
    if c.scheduled_unspecified_at:
        return result(None, None, ("scheduled_event_type_unspecified",))
    return result(None, None, ("no_scheduled_time",))


def candidate_sort_key(item) -> tuple:
    return (
        item["priority_group"], item["sort_at"], item["trip_no"], item["vehicle_slot"],
        item["boarding_stop_sequence"], item["alighting_stop_sequence"],
        str(item["trip_vehicle_id"]), str(item["boarding_trip_stop_id"]), str(item["alighting_trip_stop_id"]),
    )


def unverified_sort_key(item) -> tuple:
    sort_at = item["sort_at"]
    return (
        sort_at is None, sort_at.timestamp() if sort_at else 0.0, item["trip_no"], item["vehicle_slot"],
        item["boarding_stop_sequence"], item["alighting_stop_sequence"],
        str(item["trip_vehicle_id"]), str(item["boarding_trip_stop_id"]), str(item["alighting_trip_stop_id"]),
    )
