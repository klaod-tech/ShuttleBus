from app.models import calendar, reference  # noqa: F401  메타데이터 등록
from app.models.base import Base

# 15 1장의 층. FR-DM-01 검사와 마이그레이션 순서가 이 표를 따른다
LAYERS: dict[str, int] = {
    "survey_tracks": 0,
    "survey_track_points": 0,
    "survey_annotations": 0,
    "stops": 1,
    "routes": 1,
    "route_patterns": 1,
    "route_versions": 1,
    "route_stops": 1,
    "route_path_points": 1,
    "route_stop_segments": 1,
    "source_stop_labels": 1,
    "schedule_templates": 1,
    "trip_templates": 1,
    "scheduled_stop_times": 1,
    "schedule_annotations": 1,
    "schedule_exceptions": 2,
    "schedule_route_coverage": 2,
    "service_calendar": 2,
    "scheduled_trips": 2,
    "scheduled_trip_stops": 2,
    "trip_vehicles": 2,
}

__all__ = ["Base", "LAYERS"]
