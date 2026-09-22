"""조사 트랙 적재·경로 생성 (04 1장 조사 트랙, IMPROVEMENTS 등록 절차, PLAN-route-data ②③)."""

from datetime import datetime, timezone

import pytest

from sqlalchemy import select

from app.models.reference import RoutePathPoint, RouteStop, RouteStopSegment, Stop, SurveyAnnotation, SurveyTrack, SurveyTrackPoint
from app.seed import route_id, stop_id, version_id
from app.stops import set_location
from app.survey import build_path, douglas_peucker, generate_demo_gpx, import_gpx, parse_gpx, verify_path

# 시험용 임시 좌표 (samples/stops-provisional.json 과 같은 성격 — 실제 승차 위치가 아니다)
COORDS = {
    "아산캠퍼스": (36.7998, 127.0745),
    "탕정역": (36.7896, 127.0839),
    "시티프라디움": (36.7910, 127.0950),
    "천안아산역": (36.7944, 127.1045),
}
RV = version_id("cheonan_asan", "general")
START = datetime(2026, 9, 18, 8, 0, tzinfo=timezone.utc)


def seed_coords(db, names=COORDS):
    for name, (lat, lng) in names.items():
        set_location(db, db.get(Stop, stop_id(name)), lat, lng, "needs_interpretation", 60)
    db.flush()


def demo_gpx(db) -> bytes:
    rows = db.execute(
        select(Stop).join(RouteStop, RouteStop.stop_id == Stop.stop_id).where(RouteStop.route_version_id == RV).order_by(RouteStop.stop_sequence)
    ).scalars().all()
    stops = [(s.name, s.latitude, s.longitude) for s in rows if s.latitude is not None]
    return generate_demo_gpx(stops, START).encode()


# ---------- 순수 함수 ----------


def test_parse_gpx_reads_points_extensions_and_waypoints():
    gpx = generate_demo_gpx([("A", 36.80, 127.07), ("B", 36.79, 127.08)], START).encode()
    parsed = parse_gpx(gpx)
    assert parsed.version == "1.1" and "demo" in (parsed.creator or "")
    assert len(parsed.waypoints) == 2 and parsed.waypoints[0].name == "A"
    first = parsed.points[0]
    assert (first.lat, first.speed, first.sat, first.hdop) == (36.80, 0.0, 9, 1.2)
    assert first.time == START and first.raw_extensions and "speed" in first.raw_extensions
    assert first.accuracy is None  # 표준 GPX에는 정확도 필드가 없다 (IMPROVEMENTS)


def test_douglas_peucker_keeps_endpoints_and_corners():
    line = [(36.80, 127.07), (36.80, 127.071), (36.80, 127.072), (36.80, 127.073)]
    assert douglas_peucker(line, 5.0) == [0, 3]
    corner = [(36.80, 127.07), (36.80, 127.08), (36.81, 127.08)]
    assert douglas_peucker(corner, 5.0) == [0, 1, 2]


# ---------- 적재 ----------


def test_import_is_idempotent_by_file_hash(db):
    seed_coords(db)
    data = demo_gpx(db)
    track, created = import_gpx(db, data, RV, file_ref="demo.gpx", device_label="test", note="demo")
    assert created and track.point_count > 100 and track.recorded_on == START.date()
    again, created2 = import_gpx(db, data, RV, file_ref="demo-copy.gpx", device_label="other", note=None)
    assert not created2 and again.survey_track_id == track.survey_track_id
    assert db.scalar(select(SurveyTrack).where(SurveyTrack.source_file_hash == track.source_file_hash)) is track
    points = db.scalars(select(SurveyTrackPoint).where(SurveyTrackPoint.survey_track_id == track.survey_track_id)).all()
    assert len(points) == track.point_count and all(p.raw_extensions for p in points)
    annotations = db.scalars(select(SurveyAnnotation).where(SurveyAnnotation.survey_track_id == track.survey_track_id)).all()
    assert [a.label for a in annotations] == ["아산캠퍼스", "탕정역", "시티프라디움", "천안아산역", "아산캠퍼스"]
    assert all(a.resolved_route_stop_id is None and a.linked_point_seq is None for a in annotations)  # 적재만으로는 매핑하지 않는다


# ---------- 경로 생성 ----------


