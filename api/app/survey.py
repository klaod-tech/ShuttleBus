"""조사 트랙(GPX) 적재와 경로 생성 (04 1장 조사 트랙, IMPROVEMENTS '등록 절차', PLAN-route-data ②).

원본(⓪ survey_*)은 고치지 않는다. 정제 결과(① route_path_points·route_stop_segments)는 언제든 다시 만든다.

실행
  python -m app.survey gpx-demo --pattern cheonan_asan/general --out demo.gpx   가짜 트랙 (시험 전용)
  python -m app.survey import --file x.gpx --pattern cheonan_asan/general [--label 폰이름] [--note ...]
  python -m app.survey build-path --track <survey_track_id> [--tolerance 5] [--max-speed 40]
  python -m app.survey verify --track <survey_track_id> [--max-deviation 30]   두 번째 트랙으로 구간 검증
  python -m app.survey list
"""

import argparse
import hashlib
import math
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models.reference import (
    RoutePathPoint,
    RoutePattern,
    RouteStop,
    RouteStopSegment,
    RouteVersion,
    Stop,
    SurveyAnnotation,
    SurveyTrack,
    SurveyTrackPoint,
)
from app.seed import version_id as seed_version_id

EARTH_R = 6_371_000.0
# 시험값은 Settings에 있다 (01 설정 인덱스, 14 4장 ConfigMap). 여기서는 기본 인자로만 읽는다
DEFAULT_TOLERANCE_M = settings.survey_tolerance_m
DEFAULT_MAX_SPEED_MPS = settings.survey_max_speed_mps
DEFAULT_MAX_DEVIATION_M = settings.survey_max_deviation_m
STOP_MATCH_RADIUS_M = settings.survey_stop_match_radius_m
DWELL_SPEED_MPS = settings.survey_dwell_speed_mps

# 같은 기록으로 자기 자신을 검증하지 못하게 하는 기준 — 경로 점 시각이 이 비율 이상 겹치면 같은 기록으로 본다
SAME_RECORDING_OVERLAP = 0.9


# ---------- 기하 ----------


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def _xy(lat: float, lng: float, lat0: float) -> tuple[float, float]:
    """국지 등거리 투영 (m). 수 km 범위에서 충분하다."""
    return (math.radians(lng) * EARTH_R * math.cos(math.radians(lat0)), math.radians(lat) * EARTH_R)


def point_segment_distance_m(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    """점 p와 선분 ab 거리 (m). 07 4장 2단계와 같은 식 — 여기서는 좌표 점과 경로 선분."""
    lat0 = (a[0] + b[0]) / 2
    px, py = _xy(*p, lat0)
    ax, ay = _xy(*a, lat0)
    bx, by = _xy(*b, lat0)
    vx, vy = bx - ax, by - ay
    denom = vx * vx + vy * vy
    u = 0.0 if denom == 0 else max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / denom))
    cx, cy = ax + u * vx, ay + u * vy
    return math.hypot(px - cx, py - cy)


def douglas_peucker(points: list[tuple[float, float]], tolerance_m: float) -> list[int]:
    """단순화 후 남길 점의 인덱스 (원본 순서). 양 끝은 항상 남는다."""
    if len(points) <= 2:
        return list(range(len(points)))
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        s, e = stack.pop()
        if e - s < 2:
            continue
        best_d, best_i = -1.0, -1
        for i in range(s + 1, e):
            d = point_segment_distance_m(points[i], points[s], points[e])
            if d > best_d:
                best_d, best_i = d, i
        if best_d > tolerance_m:
            keep[best_i] = True
            stack.append((s, best_i))
            stack.append((best_i, e))
    return [i for i, k in enumerate(keep) if k]


# ---------- GPX ----------


@dataclass
class GpxPoint:
    lat: float
    lng: float
    time: datetime | None
    ele: float | None = None
    speed: float | None = None
    bearing: float | None = None
    sat: int | None = None
    hdop: float | None = None
    accuracy: float | None = None
    raw_extensions: str | None = None


