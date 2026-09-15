"""원문 행 해석 (04 2장).

X의 의미는 앞뒤 칸에 시각이 있는가로만 가른다.
  - 첫 시각 앞 X          → before_origin (기점 이전). 방문을 만들지 않는다
  - 시각과 시각 사이 X    → not_visited (미방문). 원문에 사례 없음. 별도 패턴 등록 대상이므로 생성하지 않는다
  - 마지막 시각 뒤 X      → unresolved. 기점·종점 추정에 쓰지 않는다
"""

from dataclasses import dataclass, field
from datetime import time

from app.timetable.source_2026_2 import (
    CAMPUS,
    PATTERNS,
    STUDENT_UNION,
    PatternDef,
    SourceRow,
    SourceTable,
)
from app.timetable.source_2026_2 import TABLES as SOURCE_TABLES
from app.timeutil import parse_hhmm

TERM_KEY = "2026-2"
X = "X"
VIA = "경유"

WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri")


@dataclass(frozen=True)
class StopTime:
    pattern_seq: int
    event_type: str  # arrival / departure / unspecified
    raw_value: str

    @property
    def time(self) -> time:
        return parse_hhmm(self.raw_value)


@dataclass
class TripDef:
    day_type: str
    route: str
    pattern: str
    trip_no: int
    source_row_key: str
    source_reference: str
    origin_seq: int | None
    times: list[StopTime]
    source_cells: dict
    excluded_weekdays: list[str]
    vehicle_count_by_weekday: dict[str, int]
    note: str | None
    issues: list[str] = field(default_factory=list)

    @property
    def origin_verified(self) -> bool:
        return self.origin_seq is not None and not self.issues


def pattern_def(route: str, code: str) -> PatternDef:
    for p in PATTERNS:
        if p.route == route and p.code == code:
            return p
    raise KeyError((route, code))


def classify_cells(cells: tuple[str, ...]) -> list[str]:
    """각 칸을 time / via / before_origin / not_visited / unresolved로 분류한다."""
    is_time = [c not in (X, VIA) for c in cells]
    if not any(is_time):
        return ["unresolved" if c == X else "via" for c in cells]
    first = is_time.index(True)
    last = len(cells) - 1 - is_time[::-1].index(True)
    kinds = []
    for i, c in enumerate(cells):
        if is_time[i]:
            kinds.append("time")
        elif c == VIA:
            kinds.append("via")
        elif i < first:
            kinds.append("before_origin")
        elif i < last:
            kinds.append("not_visited")
        else:
            kinds.append("unresolved")
    return kinds


def _vehicle_counts(day_type: str, row: SourceRow) -> dict[str, int]:
    if day_type == "weekday":
        counts = {k: 1 for k in WEEKDAY_KEYS}
        counts.update(row.vehicles)
        return counts
    return {"saturday": {"sat": 1}, "sunday_holiday": {"sun": 1}}[day_type]


def parse_row(table: SourceTable, row: SourceRow) -> TripDef:
    kinds = classify_cells(row.cells)
    table_pattern = pattern_def(table.route, table.pattern)
    issues = [
        f"{col.label} 칸 X가 시각 사이에 있음 — 미방문. 별도 패턴 등록 필요"
        for col, kind in zip(table.columns, kinds)
        if kind == "not_visited"
    ] + [
        f"{col.label} 칸 X를 판별할 수 없음"
        for col, kind in zip(table.columns, kinds)
        if kind == "unresolved"
    ]

    remark = row.remark_origin
    pattern = pattern_def(table.route, remark.pattern) if remark else table_pattern

    times: list[StopTime] = []
    origin_seq: int | None = None
    if remark:
        origin_seq = pattern.stops.index(remark.stop) + 1
        times.append(StopTime(origin_seq, "departure", remark.time))

    for col, kind, raw in zip(table.columns, kinds, row.cells):
        if kind != "time":
            continue
        stop_name = table_pattern.stops[col.pattern_seq - 1]
        if remark:
            # 원래 열의 정거장을 중간노선 패턴에서 기점 뒤 방문으로 찾는다
            candidates = [i + 1 for i, s in enumerate(pattern.stops) if s == stop_name and i + 1 > origin_seq]
            if not candidates:
                issues.append(f"{col.label} 시각을 비고 기점 패턴에 연결할 수 없음")
                continue
            seq = candidates[0]
        else:
            seq = col.pattern_seq
        if origin_seq is None:
            origin_seq = seq
        if seq == origin_seq:
            event_type = "departure"
        elif seq == len(pattern.stops):
            event_type = "arrival"
        else:
            # 외부 정거장 열의 시각은 도착·출발 의미가 확인되지 않았다 (04 11장)
            event_type = "unspecified"
        times.append(StopTime(seq, event_type, raw))

    if issues:
        origin_seq = None

    source_cells = {
        "columns": [
            {"label": col.label, "raw": raw, "interpretation": kind}
            for col, raw, kind in zip(table.columns, row.cells, kinds)
        ],
        "friday": None if table.day_type != "weekday" else ("○" if row.friday_runs else "✕"),
        "remark": remark.raw if remark else None,
        "note": row.note,
    }

    return TripDef(
        day_type=table.day_type,
        route=table.route,
        pattern=pattern.code,
        trip_no=row.trip_no,
        source_row_key=f"{TERM_KEY}:{table.day_type}:{table.route}:{row.trip_no}",
        source_reference=table.source_reference,
        origin_seq=origin_seq,
        times=times,
        source_cells=source_cells,
        excluded_weekdays=[] if row.friday_runs else ["fri"],
        vehicle_count_by_weekday=_vehicle_counts(table.day_type, row),
        note=row.note,
        issues=issues,
    )


def parse_all(tables: list[SourceTable] = SOURCE_TABLES) -> list[TripDef]:
    return [parse_row(t, r) for t in tables for r in t.rows]


# ---------- 학생회관 승차 창 (04 7장, 10 6장) ----------

WINDOW_AFTERNOON = (time(13, 30), time(15, 30))  # 양 끝 포함
WINDOW_EVENING_START = time(19, 30)  # [19:30, 24:00)


def student_union_applies(day_type: str, route: str, campus_departure: time | None) -> bool | None:
    """True=해당, False=해당 없음, None=확인 필요(표시하지 않음).

    판정 기준은 캠퍼스 출발 공시 시각이며 조회 시각이 아니다.
    """
    if day_type != "weekday":
        return None  # 휴일 시간표에는 안내가 없다
    if route == "onyang":
        return None  # 원본 표기 불명확
    if campus_departure is None:
        return False  # 캠퍼스 출발이 없는 회차(중간노선 전용·외부 기점)는 비교할 시각이 없다
    start, end = WINDOW_AFTERNOON
    return start <= campus_departure <= end or campus_departure >= WINDOW_EVENING_START


def campus_departure_of(trip: TripDef) -> time | None:
    pattern = pattern_def(trip.route, trip.pattern)
    for st in trip.times:
        if st.event_type == "departure" and pattern.stops[st.pattern_seq - 1] == CAMPUS:
            return st.time
    return None


def note_says_student_union(trip: TripDef) -> bool:
    return bool(trip.note and STUDENT_UNION in trip.note)
