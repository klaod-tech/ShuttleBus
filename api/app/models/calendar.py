"""② 날짜 층 (05 소유). 기준 데이터를 실제 날짜에 적용한 결과."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    COVERAGE_STATUS,
    DAY_TYPE,
    EXCEPTION_TYPE,
    INFORMATION_STATUS,
    OPERATION_STATUS,
    POLICY,
    SCHEDULE_STATUS,
    VERIFICATION_STATUS,
    Base,
    enum,
)


class ScheduleException(Base):
    __tablename__ = "schedule_exceptions"
    __table_args__ = (
        # 같은 범위·같은 날짜의 중복 예외 금지. route_id가 null(전체)인 행끼리도 중복으로 본다
        UniqueConstraint("exception_date", "route_id", postgresql_nulls_not_distinct=True),
        CheckConstraint(
            "(exception_type = 'alternate_schedule') = (alternate_schedule_template_id IS NOT NULL)",
            name="alternate_template",
        ),
    )

    exception_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    exception_date: Mapped[date] = mapped_column(Date)
    # 범위: null이면 전체 노선, 값이 있으면 그 노선 전용
    route_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("routes.route_id"))
    exception_type: Mapped[str] = mapped_column(enum("exception_type", EXCEPTION_TYPE))
    alternate_schedule_template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schedule_templates.schedule_template_id")
    )
    source_reference: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)


class ScheduleRouteCoverage(Base):
    __tablename__ = "schedule_route_coverage"

    schedule_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schedule_templates.schedule_template_id"), primary_key=True
    )
    route_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("routes.route_id"), primary_key=True)
    coverage_status: Mapped[str] = mapped_column(enum("coverage_status", COVERAGE_STATUS))
    source_reference: Mapped[str] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_trip_count: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)


class ServiceCalendar(Base):
    __tablename__ = "service_calendar"

    service_date: Mapped[date] = mapped_column(Date, primary_key=True)
    route_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("routes.route_id"), primary_key=True)
    schedule_status: Mapped[str] = mapped_column(enum("schedule_status", SCHEDULE_STATUS))
    reason: Mapped[str | None] = mapped_column(Text)
    applied_schedule_template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schedule_templates.schedule_template_id")
    )
    actual_weekday: Mapped[str] = mapped_column(String(3))
    effective_service_weekday: Mapped[str | None] = mapped_column(String(3))
    effective_day_type: Mapped[str | None] = mapped_column(enum("effective_day_type", DAY_TYPE))
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScheduledTrip(Base):
    __tablename__ = "scheduled_trips"
    __table_args__ = (
        UniqueConstraint("trip_template_id", "service_date"),
        UniqueConstraint("source_row_key", "service_date"),
    )

    scheduled_trip_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    trip_template_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trip_templates.trip_template_id"))
    service_date: Mapped[date] = mapped_column(Date)
    route_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("route_versions.route_version_id"))
    # 회차와 방문이 서로를 가리키므로 방문 생성 후 채운다
    origin_trip_stop_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scheduled_trip_stops.trip_stop_id", use_alter=True)
    )
    operation_status: Mapped[str] = mapped_column(enum("operation_status", OPERATION_STATUS), default="scheduled")
    scheduled_vehicle_count: Mapped[int] = mapped_column(Integer)
    state_version: Mapped[int] = mapped_column(Integer, default=1)
    control_version: Mapped[int] = mapped_column(Integer, default=1)
    source_row_key: Mapped[str] = mapped_column(Text)


class ScheduledTripStop(Base):
    __tablename__ = "scheduled_trip_stops"
    __table_args__ = (
        UniqueConstraint("scheduled_trip_id", "route_stop_id"),
        UniqueConstraint("scheduled_trip_id", "stop_sequence"),
    )

    trip_stop_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scheduled_trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scheduled_trips.scheduled_trip_id"))
    route_stop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("route_stops.route_stop_id"))
    stop_sequence: Mapped[int] = mapped_column(Integer)
    scheduled_arrival_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_departure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_unspecified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    boarding_policy: Mapped[str] = mapped_column(enum("boarding_policy", POLICY))
    alighting_policy: Mapped[str] = mapped_column(enum("alighting_policy", POLICY))
    verification_status: Mapped[str] = mapped_column(enum("verification_status", VERIFICATION_STATUS))


class TripVehicle(Base):
    __tablename__ = "trip_vehicles"
    __table_args__ = (UniqueConstraint("scheduled_trip_id", "vehicle_slot"),)

    trip_vehicle_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scheduled_trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scheduled_trips.scheduled_trip_id"))
    vehicle_slot: Mapped[int] = mapped_column(Integer)
    # 차량 테이블과 관측 테이블은 해당 단계(P3)에서 생기며 그때 FK를 건다
    shuttle_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    operation_status: Mapped[str] = mapped_column(enum("operation_status", OPERATION_STATUS), default="scheduled")
    information_status: Mapped[str] = mapped_column(
        enum("information_status", INFORMATION_STATUS), default="timetable_only"
    )
    departure_observation_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