def test_build_path_creates_polyline_segments_and_resolves_annotations(db):
    seed_coords(db)
    track, _ = import_gpx(db, demo_gpx(db), RV, file_ref="demo.gpx", device_label=None, note="demo")
    report = build_path(db, track, tolerance_m=5.0)
    path = db.scalars(select(RoutePathPoint).where(RoutePathPoint.route_version_id == RV).order_by(RoutePathPoint.path_seq)).all()
    assert report.path_points == len(path) and 5 <= len(path) < track.point_count
    assert all(p.path_source == "recorded_track" for p in path)
    segments = db.scalars(select(RouteStopSegment).where(RouteStopSegment.route_version_id == RV).order_by(RouteStopSegment.path_from_seq)).all()
    # 캠퍼스→탕정역→시티프라디움→천안아산역→캠퍼스: 좌표 있는 인접 방문 쌍 4개
    assert report.segments == len(segments) == 4 and report.unmapped_stops == []
    assert all(s.verification_status == "unverified" for s in segments)  # 첫 트랙은 검증 전
    assert all(s.path_from_seq < s.path_to_seq and s.distance_m > 500 for s in segments)
    # 왕복 — 같은 캠퍼스 정거장이 처음과 끝에 따로 잡힌다
    assert segments[0].path_from_seq == 1 and segments[-1].path_to_seq == len(path)
    assert report.annotations_resolved == report.annotations_total == 5
    resolved = db.scalars(select(SurveyAnnotation).where(SurveyAnnotation.survey_track_id == track.survey_track_id).order_by(SurveyAnnotation.annotation_seq)).all()
    assert all(a.resolved_route_stop_id is not None and a.linked_point_seq is not None for a in resolved)


def test_build_path_is_rebuildable_with_other_tolerance(db):
    seed_coords(db)
    track, _ = import_gpx(db, demo_gpx(db), RV, file_ref="demo.gpx", device_label=None, note="demo")
    fine = build_path(db, track, tolerance_m=0.5).path_points
    coarse = build_path(db, track, tolerance_m=50.0).path_points
    assert coarse <= fine
    # 다시 만들어도 구간 수는 같고 원본 점은 그대로
    assert db.scalar(select(SurveyTrack).where(SurveyTrack.survey_track_id == track.survey_track_id)).point_count == track.point_count
    assert len(db.scalars(select(RouteStopSegment).where(RouteStopSegment.route_version_id == RV)).all()) == 4


def test_build_path_skips_stops_without_coordinates(db):
    seed_coords(db, {k: v for k, v in COORDS.items() if k != "시티프라디움"})
    track, _ = import_gpx(db, demo_gpx(db), RV, file_ref="demo.gpx", device_label=None, note="demo")
    report = build_path(db, track)
    # 시티프라디움 좌표가 없으면 그 앞뒤 구간은 만들지 않는다 — 가짜 구간을 만들지 않는다
    assert report.unmapped_stops == ["시티프라디움"] and report.segments == 2


def test_verify_marks_segments_from_second_track(db):
    seed_coords(db)
    first, _ = import_gpx(db, demo_gpx(db), RV, file_ref="a.gpx", device_label=None, note="demo")
    build_path(db, first)
    # 두 번째 트랙: 같은 경로를 살짝 다른 시각·흔들림으로
    rows = db.execute(select(Stop).join(RouteStop, RouteStop.stop_id == Stop.stop_id).where(RouteStop.route_version_id == RV).order_by(RouteStop.stop_sequence)).scalars().all()
    stops = [(s.name, s.latitude, s.longitude) for s in rows]
    second_data = generate_demo_gpx(stops, datetime(2026, 9, 19, 8, 0, tzinfo=timezone.utc), jitter_m=4.0).encode()
    second, created = import_gpx(db, second_data, RV, file_ref="b.gpx", device_label=None, note="demo")
    assert created
    report = verify_path(db, second, max_deviation_m=30.0, allow_demo=True)  # 데모는 시험에서만 명시 허용
    assert report.verified == 4 and report.needs_interpretation == 0 and report.skipped == 0
    assert all(s.verification_status == "verified" for s in db.scalars(select(RouteStopSegment).where(RouteStopSegment.route_version_id == RV)))
    # 크게 어긋난 트랙은 needs_interpretation
    shifted = [(n, lat + 0.002, lng) for n, lat, lng in stops]  # 약 220m 북쪽
    third, _ = import_gpx(db, generate_demo_gpx(shifted, datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc)).encode(), RV, file_ref="c.gpx", device_label=None, note="demo")
    report = verify_path(db, third, max_deviation_m=30.0, allow_demo=True)
    assert report.verified == 0 and report.skipped == 4  # 정거장 자체가 150m 밖이라 대조 불가


# ---------- 경로 API ----------


