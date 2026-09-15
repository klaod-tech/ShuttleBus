"""⓪ 조사 · ① 기준 층 (04 소유). 날짜와 무관하다."""

import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    ARRAY,
    Boolean,
    Date,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    DATA_STATUS,
    DAY_TYPE,
    PATH_SOURCE,
    POLICY,
    PUNCTUALITY,
    SCHEDULE_SOURCE,
    SCHEDULED_EVENT_TYPE,
    VERIFICATION_STATUS,
    Base,
    enum,
)

# ---------- ① 정거장·노선 ----------


class Stop(Base):
    __tablename__ = "stops"

    stop_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, unique=True)
    latitude: Mapped[float | None] = mapped_column(Double)
    longitude: Mapped[float | None] = mapped_column(Double)
    geofence_radius_m: Mapped[int | None] = mapped_column(Integer)
    verification_status: Mapped[str] = mapped_column(enum("verification_status", VERIFICATION_STATUS))


class Route(Base):
    __tablename__ = "routes"

    route_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, unique=True)
    short_name: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class RoutePattern(Base):
    __tablename__ = "route_patterns"
    __table_args__ = (UniqueConstraint("route_id", "pattern_code"),)

    route_pattern_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    route_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("routes.route_id"))
    pattern_code: Mapped[str] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(enum("verification_status", VERIFICATION_STATUS))


class RouteVersion(Base):
    __tablename__ = "route_versions"
    __table_args__ = (UniqueConstraint("route_pattern_id", "version_no"),)

    route_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    route_pattern_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("route_patterns.route_pattern_id"))
    version_no: Mapped[int] = mapped_column(Integer)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)


class RouteStop(Base):
    __tablename__ = "route_stops"
    __table_args__ = (UniqueConstraint("route_version_id", "stop_sequence"),)

    route_stop_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    route_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("route_versions.route_version_id"))
    stop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stops.stop_id"))
    stop_sequence: Mapped[int] = mapped_column(Integer)
    is_origin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_terminal: Mapped[bool] = mapped_column(Boolean, default=False)
    boarding_policy: Mapped[str] = mapped_column(enum("boarding_policy", POLICY))
    alighting_policy: Mapped[str] = mapped_column(enum("alighting_policy", POLICY))
    note: Mapped[str | None] = mapped_column(Text)


class RoutePathPoint(Base):
    __tablename__ = "route_path_points"

    route_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("route_versions.route_version_id"), primary_key=True
    )
    path_seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    latitude: Mapped[float] = mapped_column(Double)
    longitude: Mapped[float] = mapped_column(Double)
    path_source: Mapped[str] = mapped_column(enum("path_source", PATH_SOURCE))
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RouteStopSegment(Base):
    __tablename__ = "route_stop_segments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["route_version_id", "path_from_seq"],
            ["route_path_points.route_version_id", "route_path_points.path_seq"],
        ),
        ForeignKeyConstraint(
            ["route_version_id", "path_to_seq"],
            ["route_path_points.route_version_id", "route_path_points.path_seq"],
        ),
    )

    route_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("route_versions.route_version_id"), primary_key=True
    )
    from_route_stop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("route_stops.route_stop_id"), primary_key=True)
    to_route_stop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("route_stops.route_stop_id"), primary_key=True)
    path_from_seq: Mapped[int] = mapped_column(Integer)
    path_to_seq: Mapped[int] = mapped_column(Integer)
    distance_m: Mapped[float | None] = mapped_column(Double)
    path_source: Mapped[str] = mapped_column(enum("path_source", PATH_SOURCE))
    verification_status: Mapped[str] = mapped_column(enum("verification_status", VERIFICATION_STATUS))


class SourceStopLabel(Base):
    """원문 이름과 확정 물리 지점의 잠정 매핑 (04 13장)."""

    __tablename__ = "source_stop_labels"

    source_reference: Mapped[str] = mapped_column(Text, primary_key=True)
    raw_name: Mapped[str] = mapped_column(Text, primary_key=True)
    provisional_stop_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stops.stop_id"))
    resolved_stop_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stops.stop_id"))
    verification_status: Mapped[str] = mapped_column(enum("verification_status", VERIFICATION_STATUS))
    note: Mapped[str | None] = mapped_column(Text)


# ---------- ⓪ 조사 ----------


class SurveyTrack(Base):
    __tablename__ = "survey_tracks"

    survey_track_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    route_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("route_versions.route_version_id"))
    recorded_on: Mapped[date | None] = mapped_column(Date)
    device_label: Mapped[str | None] = mapped_column(Text)
    gpx_version: Mapped[str | None] = mapped_column(Text)
    point_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    note: Mapped[str | None] = mapped_column(Text)
    source_file_hash: Mapped[str] = mapped_column(Text, unique=True)
    source_file_ref: Mapped[str | None] = mapped_column(Text)
    app_version: Mapped[str | None] = mapped_column(Text)
    export_format: Mapped[str | None] = mapped_column(Text)
    recording_settings: Mapped[dict | None] = mapped_column(JSONB)


