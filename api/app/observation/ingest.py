"""수동 관측 수집 (06) — 세션 시작·관측 저장·취소·수집 종료·시계 검증.

모든 변경은 회차 단위 잠금 아래 한 트랜잭션으로 확정한다 (01 3장 원자성).
처리 순서는 01 4장: 인증 → 멱등 키 → 기존 논리 관측 → 기대 버전 → 유효성 → 저장.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Principal
from app.config import settings
from app.errors import AppError, not_found
from app.models.calendar import ScheduledTrip, ScheduledTripStop, TripVehicle
from app.models.observation import ClockCheck, CollectionSession, LocationEvent, ObservationReview
from app.models.reference import RouteStop, Stop
from app.observation.rules import TRANSITION_RANK, EventView, progress_sequence


# ---------- 공통 ----------


def lock_trip(session: Session, trip_id: uuid.UUID) -> ScheduledTrip:
    trip = session.scalar(select(ScheduledTrip).where(ScheduledTrip.scheduled_trip_id == trip_id).with_for_update())
    if trip is None:
        raise not_found("회차")
    return trip


def _ownership_conflict(message: str = "다른 기기에서 수집 중입니다. 관리자 확인이 필요합니다.") -> AppError:
    return AppError(409, "SESSION_OWNERSHIP_CONFLICT", message)


def _check_owner(sess: CollectionSession, principal: Principal, writer_instance_id: uuid.UUID | None) -> None:
    if sess.collector_id != principal.account_id:
        raise _ownership_conflict("다른 입력자가 수집 중인 세션입니다. 관리자 확인이 필요합니다.")
    if writer_instance_id is not None and sess.writer_instance_id != writer_instance_id:
        raise _ownership_conflict()


def _check_input_version(sess: CollectionSession, expected: int) -> None:
    if sess.input_version != expected:
        raise AppError(
            409,
            "INPUT_VERSION_CONFLICT",
            "다른 입력이 먼저 반영되었습니다. 최신 상태를 불러온 뒤 다시 보내 주세요.",
            details={"current_input_version": sess.input_version},
        )


def trip_stops_by_id(session: Session, trip_id: uuid.UUID) -> dict[uuid.UUID, tuple[ScheduledTripStop, str]]:
    rows = session.execute(
        select(ScheduledTripStop, Stop.name)
        .join(RouteStop, RouteStop.route_stop_id == ScheduledTripStop.route_stop_id)
        .join(Stop, Stop.stop_id == RouteStop.stop_id)
        .where(ScheduledTripStop.scheduled_trip_id == trip_id)
    )
    return {ts.trip_stop_id: (ts, name) for ts, name in rows}


def vehicle_event_views(session: Session, trip_vehicle_id: uuid.UUID, seq_of: dict) -> tuple[list[LocationEvent], list[EventView]]:
    events = list(session.scalars(select(LocationEvent).where(LocationEvent.trip_vehicle_id == trip_vehicle_id)))
    views = [
        EventView(e.event_id, e.trip_stop_id, seq_of[e.trip_stop_id], e.event_type, e.occurred_at, e.time_confidence, e.validation_status)
        for e in events
    ]
    return events, views


def refresh_vehicle_information(session: Session, vehicle: TripVehicle) -> None:
    """저장 열은 공개 관측 보유 여부만 반영한다. 신선도(observed/stale)는 조회 시점에 계산한다."""
    has_valid = session.scalar(
        select(LocationEvent.event_id).where(
            LocationEvent.trip_vehicle_id == vehicle.trip_vehicle_id,
            LocationEvent.validation_status == "valid",
            LocationEvent.event_type != "skipped",
        ).limit(1)
    )
    vehicle.information_status = "observed" if has_valid else "timetable_only"


# ---------- 세션 시작 ----------


@dataclass
class StartResult:
    session: CollectionSession
    created: bool


def start_session(
    session: Session,
    principal: Principal,
    trip_vehicle_id: uuid.UUID,
    shuttle_id: uuid.UUID | None,
    collection_start_trip_stop_id: uuid.UUID | None,
    writer_instance_id: uuid.UUID | None,
    now: datetime,
) -> StartResult:
    vehicle = session.get(TripVehicle, trip_vehicle_id)
    if vehicle is None:
        raise not_found("차량 슬롯")
    lock_trip(session, vehicle.scheduled_trip_id)
    if collection_start_trip_stop_id is not None:
        start = session.get(ScheduledTripStop, collection_start_trip_stop_id)
        if start is None or start.scheduled_trip_id != vehicle.scheduled_trip_id:
            raise not_found("같은 회차의 시작 방문")

    existing = session.scalar(
        select(CollectionSession).where(
            CollectionSession.trip_vehicle_id == trip_vehicle_id,
            CollectionSession.producer_type == "manual",
            CollectionSession.ended_at.is_(None),
        )
    )
    if existing is not None:
        # 같은 입력자·같은 기기의 재시작은 기존 세션 반환. 다른 기기·다른 입력자는 자동 인계하지 않는다 (06 1장)
        if existing.collector_id == principal.account_id and writer_instance_id == existing.writer_instance_id:
            return StartResult(existing, False)
        if existing.collector_id == principal.account_id:
            raise _ownership_conflict()
        raise _ownership_conflict("다른 입력자가 이 차량을 수집 중입니다. 관리자 확인이 필요합니다.")

    created = CollectionSession(
        trip_vehicle_id=trip_vehicle_id,
        shuttle_id=shuttle_id,
        collector_id=principal.account_id,
        producer_type="manual",
        comparison_policy="manual_only",
        collection_start_trip_stop_id=collection_start_trip_stop_id,
        collection_status="collecting",
        input_version=1,
        writer_instance_id=uuid.uuid4(),
        started_at=now,
    )
    if shuttle_id is not None and vehicle.shuttle_id is None:
        vehicle.shuttle_id = shuttle_id
    session.add(created)
    session.flush()
    return StartResult(created, True)


# ---------- 관측 저장 ----------


@dataclass
class ObservationInput:
    trip_stop_id: uuid.UUID
    event_type: str
    occurred_at: datetime
    client_event_id: str
    client_sequence: int
    expected_input_version: int
    confirm_skip: bool
    writer_instance_id: uuid.UUID
    clock_check_id: uuid.UUID | None


@dataclass
class ObservationResult:
    event: LocationEvent
    skipped: list[LocationEvent] = field(default_factory=list)
    superseded: list[LocationEvent] = field(default_factory=list)
    replayed: bool = False
    session: CollectionSession | None = None
    trip: ScheduledTrip | None = None


def _immutable(e: LocationEvent) -> tuple:
    return (e.trip_stop_id, e.event_type, e.occurred_at, e.client_sequence)


def submit_observation(
    session: Session, principal: Principal, session_id: uuid.UUID, data: ObservationInput, now: datetime
) -> ObservationResult:
    sess = session.get(CollectionSession, session_id)
    if sess is None or sess.producer_type != "manual":
        raise not_found("수집 세션")
    vehicle = session.get(TripVehicle, sess.trip_vehicle_id)
    trip = lock_trip(session, vehicle.scheduled_trip_id)
    session.refresh(sess)

    # 3~4. 이미 확정된 논리 관측 — 기대 버전 검증보다 먼저 (01 4장)
    existing = session.scalar(
        select(LocationEvent).where(
            LocationEvent.collection_session_id == session_id, LocationEvent.client_event_id == data.client_event_id
        )
    )
    if existing is not None:
        if _immutable(existing) != (data.trip_stop_id, data.event_type, data.occurred_at, data.client_sequence):
            raise AppError(409, "EVENT_ID_REUSED", "같은 기록 ID에 다른 내용이 들어왔습니다. 앱을 새로고침해 주세요.")
        return ObservationResult(existing, replayed=True, session=sess, trip=trip)

    _check_owner(sess, principal, data.writer_instance_id)
    stops = trip_stops_by_id(session, trip.scheduled_trip_id)
    if data.trip_stop_id not in stops:
        raise not_found("이 회차의 방문")
    _check_input_version(sess, data.expected_input_version)

    seq_taken = session.scalar(
        select(LocationEvent.event_id).where(
            LocationEvent.collection_session_id == session_id, LocationEvent.client_sequence == data.client_sequence
        )
    )
    if seq_taken is not None:
        raise AppError(409, "EVENT_ID_REUSED", "이미 사용한 기록 순번입니다. 앱을 새로고침해 주세요.")

    seq_of = {tid: ts.stop_sequence for tid, (ts, _) in stops.items()}
    target_seq = seq_of[data.trip_stop_id]
    events, views = vehicle_event_views(session, vehicle.trip_vehicle_id, seq_of)
    last_seq = progress_sequence(views)
    received_at = now
    review: list[str] = []
    skip_ids: list[uuid.UUID] = []

    start_seq = seq_of[sess.collection_start_trip_stop_id] if sess.collection_start_trip_stop_id else None

    # ---- 거절 검사: 순서 (02 6장) ----
    if last_seq is not None and target_seq < last_seq:
        window = settings.realtime_input_window_seconds
        if window is None:
            review.append("order_backward_window_undefined")
        elif (received_at - data.occurred_at).total_seconds() <= window:
            raise AppError(409, "EVENT_ORDER_CONFLICT", "이미 지난 정거장입니다. 잘못 입력했다면 취소를 사용해 주세요.")
        else:
            pass  # 지연 보충: 해당 방문 상태만 정정, 진행 위치는 max라 뒤로 가지 않는다
    elif start_seq is not None and target_seq < start_seq:
        review.append("before_collection_start")
    else:
        same_visit = [
            e for e in events if e.trip_stop_id == data.trip_stop_id and e.validation_status == "valid" and e.event_type != "skipped"
        ]
        types = {e.event_type: e for e in same_visit}
        if data.event_type in types:
            review.append("duplicate_observation")
        elif data.event_type == "departed" and "arrived" in types and types["arrived"].occurred_at > data.occurred_at:
            review.append("departed_before_arrived")
        elif data.event_type == "passed" and "arrived" in types or data.event_type == "arrived" and ({"passed", "departed"} & set(types)):
            review.append("conflicting_event_types")

        if not review:
            skip_ids = gap_visits(trip, sess, stops, events, last_seq, target_seq)
            if len(skip_ids) > settings.max_skip_stops and not data.confirm_skip:
                raise AppError(
                    409,
                    "SKIP_LIMIT_EXCEEDED",
                    f"정거장 {len(skip_ids)}곳을 건너뛰게 됩니다. 확인 후 다시 보내 주세요.",
                    details={
                        "skipped_visits": [
                            {"trip_stop_id": str(t), "stop_name": stops[t][1], "stop_sequence": seq_of[t]} for t in skip_ids
                        ]
                    },
                )

    # ---- 보관 판정: 수집 기간 → 시계 → 보관 기간 ----
    # 열린 세션의 끝은 수신 시각이다. 서버 시각보다 앞선 발생 시각은 시계 허용 오차까지만 인정한다
    period_end = sess.ended_at if sess.ended_at is not None else received_at + timedelta(seconds=settings.clock_skew_tolerance_seconds or 0)
    if data.occurred_at < sess.started_at or data.occurred_at > period_end:
        review.append("outside_collection_period")
    clock_reason = _clock_reason(session, sess, data)
    if clock_reason:
        review.append(clock_reason)
    retention = settings.pending_input_retention_hours
    if retention is None:
        review.append("retention_undefined")
    elif received_at - data.occurred_at > timedelta(hours=retention):
        review.append("retention_exceeded")

    status = "needs_review" if review else "valid"
    event = LocationEvent(
        event_id=uuid.uuid4(),
        collection_session_id=session_id,
        trip_vehicle_id=vehicle.trip_vehicle_id,
        trip_stop_id=data.trip_stop_id,
        event_type=data.event_type,
        occurred_at=data.occurred_at,
        time_confidence="observed",
        received_at=received_at,
        source="manual",
        client_event_id=data.client_event_id,
        client_sequence=data.client_sequence,
        clock_check_id=data.clock_check_id,
        review_reason=",".join(review) or None,
        validation_status=status,
    )
    session.add(event)
    session.flush()

    result = ObservationResult(event, session=sess, trip=trip)
    if status == "valid":
        result.superseded, result.skipped = make_public(
            session, event, sess, trip, vehicle, stops, events, skip_ids, now, f"system:{event.event_id}"
        )
        trip.state_version += 1

    sess.input_version += 1
    session.flush()
    return result


def _origin_seq(trip: ScheduledTrip, stops: dict) -> int:
    return stops[trip.origin_trip_stop_id][0].stop_sequence


def gap_visits(
    trip: ScheduledTrip, sess: CollectionSession, stops: dict, events: list[LocationEvent], last_seq: int | None, target_seq: int
) -> list[uuid.UUID]:
    """마지막 진행 지점(없으면 수집 시작·기점 직전)과 목표 사이에서 관측이 없는 방문 — 자동 누락 대상 (02 7장)."""
    if last_seq is not None and target_seq <= last_seq:
        return []
    seq_of = {tid: ts.stop_sequence for tid, (ts, _) in stops.items()}
    if last_seq is not None:
        base = last_seq
    elif sess.collection_start_trip_stop_id is not None:
        base = seq_of[sess.collection_start_trip_stop_id] - 1
    else:
        base = _origin_seq(trip, stops) - 1
    observed = {e.trip_stop_id for e in events if e.validation_status == "valid"}
    return [tid for tid, seq in sorted(seq_of.items(), key=lambda kv: kv[1]) if base < seq < target_seq and tid not in observed]


def make_public(
    session: Session,
    event: LocationEvent,
    sess: CollectionSession,
    trip: ScheduledTrip,
    vehicle: TripVehicle,
    stops: dict,
    events: list[LocationEvent],
    skip_ids: list[uuid.UUID],
    now: datetime,
    skip_prefix: str,
) -> tuple[list[LocationEvent], list[LocationEvent]]:
    """유효가 된 관측의 파생 효과. 입력·검토 승인·복구가 같은 경로를 쓴다.

    지연 실측의 누락 대체 (02 7장) → 사이 방문 자동 누락 → 기점 출발 연결 → 정보 상태 → 종점 자동 완료 (13 3장).
    state_version·input_version·control_version 증가는 호출자가 정한다.
    """
    from app.operations.completion import auto_complete_on_terminal

    superseded: list[LocationEvent] = []
    for e in events:
        if e.event_id != event.event_id and e.trip_stop_id == event.trip_stop_id and e.event_type == "skipped" and e.validation_status == "valid":
            e.validation_status, e.cancelled_at, e.cancel_reason = "cancelled", now, "superseded_by_observation"
            superseded.append(e)
    session.flush()
    skipped: list[LocationEvent] = []
    for tid in skip_ids:
        row = LocationEvent(
            event_id=uuid.uuid4(),
            collection_session_id=sess.collection_session_id,
            trip_vehicle_id=vehicle.trip_vehicle_id,
            trip_stop_id=tid,
            event_type="skipped",
            occurred_at=None,
            time_confidence="inferred",
            received_at=now,
            source="system",
            client_event_id=f"{skip_prefix}:{tid}",
            client_sequence=None,
            validation_status="valid",
            parent_event_id=event.event_id,
        )
        session.add(row)
        skipped.append(row)
    if event.event_type == "departed" and event.trip_stop_id == trip.origin_trip_stop_id:
        vehicle.departure_observation_event_id = event.event_id
    session.flush()
    refresh_vehicle_information(session, vehicle)
    auto_complete_on_terminal(session, trip, vehicle, event, stops, now)
    return superseded, skipped


def _clock_reason(session: Session, sess: CollectionSession, data: ObservationInput) -> str | None:
    """검증된 시계 근거가 없거나 설정이 미정이면 검토 대기 (02 12장)."""
    if data.clock_check_id is None:
        return "clock_unverified"
    check = session.get(ClockCheck, data.clock_check_id)
    if check is None or check.collection_session_id != sess.collection_session_id:
        raise AppError(422, "CLOCK_EVIDENCE_INVALID", "시계 확인 기록이 이 수집 세션에 속하지 않습니다.")
    tolerance, valid_seconds = settings.clock_skew_tolerance_seconds, settings.clock_check_valid_seconds
    if tolerance is None or valid_seconds is None or check.checked_at is None:
        return "clock_unverified"
    if abs(check.estimated_offset_seconds) + check.uncertainty_seconds > tolerance:
        return "clock_skew_exceeded"
    window = timedelta(seconds=valid_seconds)
    if not (check.checked_at - window <= data.occurred_at <= check.checked_at + window):
        return "clock_check_out_of_range"
    return None


# ---------- 취소 ----------


@dataclass
class CancelResult:
    event: LocationEvent
    cascaded: list[LocationEvent]
    session: CollectionSession
    trip: ScheduledTrip


def cancel_observation(
    session: Session, principal: Principal, event_id: uuid.UUID, reason: str, expected_input_version: int, now: datetime
) -> CancelResult:
    event = session.get(LocationEvent, event_id)
    if event is None:
        raise not_found("관측 기록")
    sess = session.get(CollectionSession, event.collection_session_id)
    vehicle = session.get(TripVehicle, event.trip_vehicle_id)
    trip = lock_trip(session, vehicle.scheduled_trip_id)
    session.refresh(event)
    session.refresh(sess)

    # 관리자는 대체 관측 정리 등을 위해 다른 입력자의 기록도 취소할 수 있다 (13 15장)
    if principal.role != "admin":
        _check_owner(sess, principal, None)
    if event.source == "system":
        raise AppError(422, "VALIDATION_ERROR", "자동으로 만든 누락 기록은 직접 취소할 수 없습니다. 근거 기록을 취소해 주세요.")
    _check_input_version(sess, expected_input_version)
    if event.validation_status == "cancelled":
        raise AppError(409, "EVENT_ALREADY_CANCELLED", "이미 취소된 기록입니다. 되돌리려면 관리자 복구가 필요합니다.")

    was_public = event.validation_status == "valid"
    cascaded: list[LocationEvent] = []
    _cancel(session, event, reason, principal, now, sess.input_version, trip.control_version)
    for child in session.scalars(
        select(LocationEvent).where(LocationEvent.parent_event_id == event.event_id, LocationEvent.validation_status == "valid")
    ):
        _cancel(session, child, "parent_cancelled", principal, now, sess.input_version, trip.control_version)
        cascaded.append(child)

    if vehicle.departure_observation_event_id == event.event_id:
        vehicle.departure_observation_event_id = None
    session.flush()
    refresh_vehicle_information(session, vehicle)
    sess.input_version += 1
    if was_public:
        trip.state_version += 1
    session.flush()
    return CancelResult(event, cascaded, sess, trip)


def _cancel(session, event, reason, principal, now, input_version, control_version):
    session.add(
        ObservationReview(
            event_id=event.event_id,
            decision="cancel",
            previous_validation_status=event.validation_status,
            reason=reason,
            reviewed_by=principal.account_id,
            reviewed_at=now,
            input_version=input_version,
            control_version=control_version,
        )
    )
    event.validation_status = "cancelled"
    event.cancelled_at = now
    # 09 무효화 reason과 같은 이름 (02 9장)
    event.cancel_reason = "observation_cancelled"


# ---------- 수집 종료 ----------


def end_session(
    session: Session, principal: Principal, session_id: uuid.UUID, ended_at: datetime, expected_input_version: int, now: datetime
) -> CollectionSession:
    sess = session.get(CollectionSession, session_id)
    if sess is None or sess.producer_type != "manual":
        raise not_found("수집 세션")
    vehicle = session.get(TripVehicle, sess.trip_vehicle_id)
    lock_trip(session, vehicle.scheduled_trip_id)
    session.refresh(sess)
    _check_owner(sess, principal, None)
    _check_input_version(sess, expected_input_version)
    if sess.ended_at is not None:
        raise AppError(409, "INPUT_VERSION_CONFLICT", "이미 종료된 수집입니다.", details={"current_input_version": sess.input_version})
    if ended_at < sess.started_at or ended_at > now:
        raise AppError(422, "VALIDATION_ERROR", "종료 시각은 수집 시작 이후, 현재 시각 이전이어야 합니다.")
    # 수집 종료는 운행 완료가 아니다 (06 1장) — operation_status는 건드리지 않는다
    sess.ended_at = ended_at
    sess.collection_status = "ended"
    sess.input_version += 1
    session.flush()
    return sess


# ---------- 시계 검증 ----------


def begin_clock_check(
    session: Session, principal: Principal, session_id: uuid.UUID, device_sent_at: datetime, now: datetime
) -> ClockCheck:
    sess = session.get(CollectionSession, session_id)
    if sess is None:
        raise not_found("수집 세션")
    _check_owner(sess, principal, None)
    check = ClockCheck(
        collection_session_id=session_id,
        device_sent_at=device_sent_at,
        server_received_at=now,
        server_responded_at=now,
    )
    session.add(check)
    session.flush()
    return check


def complete_clock_check(
    session: Session, principal: Principal, clock_check_id: uuid.UUID, device_received_at: datetime, now: datetime
) -> ClockCheck:
    """NTP 방식 네 시각: t0 단말 송신, t1 서버 수신, t2 서버 응답, t3 단말 수신.

    단말 시계 − 서버 시계 = ((t0 − t1) + (t3 − t2)) / 2, 불확실성 = 왕복 지연 / 2.
    서버가 자기 시각 둘을 보관하므로 단말이 보고한 값만으로 검증되지 않는다 (02 12장).
    """
    check = session.get(ClockCheck, clock_check_id)
    if check is None:
        raise not_found("시계 확인 기록")
    sess = session.get(CollectionSession, check.collection_session_id)
    _check_owner(sess, principal, None)
    if check.checked_at is not None:
        return check
    t0, t1, t2, t3 = check.device_sent_at, check.server_received_at, check.server_responded_at, device_received_at
    delay = (t3 - t0).total_seconds() - (t2 - t1).total_seconds()
    if delay < 0:
        raise AppError(422, "CLOCK_EVIDENCE_INVALID", "시계 확인 시각의 순서가 맞지 않습니다.")
    check.device_received_at = t3
    check.estimated_offset_seconds = ((t0 - t1).total_seconds() + (t3 - t2).total_seconds()) / 2
    check.uncertainty_seconds = delay / 2
    check.checked_at = now
    if settings.clock_check_valid_seconds is not None:
        check.valid_until = now + timedelta(seconds=settings.clock_check_valid_seconds)
    session.flush()
    return check