def test_route_path_api(client, db, set_now):
    set_now(2026, 9, 18, 9, 0)
    rid = str(route_id("cheonan_asan"))
    empty = client.get(f"/api/v1/routes/{rid}/path", params={"service_date": "2026-09-18"}).json()
    assert empty["patterns"] and all(p["verification"] == "none" and p["points"] == [] for p in empty["patterns"])

    seed_coords(db)
    track, _ = import_gpx(db, demo_gpx(db), RV, file_ref="demo.gpx", device_label=None, note="demo")
    build_path(db, track)
    body = client.get(f"/api/v1/routes/{rid}/path", params={"service_date": "2026-09-18"}).json()
    pattern = next(p for p in body["patterns"] if p["route_version_id"] == str(RV))
    assert pattern["pattern_code"] == "general" and pattern["path_source"] == "recorded_track"
    assert pattern["point_count"] == len(pattern["points"]) >= 5 and len(pattern["points"][0]) == 2
    assert len(pattern["segments"]) == 4 and pattern["verification"] == "unverified"
    assert client.get(f"/api/v1/routes/{rid}/path", params={"service_date": "2026-09-05"}).status_code == 200


def test_verify_refuses_demo_and_self_verification(db):
    """가짜 자료·자기 기록으로 verified를 만들지 않는다 (CLAUDE.md 5절, REVIEW-2026-09-21 P1)."""
    seed_coords(db)
    first, _ = import_gpx(db, demo_gpx(db), RV, file_ref="a.gpx", device_label=None, note="demo")
    build_path(db, first)

    with pytest.raises(SystemExit, match="데모 트랙"):
        verify_path(db, first, max_deviation_m=30.0)

    # 데모 표시를 지워도 경로를 만든 그 기록이면 거절한다
    first.app_version, first.note, first.source_file_ref = "RealApp 1.0", None, "ride.gpx"
    db.flush()
    with pytest.raises(SystemExit, match="그 기록으로는"):
        verify_path(db, first, max_deviation_m=30.0)

    assert all(
        s.verification_status == "unverified"
        for s in db.scalars(select(RouteStopSegment).where(RouteStopSegment.route_version_id == RV))
    )


def test_route_path_verification_needs_full_coverage(client, db, set_now):
    """구간이 빠져 있으면 전체를 verified로 표시하지 않는다 (REVIEW-2026-09-21 P1)."""
    from app.seed import route_id as seed_route_id

    seed_coords(db)
    first, _ = import_gpx(db, demo_gpx(db), RV, file_ref="a.gpx", device_label=None, note="demo")
    build_path(db, first)
    for segment in db.scalars(select(RouteStopSegment).where(RouteStopSegment.route_version_id == RV)):
        segment.verification_status = "verified"
    db.flush()
    set_now(2026, 9, 21, 9, 0)
    params = {"service_date": "2026-09-21"}

    def pattern_verification():
        body = client.get(f"/api/v1/routes/{seed_route_id('cheonan_asan')}/path", params=params).json()
        return next(p["verification"] for p in body["patterns"] if p["route_version_id"] == str(RV))

    full = db.scalars(select(RouteStopSegment).where(RouteStopSegment.route_version_id == RV)).all()
    assert len(full) >= 2
    assert pattern_verification() == "verified"

    db.delete(full[0])  # 좌표 없는 정거장 때문에 구간 하나가 없는 상황
    db.flush()
    assert pattern_verification() == "partial"


NO_TIME_GPX = b"""<?xml version="1.0"?>
<gpx version="1.1" creator="RealLogger 2.0" xmlns="http://www.topografix.com/GPX/1/1">
 <trk><trkseg>
  <trkpt lat="36.7998" lon="127.0745"></trkpt>
  <trkpt lat="36.7950" lon="127.0800"></trkpt>
  <trkpt lat="36.7944" lon="127.1045"></trkpt>
 </trkseg></trk>
</gpx>"""


def test_verify_refuses_when_provenance_cannot_be_checked(db):
    """측정 시각이 없어 같은 기록인지 확인할 수 없으면 통과시키지 않는다 (REVIEW-2026-09-22 P1)."""
    seed_coords(db)
    first, _ = import_gpx(db, NO_TIME_GPX, RV, file_ref="ride-a.gpx", device_label=None, note=None)
    build_path(db, first)

    second, _ = import_gpx(db, NO_TIME_GPX.replace(b"36.7950", b"36.7951"), RV, file_ref="ride-b.gpx", device_label=None, note=None)
    with pytest.raises(SystemExit, match="확인할 수 없다"):
        verify_path(db, second, max_deviation_m=30.0)

    assert all(
        s.verification_status != "verified"
        for s in db.scalars(select(RouteStopSegment).where(RouteStopSegment.route_version_id == RV))
    )


def test_cli_has_no_demo_bypass():
    """CLI에 데모 허용 옵션이 없어야 한다 — 우회 옵션이 실제 DB에 검증 완료를 저장했다 (REVIEW-2026-09-22 P1)."""
    import io as _io

    from app import survey

    assert "--allow-demo" not in _io.open(survey.__file__, encoding="utf-8").read()
