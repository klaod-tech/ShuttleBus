"""회차 공개 상태 확정 (12 4·10장, 08 6장 '만료를 정상 버전 변경으로 확정').

상태는 시간이 지나기만 해도 바뀐다(방문 upcoming→unknown, 관측 observed→stale, 도착 신선도).
그래서 '내용이 바뀌었으면 새 state_version으로 확정한다'를 한 함수로 모은다.

    commit_trip_state  — 회차 잠금을 가진 호출자가 부른다. 스냅샷과 내용이 다르면 버전·스냅샷·outbox 확정
    같은 내용이면 아무것도 쓰지 않는다 (FR-RT-09). 과거 버전으로 되돌리지 않는다.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendar.service import resolve_service_calendar
from app.candidates.classify import CandidateInput, classify
from app.models.calendar import ScheduledTrip
from app.models.realtime import TripStateSnapshot
from app.realtime.outbox import enqueue
from app.state.build import build_trip_state
from app.state.bundle import TripBundle, load_trip_bundles
from app.state.visits import evaluate_vehicle_visits

# 버전과 무관한 응답 메타데이터
VOLATILE_KEYS = ("server_time", "state_version")


@dataclass
class LiveState:
    trip_id: uuid.UUID
    route_id: uuid.UUID
    service_date: str
    payload: dict
    signature: list


def content(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if k not in VOLATILE_KEYS}


def candidate_signature(bundle: TripBundle, now: datetime) -> list:
    """후보 목록의 (a) 집합·(b) 분류를 결정하는 값만 모은다. 예상 시각 숫자(c)는 넣지 않는다 (12 2장, FR-RT-14).

    각 방문을 승차 방문으로 볼 때의 분류(제외·추천·확인 필요와 사유)와 하차 정책을 차량별로 적는다.
    하차 정책은 쌍마다 달라 분류와 따로 둔다.
    """
    rows = []
    for vehicle in bundle.vehicles:
        states = evaluate_vehicle_visits(bundle, vehicle, now)
        for visit, state in zip(bundle.visits, states, strict=True):
            ts = visit.trip_stop
            result = classify(
                CandidateInput(
                    trip_operation_status=bundle.trip.operation_status,
                    vehicle_operation_status=vehicle.operation_status,
                    boarding_policy=ts.boarding_policy,
                    alighting_policy="allowed",
                    boarding_visit_status=state.visit_status,
                    boarding_arrived_observed_at=state.arrived_observed_at,
                    boarding_estimated_event_at=state.estimated_event_at,
                    boarding_target_event_type=state.target_event_type,
                    boarding_unavailable_reason=state.unavailable_reason,
                    scheduled_departure_at=ts.scheduled_departure_at,
                    scheduled_arrival_at=ts.scheduled_arrival_at,
                    scheduled_unspecified_at=ts.scheduled_unspecified_at,
                ),
                now,
            )
            rows.append(
                [str(vehicle.trip_vehicle_id), str(ts.trip_stop_id), result.kind, result.priority_group, list(result.reasons), ts.alighting_policy]
            )
    return rows


def compute_live_states(session: Session, trip_ids: list[uuid.UUID], now: datetime) -> dict[uuid.UUID, LiveState]:
    """DB 확정 자료로 지금 시각의 공개 상태를 계산한다. 쓰지 않는다(달력 판정 저장 제외)."""
    bundles = load_trip_bundles(session, trip_ids)
    calendars = {}
    states = {}
    for trip_id, bundle in bundles.items():
        key = (bundle.route_id, bundle.trip.service_date)
        if key not in calendars:
            calendars[key] = resolve_service_calendar(session, bundle.route_id, bundle.trip.service_date)
        payload = jsonable_encoder(build_trip_state(bundle, calendars[key], now))
        states[trip_id] = LiveState(
            trip_id, bundle.route_id, str(bundle.trip.service_date), payload, candidate_signature(bundle, now)
        )
    return states


def is_current(snapshot: TripStateSnapshot | None, live: LiveState, trip: ScheduledTrip) -> bool:
    return (
        snapshot is not None
        and snapshot.state_version == trip.state_version
        and content(snapshot.payload) == content(live.payload)
    )


@dataclass
class CommitResult:
    changed: bool
    state_version: int
    payload: dict


def commit_trip_state(session: Session, trip: ScheduledTrip, now: datetime) -> CommitResult:
    """호출자는 회차 잠금을 가진다. 내용이 바뀌었을 때만 새 버전·스냅샷·outbox를 같은 트랜잭션에 넣는다."""
    session.flush()
    live = compute_live_states(session, [trip.scheduled_trip_id], now)[trip.scheduled_trip_id]
    snapshot = session.get(TripStateSnapshot, trip.scheduled_trip_id, with_for_update=True, populate_existing=True)
    if is_current(snapshot, live, trip):
        return CommitResult(False, trip.state_version, {**snapshot.payload, "state_version": snapshot.state_version})

    if snapshot is not None and trip.state_version <= snapshot.state_version:
        # 호출자가 올리지 않은 변경(시간 경과 등)이거나 버전이 뒤처진 경우. 과거 버전으로 되돌리지 않는다
        trip.state_version = snapshot.state_version + 1
    payload = {**live.payload, "state_version": trip.state_version, "control_version": trip.control_version}
    payload.pop("server_time", None)

    previous_signature = snapshot.candidate_signature if snapshot is not None else None
    if snapshot is None:
        snapshot = TripStateSnapshot(scheduled_trip_id=trip.scheduled_trip_id)
        session.add(snapshot)
    snapshot.state_version = trip.state_version
    snapshot.payload = payload
    snapshot.candidate_signature = live.signature
    snapshot.committed_at = now

    enqueue(session, "trip:state", f"trip:{trip.scheduled_trip_id}", payload, now)
    # 첫 스냅샷은 변경이 아니다. 이미 있던 분류가 바뀔 때만 노선 전체를 깨운다 (FR-RT-14·15·16)
    if previous_signature is not None and previous_signature != live.signature:
        enqueue(
            session,
            "candidates:changed",
            f"route:{live.route_id}",
            {"route_id": str(live.route_id), "service_date": live.service_date, "affected_trip_ids": [str(trip.scheduled_trip_id)]},
            now,
        )
    session.flush()
    return CommitResult(True, trip.state_version, payload)


def lock_and_commit(session: Session, trip_id: uuid.UUID, now: datetime) -> CommitResult:
    from app.observation.ingest import lock_trip

    trip = lock_trip(session, trip_id)
    return commit_trip_state(session, trip, now)


def refresh_states(session: Session, service_dates, now: datetime) -> int:
    """시간 경과로 내용이 바뀐 회차를 새 버전으로 확정한다 (08 9장 expire_predictions 역할). 회차마다 커밋한다."""
    committed = 0
    for service_date in service_dates:
        trip_ids = list(session.scalars(select(ScheduledTrip.scheduled_trip_id).where(ScheduledTrip.service_date == service_date)))
        for trip_id in stale_trip_ids(session, trip_ids, now):
            if lock_and_commit(session, trip_id, now).changed:
                committed += 1
            session.commit()
    session.commit()
    return committed


def stale_trip_ids(session: Session, trip_ids: list[uuid.UUID], now: datetime) -> list[uuid.UUID]:
    """스냅샷이 없거나 지금 계산한 내용과 다른 회차 (잠금 없이 판단, 확정은 잠금 뒤 다시 계산)."""
    if not trip_ids:
        return []
    live = compute_live_states(session, trip_ids, now)
    snapshots = {s.scheduled_trip_id: s for s in session.scalars(select(TripStateSnapshot).where(TripStateSnapshot.scheduled_trip_id.in_(trip_ids)))}
    trips = {t.scheduled_trip_id: t for t in session.scalars(select(ScheduledTrip).where(ScheduledTrip.scheduled_trip_id.in_(trip_ids)))}
    return [tid for tid, state in live.items() if not is_current(snapshots.get(tid), state, trips[tid])]