@dataclass
class GpxWaypoint:
    lat: float
    lng: float
    time: datetime | None
    name: str


@dataclass
class ParsedGpx:
    version: str | None
    creator: str | None
    points: list[GpxPoint] = field(default_factory=list)
    waypoints: list[GpxWaypoint] = field(default_factory=list)


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_text(el: ET.Element, name: str) -> str | None:
    for child in el.iter():
        if child is not el and _localname(child.tag) == name and child.text:
            return child.text.strip()
    return None


def _parse_time(text: str | None) -> datetime | None:
    if not text:
        return None
    t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _float(text: str | None) -> float | None:
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None


def parse_gpx(data: bytes) -> ParsedGpx:
    """GPX 1.0/1.1. 이름공간이 무엇이든 지역 이름으로 읽는다. <extensions>는 원문 그대로 보존."""
    root = ET.fromstring(data)
    parsed = ParsedGpx(version=root.get("version"), creator=root.get("creator"))
    for el in root.iter():
        tag = _localname(el.tag)
        if tag == "trkpt":
            ext = next((c for c in el if _localname(c.tag) == "extensions"), None)
            parsed.points.append(
                GpxPoint(
                    lat=float(el.get("lat")),
                    lng=float(el.get("lon")),
                    time=_parse_time(_find_text(el, "time")),
                    ele=_float(_find_text(el, "ele")),
                    speed=_float(_find_text(el, "speed")),
                    bearing=_float(_find_text(el, "course") or _find_text(el, "bearing")),
                    sat=int(_find_text(el, "sat")) if _find_text(el, "sat") else None,
                    hdop=_float(_find_text(el, "hdop")),
                    accuracy=_float(_find_text(el, "accuracy")),
                    raw_extensions=ET.tostring(ext, encoding="unicode") if ext is not None else None,
                )
            )
        elif tag == "wpt":
            parsed.waypoints.append(
                GpxWaypoint(float(el.get("lat")), float(el.get("lon")), _parse_time(_find_text(el, "time")), _find_text(el, "name") or "")
            )
    return parsed