class SurveyTrackPoint(Base):
    __tablename__ = "survey_track_points"

    survey_track_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("survey_tracks.survey_track_id"), primary_key=True)
    point_seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latitude: Mapped[float] = mapped_column(Double)
    longitude: Mapped[float] = mapped_column(Double)
    elevation_m: Mapped[float | None] = mapped_column(Double)
    speed_mps: Mapped[float | None] = mapped_column(Double)
    bearing_deg: Mapped[float | None] = mapped_column(Double)
    sat_count: Mapped[int | None] = mapped_column(Integer)
    hdop: Mapped[float | None] = mapped_column(Double)
    accuracy_m: Mapped[float | None] = mapped_column(Double)
    raw_extensions: Mapped[str | None] = mapped_column(Text)


class SurveyAnnotation(Base):
    __tablename__ = "survey_annotations"
    __table_args__ = (
        UniqueConstraint("survey_track_id", "annotation_seq"),
        ForeignKeyConstraint(
            ["survey_track_id", "linked_point_seq"],
            ["survey_track_points.survey_track_id", "survey_track_points.point_seq"],
        ),
    )

    annotation_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    survey_track_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("survey_tracks.survey_track_id"))
    annotation_seq: Mapped[int] = mapped_column(Integer)
    latitude: Mapped[float] = mapped_column(Double)
    longitude: Mapped[float] = mapped_column(Double)
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    label: Mapped[str] = mapped_column(Text)
    linked_point_seq: Mapped[int | None] = mapped_column(Integer)
    resolved_route_stop_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("route_stops.route_stop_id"))
    verification_status: Mapped[str] = mapped_column(enum("verification_status", VERIFICATION_STATUS))


# ---------- ① 시간표 ----------


class ScheduleTemplate(Base):
    __tablename__ = "schedule_templates"

    schedule_template_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, unique=True)
    day_type: Mapped[str] = mapped_column(enum("day_type", DAY_TYPE))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date] = mapped_column(Date)
    data_status: Mapped[str] = mapped_column(enum("data_status", DATA_STATUS))
    source_reference: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TripTemplate(Base):
    __tablename__ = "trip_templates"

    trip_template_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    schedule_template_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schedule_templates.schedule_template_id"))
    route_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("route_versions.route_version_id"))
    trip_no: Mapped[int] = mapped_column(Integer)
    source_row_key: Mapped[str] = mapped_column(Text, unique=True)
    # 기점을 확정하지 못한 회차는 null. 05 6단계에서 unknown으로 판정된다
    origin_route_stop_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("route_stops.route_stop_id"))
    excluded_weekdays: Mapped[list[str]] = mapped_column(ARRAY(String(3)), default=list)
    vehicle_count_by_weekday: Mapped[dict] = mapped_column(JSONB)
    schedule_source: Mapped[str] = mapped_column(enum("schedule_source", SCHEDULE_SOURCE))
    punctuality_assumption: Mapped[str] = mapped_column(enum("punctuality_assumption", PUNCTUALITY))
    # 원문 행의 칸 값(시각·X·경유·비고)을 해석 전 그대로 보존한다 (04 2장)
    source_cells: Mapped[dict] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(Text)


class ScheduledStopTime(Base):
    __tablename__ = "scheduled_stop_times"

    trip_template_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trip_templates.trip_template_id"), primary_key=True)
    route_stop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("route_stops.route_stop_id"), primary_key=True)
    event_type: Mapped[str] = mapped_column(enum("event_type", SCHEDULED_EVENT_TYPE), primary_key=True)
    scheduled_time: Mapped[time] = mapped_column(Time)
    day_offset: Mapped[int] = mapped_column(Integer, default=0)
    raw_value: Mapped[str] = mapped_column(Text)
    schedule_source: Mapped[str] = mapped_column(enum("schedule_source", SCHEDULE_SOURCE))


class ScheduleAnnotation(Base):
    """병합 칸의 범위형 소요 안내 (04 2장). 기산점 확인 전 ETA에 쓰지 않는다."""

    __tablename__ = "schedule_annotations"

    annotation_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_page: Mapped[str] = mapped_column(Text)
    route_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("routes.route_id"))
    trip_no: Mapped[int | None] = mapped_column(Integer)
    covered_stop_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    raw_text: Mapped[str] = mapped_column(Text)
    min_seconds: Mapped[int | None] = mapped_column(Integer)
    max_seconds: Mapped[int | None] = mapped_column(Integer)
    reference_stop_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stops.stop_id"))
    verification_status: Mapped[str] = mapped_column(enum("verification_status", VERIFICATION_STATUS))