def generate_demo_gpx(stops: list[tuple[str, float, float]], start: datetime, *, interval_s: int = 3, speed_mps: float = 8.0, dwell_s: int = 30, jitter_m: float = 2.0) -> str:
    """정거장 좌표를 직선으로 이어 만든 **가짜** 트랙. 시험 전용이며 실제 경로가 아니다.

    정거장마다 dwell_s 동안 속도 0으로 머물고, 이동 중에는 좌표를 jitter_m 만큼 결정적으로 흔든다.
    creator에 'demo'를 박아 진짜 파일과 섞이지 않게 한다.
    """
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="ShuttleBus demo (NOT a real recording)" xmlns="http://www.topografix.com/GPX/1/1">',
    ]
    for name, lat, lng in stops:
        lines.append(f'  <wpt lat="{lat:.6f}" lon="{lng:.6f}"><name>{name}</name></wpt>')
    lines.append(f'  <trk><name>demo {stops[0][0]} → {stops[-1][0]}</name><trkseg>')
    t = start
    seq = 0

    def emit(lat, lng, speed, bearing):
        nonlocal t, seq
        seq += 1
        lines.append(
            f'    <trkpt lat="{lat:.6f}" lon="{lng:.6f}"><time>{t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}</time>'
            f'<sat>9</sat><hdop>1.2</hdop><extensions><speed>{speed:.2f}</speed><course>{bearing:.1f}</course></extensions></trkpt>'
        )
        t += timedelta(seconds=interval_s)

    for i, (_, lat, lng) in enumerate(stops):
        for _ in range(max(1, dwell_s // interval_s)):
            emit(lat, lng, 0.0, 0.0)
        if i == len(stops) - 1:
            break
        nlat, nlng = stops[i + 1][1], stops[i + 1][2]
        dist = haversine_m(lat, lng, nlat, nlng)
        steps = max(1, int(dist / (speed_mps * interval_s)))
        bearing = (math.degrees(math.atan2(nlng - lng, nlat - lat)) + 360) % 360
        for k in range(1, steps + 1):
            f = k / steps
            # 결정적 흔들림 — 같은 입력이면 같은 파일 (해시 멱등 시험용)
            j = jitter_m * math.sin(seq * 0.7) / 111_000
            emit(lat + (nlat - lat) * f + j, lng + (nlng - lng) * f + j, speed_mps, bearing)
    lines += ["  </trkseg></trk>", "</gpx>", ""]
    return "\n".join(lines)


# ---------- 적재 ----------


def resolve_pattern(session: Session, pattern: str, version_no: int = 1) -> RouteVersion:
    """'route/code' (+ --version) → route_version. 예: cheonan_asan/general. 노선 개정 후에는 새 version_no를 준다"""
    try:
        route, code = pattern.split("/", 1)
    except ValueError:
        raise SystemExit("--pattern 은 route/code 형식이다. 예: cheonan_asan/general") from None
    version = session.get(RouteVersion, seed_version_id(route, code, version_no))
    if version is None:
        raise SystemExit(f"경로 버전을 찾을 수 없다: {pattern}")
    return version


def import_gpx(session: Session, data: bytes, route_version_id: uuid.UUID, *, file_ref: str | None, device_label: str | None, note: str | None) -> tuple[SurveyTrack, bool]:
    """같은 파일(해시)은 기존 조사 건을 돌려준다 (04 v7.8 조사 자료 검증)."""
    digest = hashlib.sha256(data).hexdigest()
    existing = session.scalar(select(SurveyTrack).where(SurveyTrack.source_file_hash == digest))
    if existing is not None:
        return existing, False
    parsed = parse_gpx(data)
    first_time = next((p.time for p in parsed.points if p.time), None)
    track = SurveyTrack(
        route_version_id=route_version_id,
        recorded_on=first_time.date() if first_time else None,
        device_label=device_label,
        gpx_version=parsed.version,
        point_count=len(parsed.points),
        note=note,
        source_file_hash=digest,
        source_file_ref=file_ref,
        app_version=parsed.creator,
        export_format="gpx",
        recording_settings=None,
    )
    session.add(track)
    session.flush()
    for seq, p in enumerate(parsed.points, start=1):
        session.add(
            SurveyTrackPoint(
                survey_track_id=track.survey_track_id, point_seq=seq, measured_at=p.time, latitude=p.lat, longitude=p.lng,
                elevation_m=p.ele, speed_mps=p.speed, bearing_deg=p.bearing, sat_count=p.sat, hdop=p.hdop, accuracy_m=p.accuracy,
                raw_extensions=p.raw_extensions,
            )
        )
    for seq, w in enumerate(parsed.waypoints, start=1):
        session.add(
            SurveyAnnotation(
                survey_track_id=track.survey_track_id, annotation_seq=seq, latitude=w.lat, longitude=w.lng, measured_at=w.time,
                label=w.name, linked_point_seq=None, resolved_route_stop_id=None, verification_status="unverified",
            )
        )
    session.flush()
    return track, True


# ---------- 경로 생성 ----------


@dataclass
class BuildReport:
    raw_points: int
    kept_after_outliers: int
    path_points: int
    segments: int
    unmapped_stops: list[str]
    annotations_resolved: int
    annotations_total: int


def remove_outliers(points: list[SurveyTrackPoint], max_speed_mps: float) -> list[SurveyTrackPoint]:
    """직전에 남긴 점 기준으로 불가능한 속도로 튄 점을 버린다. 시각이 없으면 거리 기준(200m)만 본다."""
    kept: list[SurveyTrackPoint] = []
    for p in points:
        if kept:
            q = kept[-1]
            d = haversine_m(q.latitude, q.longitude, p.latitude, p.longitude)
            if p.measured_at and q.measured_at:
                dt = (p.measured_at - q.measured_at).total_seconds()
                if dt <= 0 and d > 0:
                    continue  # 시각 역행
                if dt > 0 and d / dt > max_speed_mps:
                    continue
            elif d > 200:
                continue
        kept.append(p)
    return kept


def _nearest_index(coords: list[tuple[float, float]], lat: float, lng: float, start: int = 0) -> tuple[int, float]:
    best_i, best_d = -1, float("inf")
    for i in range(start, len(coords)):
        d = haversine_m(lat, lng, coords[i][0], coords[i][1])
        if d < best_d:
            best_i, best_d = i, d
    return best_i, best_d


def build_path(session: Session, track: SurveyTrack, *, tolerance_m: float = DEFAULT_TOLERANCE_M, max_speed_mps: float = DEFAULT_MAX_SPEED_MPS) -> BuildReport:
    """IMPROVEMENTS 2~7단계. 이 경로 버전의 기존 정제 결과는 지우고 다시 만든다 (원본은 survey_*에 남는다)."""
    if track.route_version_id is None:
        raise SystemExit("트랙에 경로 버전이 없다")
    rv = track.route_version_id
    raw = list(
        session.scalars(select(SurveyTrackPoint).where(SurveyTrackPoint.survey_track_id == track.survey_track_id).order_by(SurveyTrackPoint.point_seq))
    )
    if len(raw) < 2:
        raise SystemExit("경로 점이 2개 미만이라 폴리라인을 만들 수 없다 (주석 전용 파일은 경로 근거로 쓰지 않는다)")
    kept = remove_outliers(raw, max_speed_mps)
    coords = [(p.latitude, p.longitude) for p in kept]
    keep_idx = douglas_peucker(coords, tolerance_m)
    simplified = [kept[i] for i in keep_idx]

    session.execute(delete(RouteStopSegment).where(RouteStopSegment.route_version_id == rv))
    session.execute(delete(RoutePathPoint).where(RoutePathPoint.route_version_id == rv))
    session.flush()
    for seq, p in enumerate(simplified, start=1):
        session.add(RoutePathPoint(route_version_id=rv, path_seq=seq, latitude=p.latitude, longitude=p.longitude, path_source="recorded_track", recorded_at=p.measured_at))
    session.flush()

    # 정거장 → 경로 점 매핑. 방문 순서대로 앞으로만 찾는다 (왕복은 캠퍼스로 돌아오므로 단조 탐색이 필요)
    path_coords = [(p.latitude, p.longitude) for p in simplified]
    route_stops = list(
        session.execute(
            select(RouteStop, Stop).join(Stop, Stop.stop_id == RouteStop.stop_id).where(RouteStop.route_version_id == rv).order_by(RouteStop.stop_sequence)
        )
    )
    mapped: list[tuple[RouteStop, int] | None] = []
    unmapped: list[str] = []
    cursor = 0
    for rs, stop in route_stops:
        if stop.latitude is None:
            mapped.append(None)
            unmapped.append(stop.name)
            continue
        i, d = _nearest_index(path_coords, stop.latitude, stop.longitude, cursor)
        if d > STOP_MATCH_RADIUS_M:
            mapped.append(None)
            unmapped.append(f"{stop.name} (경로에서 {d:.0f}m)")
            continue
        mapped.append((rs, i))
        cursor = i
    segments = 0
    for a, b in zip(mapped, mapped[1:]):
        if a is None or b is None:
            continue
        (rs_a, ia), (rs_b, ib) = a, b
        if ib <= ia:
            continue
        distance = sum(haversine_m(*path_coords[k], *path_coords[k + 1]) for k in range(ia, ib))
        session.add(
            RouteStopSegment(
                route_version_id=rv, from_route_stop_id=rs_a.route_stop_id, to_route_stop_id=rs_b.route_stop_id,
                path_from_seq=ia + 1, path_to_seq=ib + 1, distance_m=distance, path_source="recorded_track", verification_status="unverified",
            )
        )
        segments += 1

    # 주석 → 부근 정차 구간 → 정거장. 주석 좌표를 그대로 쓰지 않는다 (04 1장)
    annotations = list(session.scalars(select(SurveyAnnotation).where(SurveyAnnotation.survey_track_id == track.survey_track_id)))
    dwell = [p for p in kept if p.speed_mps is not None and p.speed_mps <= DWELL_SPEED_MPS]
    stops_with_coords = [(rs, stop) for rs, stop in route_stops if stop.latitude is not None]
    resolved = 0
    for ann in annotations:
        near = [p for p in dwell if haversine_m(ann.latitude, ann.longitude, p.latitude, p.longitude) <= STOP_MATCH_RADIUS_M]
        if not near:
            ann.resolved_route_stop_id, ann.verification_status = None, "needs_interpretation"
            continue
        clat = sum(p.latitude for p in near) / len(near)
        clng = sum(p.longitude for p in near) / len(near)
        best = min(stops_with_coords, key=lambda rs_stop: haversine_m(clat, clng, rs_stop[1].latitude, rs_stop[1].longitude), default=None)
        if best is None or haversine_m(clat, clng, best[1].latitude, best[1].longitude) > STOP_MATCH_RADIUS_M:
            ann.resolved_route_stop_id, ann.verification_status = None, "needs_interpretation"
            continue
        ann.resolved_route_stop_id, ann.verification_status = best[0].route_stop_id, "unverified"
        ann.linked_point_seq = min(near, key=lambda p: haversine_m(ann.latitude, ann.longitude, p.latitude, p.longitude)).point_seq
        resolved += 1
    session.flush()
    return BuildReport(len(raw), len(kept), len(simplified), segments, unmapped, resolved, len(annotations))


# ---------- 검증 ----------


@dataclass
class VerifyReport:
    verified: int
    needs_interpretation: int
    skipped: int
    max_deviation_by_segment: dict[str, float]


def is_demo_track(track: SurveyTrack) -> bool:
    """gpx-demo가 만든 가짜 기록인지. creator는 app_version에 저장된다 (generate_demo_gpx)."""
    marks = (track.app_version or "", track.note or "", track.source_file_ref or "")
    return any("demo" in m.lower() for m in marks)


def _same_recording(session: Session, track: SurveyTrack, path: list[RoutePathPoint]) -> bool:
    """경로를 만든 그 기록으로 다시 검증하려는 경우. 경로 점 시각은 원본 점의 측정 시각을 그대로 복사한다.

    출처 트랙 ID 열이 없어 시각 겹침으로 판정한다. 열을 추가하려면 스키마 변경 승인이 필요하다
    (CLAUDE.md 2절, REVIEW-2026-09-21 P1).
    """
    path_times = {p.recorded_at for p in path if p.recorded_at is not None}
    if not path_times:
        return False
    track_times = set(
        session.scalars(select(SurveyTrackPoint.measured_at).where(SurveyTrackPoint.survey_track_id == track.survey_track_id))
    )
    return len(path_times & track_times) / len(path_times) >= SAME_RECORDING_OVERLAP


def verify_path(
    session: Session,
    track: SurveyTrack,
    *,
    max_deviation_m: float = DEFAULT_MAX_DEVIATION_M,
    max_speed_mps: float = DEFAULT_MAX_SPEED_MPS,
    allow_demo: bool = False,
) -> VerifyReport:
    """두 번째 트랙으로 구간을 검증한다. 구간 안의 점이 전부 폴리라인에서 max_deviation_m 안이면 verified.

    **가짜 자료와 자기 자신으로는 verified를 만들지 않는다** (CLAUDE.md 5절, 2026-09-22).
    데모 트랙은 거절하고(시험은 allow_demo로 명시), 경로를 만든 그 기록으로 검증하는 것도 거절한다.
    """
    rv = track.route_version_id
    path = list(session.scalars(select(RoutePathPoint).where(RoutePathPoint.route_version_id == rv).order_by(RoutePathPoint.path_seq)))
    if not path:
        raise SystemExit("먼저 build-path로 경로를 만든다")
    if is_demo_track(track) and not allow_demo:
        raise SystemExit("데모 트랙으로는 검증하지 않는다 — 실제 탑승 기록을 쓴다 (시험은 --allow-demo)")
    if _same_recording(session, track, path):
        raise SystemExit("경로를 만든 그 기록으로는 검증하지 않는다 — 다른 탑승의 트랙이 필요하다")
    path_coords = [(p.latitude, p.longitude) for p in path]
    raw = list(session.scalars(select(SurveyTrackPoint).where(SurveyTrackPoint.survey_track_id == track.survey_track_id).order_by(SurveyTrackPoint.point_seq)))
    kept = remove_outliers(raw, max_speed_mps)
    coords = [(p.latitude, p.longitude) for p in kept]
    segments = list(
        session.execute(
            select(RouteStopSegment, Stop.name)
            .join(RouteStop, RouteStop.route_stop_id == RouteStopSegment.from_route_stop_id)
            .join(Stop, Stop.stop_id == RouteStop.stop_id)
            .where(RouteStopSegment.route_version_id == rv)
            .order_by(RouteStopSegment.path_from_seq)
        )
    )
    report = VerifyReport(0, 0, 0, {})
    cursor = 0
    for seg, from_name in segments:
        a, b = path_coords[seg.path_from_seq - 1], path_coords[seg.path_to_seq - 1]
        ia, da = _nearest_index(coords, *a, cursor)
        ib, db = _nearest_index(coords, *b, ia)
        if da > STOP_MATCH_RADIUS_M or db > STOP_MATCH_RADIUS_M or ib <= ia:
            report.skipped += 1
            continue
        cursor = ib
        poly = path_coords[seg.path_from_seq - 1 : seg.path_to_seq]
        worst = 0.0
        for c in coords[ia : ib + 1]:
            d = min(point_segment_distance_m(c, poly[k], poly[k + 1]) for k in range(len(poly) - 1)) if len(poly) > 1 else haversine_m(*c, *poly[0])
            worst = max(worst, d)
        report.max_deviation_by_segment[from_name] = worst
        if worst <= max_deviation_m:
            seg.verification_status = "verified"
            report.verified += 1
        else:
            seg.verification_status = "needs_interpretation"
            report.needs_interpretation += 1
    session.flush()
    return report


# ---------- CLI ----------


def _pattern_label(session: Session, rv_id: uuid.UUID | None) -> str:
    if rv_id is None:
        return "-"
    rv = session.get(RouteVersion, rv_id)
    pattern = session.get(RoutePattern, rv.route_pattern_id)
    return f"{pattern.pattern_code}@{rv.version_no}"


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.survey")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("gpx-demo", help="정거장 좌표를 이은 가짜 GPX (시험 전용)")
    demo.add_argument("--pattern", required=True, help="route/code, 예: cheonan_asan/general")
    demo.add_argument("--out", required=True)
    demo.add_argument("--version", type=int, default=1)
    imp = sub.add_parser("import", help="GPX 적재 (해시로 멱등)")
    imp.add_argument("--file", required=True)
    imp.add_argument("--pattern", required=True)
    imp.add_argument("--label", default=None, help="기록 단말 이름")
    imp.add_argument("--note", default=None)
    imp.add_argument("--version", type=int, default=1, help="route_version 번호 (기본 1)")
    build = sub.add_parser("build-path", help="트랙 → route_path_points·route_stop_segments")
    build.add_argument("--track", required=True)
    build.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE_M)
    build.add_argument("--max-speed", type=float, default=DEFAULT_MAX_SPEED_MPS)
    ver = sub.add_parser("verify", help="두 번째 트랙으로 구간 검증 (데모·자기 기록 거절)")
    ver.add_argument("--track", required=True)
    ver.add_argument("--max-deviation", type=float, default=DEFAULT_MAX_DEVIATION_M)
    ver.add_argument("--allow-demo", action="store_true", help="데모 트랙으로도 검증 (시험 전용)")
    sub.add_parser("list", help="트랙과 경로 상태")
    args = parser.parse_args()

    with SessionLocal() as session:
        if args.command == "gpx-demo":
            rv = resolve_pattern(session, args.pattern, args.version)
            rows = session.execute(select(Stop).join(RouteStop, RouteStop.stop_id == Stop.stop_id).where(RouteStop.route_version_id == rv.route_version_id).order_by(RouteStop.stop_sequence)).scalars().all()
            stops = [(s.name, s.latitude, s.longitude) for s in rows if s.latitude is not None]
            if len(stops) < 2:
                raise SystemExit("좌표가 있는 정거장이 2개 미만이다. 먼저 app.stops import 로 좌표를 넣는다")
            text = generate_demo_gpx(stops, datetime.now(tz=timezone.utc).replace(microsecond=0))
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"가짜 트랙 저장: {args.out} — 정거장 {len(stops)}개 (좌표 없는 정거장은 건너뜀). 실제 경로가 아니다")
            return
        if args.command == "import":
            rv = resolve_pattern(session, args.pattern, args.version)
            with open(args.file, "rb") as f:
                data = f.read()
            track, created = import_gpx(session, data, rv.route_version_id, file_ref=args.file, device_label=args.label, note=args.note)
            session.commit()
            print(("적재: " if created else "이미 있는 파일 (기존 조사 건): ") + f"{track.survey_track_id} 점 {track.point_count}개")
            return
        if args.command == "build-path":
            track = session.get(SurveyTrack, uuid.UUID(args.track))
            if track is None:
                raise SystemExit("트랙이 없다")
            r = build_path(session, track, tolerance_m=args.tolerance, max_speed_mps=args.max_speed)
            session.commit()
            print(f"원본 {r.raw_points} → 이상치 제거 {r.kept_after_outliers} → 단순화 {r.path_points}점, 구간 {r.segments}개 (unverified), 주석 {r.annotations_resolved}/{r.annotations_total} 매핑")
            for name in r.unmapped_stops:
                print(f"  구간 없음: {name}")
            return
        if args.command == "verify":
            track = session.get(SurveyTrack, uuid.UUID(args.track))
            if track is None:
                raise SystemExit("트랙이 없다")
            r = verify_path(session, track, max_deviation_m=args.max_deviation, allow_demo=args.allow_demo)
            session.commit()
            print(f"verified {r.verified}, needs_interpretation {r.needs_interpretation}, 대조 불가 {r.skipped}")
            for name, d in r.max_deviation_by_segment.items():
                print(f"  {name} 이후 구간: 최대 {d:.1f}m")
            return
        for t in session.scalars(select(SurveyTrack).order_by(SurveyTrack.imported_at)):
            print(f"{t.survey_track_id}\t{_pattern_label(session, t.route_version_id)}\t{t.recorded_on}\t점 {t.point_count}\t{t.note or ''}")
        for rv in session.scalars(select(RouteVersion)):
            n = session.scalar(select(RoutePathPoint.path_seq).where(RoutePathPoint.route_version_id == rv.route_version_id).order_by(RoutePathPoint.path_seq.desc()).limit(1))
            if n:
                segs = list(session.scalars(select(RouteStopSegment.verification_status).where(RouteStopSegment.route_version_id == rv.route_version_id)))
                print(f"경로 {_pattern_label(session, rv.route_version_id)}: {n}점, 구간 {len(segs)}개 (verified {segs.count('verified')})")


if __name__ == "__main__":
    main()
