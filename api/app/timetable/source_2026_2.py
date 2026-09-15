"""2026-2학기 셔틀버스 시간표 원문 (04 4·5·7·8장).

숫자와 표기는 PDF 그대로다. 해석하지 않은 칸 값만 둔다 — X·경유·시각·비고는
parse.py가 판별한다. 이 파일의 값을 바꾸면 04 5장과 대조 시험이 실패해야 한다.
"""

from dataclasses import dataclass, field
from datetime import date

SOURCE_WEEKDAY = "2026-2학기 셔틀버스 시간표_평일.pdf p1"
SOURCE_HOLIDAY = "2026-2학기 셔틀버스 시간표_휴일.pdf p1"

CAMPUS = "아산캠퍼스"
SUNMOON = "선문대"  # 휴일 천안터미널 열 표기. 아산캠퍼스와 같은 지점임을 사용자가 확인 (2026-09-15)

# MVP 노선 (00 3장, 2026-09-15 결정)
MVP_ROUTE = "cheonan_asan"

# ---------- 정거장 ----------

NEEDS_INTERPRETATION_STOPS = {"펜타포트"}

# 승하차 가능한 주요 외부 정거장 — 시간표 열에 시각이 공시된 외부 정거장 (2026-09-15 사용자 확인).
# 이 정거장의 모든 중간 방문은 승차·하차 allowed. 그 밖의 경유지는 계속 unknown (04 1장)
MAJOR_EXTERNAL_STOPS = {
    "천안아산역",
    "천안역",
    "천안터미널",
    "주은아파트 버스정류장",
    "온양온천역",
    "아산터미널",
}

STOP_NAMES = [
    CAMPUS,
    "탕정역",
    "시티프라디움",
    "천안아산역",
    "월봉청솔1단지",
    "쌍용동하이마트",
    "천안역",
    "하이렉스파건너편",
    "용암마을",
    "펜타포트",
    "불당상업지구 입구",
    "그린빌아파트",
    "한방병원 건너편",
    "천안터미널",
    "두정동 맥도날드",
    "홈마트 에브리데이",
    "서울대정병원",
    "갤러리아 건너편",
    "주은아파트 버스정류장",
    "온양온천역",
    "아산터미널",
    "권곡초 버스정류장",
]

# ---------- 노선·패턴 (04 4장, 9장) ----------

ROUTES = {
    "cheonan_asan": ("천안아산역", "천안아산역"),
    "cheonan": ("천안역", "천안역"),
    "terminal": ("천안터미널", "터미널"),
    "onyang": ("온양온천역", "온양온천역"),
}

WEEKDAY_RANGE = (date(2026, 9, 1), date(2026, 12, 14))
HOLIDAY_RANGE = (date(2026, 9, 5), date(2026, 12, 13))


@dataclass(frozen=True)
class PatternDef:
    route: str
    code: str
    direction: str
    stops: tuple[str, ...]
    effective: tuple[date, date]
    verification_status: str = "verified"
    note: str | None = None


TERMINAL_MIDDLE = (
    "불당상업지구 입구",
    "그린빌아파트",
    "한방병원 건너편",
    "천안터미널",
    "두정동 맥도날드",
    "홈마트 에브리데이",
    "서울대정병원",
    "갤러리아 건너편",
)

PATTERNS = [
    PatternDef("cheonan_asan", "general", "round_trip",
               (CAMPUS, "탕정역", "시티프라디움", "천안아산역", CAMPUS),
               (WEEKDAY_RANGE[0], WEEKDAY_RANGE[1]), note="평일·토·일 공통"),
    PatternDef("cheonan", "weekday_general", "round_trip",
               (CAMPUS, "월봉청솔1단지", "쌍용동하이마트", "천안역", "하이렉스파건너편", "용암마을", CAMPUS),
               WEEKDAY_RANGE),
    PatternDef("cheonan", "holiday_general", "round_trip",
               (CAMPUS, "펜타포트", "천안아산역", "월봉청솔1단지", "쌍용동하이마트", "천안역",
                "하이렉스파건너편", "용암마을", "천안아산역", CAMPUS),
               HOLIDAY_RANGE),
    PatternDef("cheonan", "middle_only", "to_campus",
               ("하이렉스파건너편", "용암마을", CAMPUS),
               WEEKDAY_RANGE, note="중간노선 전용 — 평일 순5"),
    PatternDef("terminal", "general", "round_trip",
               (CAMPUS, *TERMINAL_MIDDLE, CAMPUS), WEEKDAY_RANGE,
               note="평일·토·일 공통. 휴일 표의 '선문대'는 아산캠퍼스"),
    PatternDef("terminal", "middle_only", "to_campus",
               ("두정동 맥도날드", "홈마트 에브리데이", "서울대정병원", "갤러리아 건너편", CAMPUS),
               WEEKDAY_RANGE, note="중간노선 전용 — 평일 순9"),
    PatternDef("onyang", "general", "round_trip",
               (CAMPUS, "주은아파트 버스정류장", "온양온천역", "아산터미널", "권곡초 버스정류장", CAMPUS),
               WEEKDAY_RANGE),
]

# ---------- 시간표 원문 행 ----------


@dataclass(frozen=True)
class Column:
    """표의 열 하나. pattern_seq는 해당 패턴에서의 방문 순번(1부터)."""

    label: str
    pattern_seq: int


@dataclass(frozen=True)
class RemarkOrigin:
    """비고 칸에 적힌 실제 기점 (중간노선 전용)."""

    pattern: str
    stop: str
    time: str
    raw: str


@dataclass(frozen=True)
class SourceRow:
    trip_no: int
    cells: tuple[str, ...]
    vehicles: dict[str, int] = field(default_factory=dict)  # 기본 1대에서 달라지는 요일만
    friday_runs: bool = True
    note: str | None = None
    remark_origin: RemarkOrigin | None = None


@dataclass(frozen=True)
class SourceTable:
    day_type: str
    route: str
    pattern: str
    columns: tuple[Column, ...]
    rows: tuple[SourceRow, ...]
    source_reference: str


def _rows(spec: str) -> list[tuple[str, ...]]:
    return [tuple(line.split()) for line in spec.strip().splitlines()]


def _simple_rows(spec: str) -> tuple[SourceRow, ...]:
    """휴일 표: '순 출발 중간 도착'."""
    return tuple(SourceRow(int(r[0]), tuple(r[1:])) for r in _rows(spec))


STUDENT_UNION = "학생회관"

# A-1 천안아산역 — 순 | 캠퍼스 출발 | 천안아산역 | 캠퍼스 도착 | 금 | 비고
_A1 = """
1 8:05 8:25 8:40 ○
2 X 8:35 8:50 ✕
3 X 8:40 8:55 ✕
4 X 8:45 9:00 ○
5 X 8:50 9:05 ✕
6 X 8:55 9:10 ○
7 X 9:00 9:15 ○
8 X 9:05 9:20 ✕
9 X 9:10 9:25 ○
10 X 9:15 9:30 ✕
11 9:30 9:50 10:05 ○
12 9:50 10:10 10:25 ○
13 10:20 10:40 10:55 ✕
14 10:30 10:50 11:05 ✕
15 10:45 11:05 11:20 ○
16 10:55 11:15 11:30 ✕
17 11:25 11:45 12:00 ✕
18 11:45 12:05 12:20 ○
19 12:15 12:35 12:50 ✕
20 12:35 12:55 13:10 ✕
21 13:10 13:30 13:45 ○
22 13:40 14:00 14:15 ○ 학생회관
23 13:50 14:10 14:25 ✕ 학생회관
24 14:40 15:00 15:15 ○ 학생회관
25 14:50 15:10 15:25 ✕ 학생회관
26 15:30 15:50 16:05 ○ 학생회관
27 15:35 15:55 16:10 ✕
28 15:40 16:00 16:15 ○
29 15:50 16:10 16:25 ✕
30 16:30 16:50 17:05 ✕
31 16:40 17:00 17:15 ○
32 16:50 17:10 17:25 ✕
33 17:00 17:20 17:35 ○
34 17:30 17:50 18:05 ✕
35 17:40 18:00 18:15 ○
36 17:50 18:10 18:25 ✕
37 18:15 18:35 18:50 ✕
38 18:35 18:55 19:10 ○
39 18:45 19:05 19:20 ✕
40 19:45 20:05 20:20 ○ 학생회관
41 20:45 21:05 21:20 ○ 학생회관
42 21:15 21:35 21:50 ○ 학생회관
"""

# 2대 운행 (04 5장 A): 순4 월~화, 순7 월~목
_A1_VEHICLES = {
    4: {"mon": 2, "tue": 2},
    7: {"mon": 2, "tue": 2, "wed": 2, "thu": 2},
}

# A-2 천안역 — 순 | 캠퍼스 출발 | 천안역 | 캠퍼스 도착 | 금 | 비고
_A2 = """
1 7:40 8:15 8:45 ○
2 X 8:30 9:00 ✕
3 X 8:40 9:10 ○
4 X 8:45 9:15 ✕
5 X X 9:05 ○
6 X 8:50 9:20 ○
7 X 9:00 9:30 ✕
8 X 9:05 9:35 ○
9 X 9:30 9:55 ✕
10 9:30 10:00 10:25 ○
11 10:00 10:30 10:55 ✕
12 10:10 10:40 11:05 ○
13 10:30 11:00 11:25 ✕
14 11:00 11:30 11:55 ○
15 11:30 12:00 12:25 ✕
16 12:30 13:00 13:25 ○
17 13:30 14:00 14:25 ✕ 학생회관
18 13:40 14:10 14:35 ○ 학생회관
19 14:30 15:00 15:25 ✕ 학생회관
20 14:40 15:10 15:35 ○ 학생회관
21 15:30 16:00 16:25 ✕ 학생회관
22 15:40 16:10 16:35 ○
23 15:50 16:20 16:45 ✕
24 16:30 17:00 17:25 ✕
25 16:40 17:10 17:35 ○
26 16:50 17:20 17:45 ✕
27 17:40 18:15 18:45 ○
28 17:50 18:25 18:55 ✕
29 18:40 19:15 19:45 ○
30 18:50 19:25 19:50 ✕
31 19:30 19:55 20:20 ○ 학생회관
32 20:30 20:55 21:20 ○ 학생회관
33 21:20 21:45 22:10 ✕ 학생회관
"""

# A-3 천안터미널 — 순 | 캠퍼스 출발 | 터미널 | 캠퍼스 도착 | 금 | 비고
_A3 = """
1 7:30 8:10 8:50 ○
2 X 8:15 8:55 ✕
3 X 8:25 9:05 ○
4 X 8:30 9:10 ✕
5 X 8:35 9:15 ○
6 X 8:40 9:20 ✕
7 X 8:45 9:25 ○
8 X 8:50 9:30 ✕
9 X X 9:10 ○
10 X 9:30 10:00 ○
11 9:30 10:00 10:30 ○
12 10:00 10:30 11:00 ✕
13 10:30 11:00 11:30 ○
14 11:00 11:30 12:00 ✕
15 11:30 12:00 12:30 ○
16 12:00 12:30 13:00 ✕
17 12:30 13:00 13:30 ○
18 13:00 13:30 14:00 ✕
19 13:30 14:00 14:30 ○ 학생회관
20 13:50 14:20 14:50 ✕ 학생회관
21 14:30 15:00 15:30 ✕ 학생회관
22 14:40 15:10 15:40 ○ 학생회관
23 14:50 15:20 15:50 ✕ 학생회관
24 15:30 16:00 16:30 ✕ 학생회관
25 15:40 16:10 16:40 ○
26 15:50 16:20 16:50 ✕
27 16:30 17:10 17:50 ✕
28 16:40 17:20 18:00 ○
29 16:50 17:30 18:10 ✕
30 17:30 18:10 18:50 ✕
31 17:40 18:20 19:00 ○
32 17:50 18:30 19:10 ✕
33 18:30 19:10 19:50 ✕
34 18:40 19:20 20:00 ○
35 18:50 19:30 20:10 ✕
36 19:40 20:10 20:40 ○ 학생회관
37 20:40 21:10 21:40 ○ 학생회관
38 21:30 22:00 22:30 ✕ 학생회관
"""

# A-4 온양온천역 — 순 | 캠퍼스 출발 | 주은아파트 | 온양온천역 | 아산터미널 | 권곡초 | 캠퍼스 도착 | 금
_A4 = """
1 X 8:00 8:10 8:15 경유 8:40 ○
2 X X 8:45 8:50 경유 9:15 ✕
3 X 8:40 8:50 8:55 경유 9:20 ○
4 10:25 경유 10:55 11:00 경유 11:20 ○
5 15:30 경유 16:00 16:05 경유 16:25 ○
6 17:30 경유 18:00 18:05 경유 18:25 ✕
7 18:30 경유 19:00 19:05 경유 19:25 ○
"""

_REMARK_ORIGINS = {
    ("cheonan", 5): RemarkOrigin("middle_only", "하이렉스파건너편", "8:50",
                                 "중간노선 전용 — 하이렉스파건너편 8:50 출발"),
    ("terminal", 9): RemarkOrigin("middle_only", "두정동 맥도날드", "8:55",
                                  "중간노선 전용 — 두정동 맥도날드 8:55 출발"),
}


def _weekday_rows(route: str, spec: str, n_cells: int, vehicles: dict[int, dict[str, int]] | None = None):
    rows = []
    for r in _rows(spec):
        trip_no = int(r[0])
        cells = r[1 : 1 + n_cells]
        fri = r[1 + n_cells]
        notes = r[2 + n_cells :]
        assert fri in ("○", "✕"), (route, trip_no, fri)
        remark = _REMARK_ORIGINS.get((route, trip_no))
        note_parts = list(notes)
        if remark:
            note_parts.append(remark.raw)
        rows.append(
            SourceRow(
                trip_no=trip_no,
                cells=tuple(cells),
                vehicles=(vehicles or {}).get(trip_no, {}),
                friday_runs=fri == "○",
                note=" · ".join(note_parts) or None,
                remark_origin=remark,
            )
        )
    return tuple(rows)


def _cols(*spec: tuple[str, int]) -> tuple[Column, ...]:
    return tuple(Column(label, seq) for label, seq in spec)


_ASAN_COLS = _cols(("캠퍼스 출발", 1), ("천안아산역", 4), ("캠퍼스 도착", 5))
_CHEONAN_WEEKDAY_COLS = _cols(("캠퍼스 출발", 1), ("천안역", 4), ("캠퍼스 도착", 7))
_CHEONAN_HOLIDAY_COLS = _cols(("캠퍼스 출발", 1), ("천안역", 6), ("캠퍼스 도착", 10))
_TERMINAL_WEEKDAY_COLS = _cols(("캠퍼스 출발", 1), ("터미널", 5), ("캠퍼스 도착", 10))
_TERMINAL_HOLIDAY_COLS = _cols(("선문대(출발)", 1), ("터미널", 5), ("선문대(도착)", 10))
_ONYANG_COLS = _cols(
    ("캠퍼스 출발", 1), ("주은아파트", 2), ("온양온천역", 3), ("아산터미널", 4), ("권곡초", 5), ("캠퍼스 도착", 6)
)

TABLES: list[SourceTable] = [
    # A. 평일
    SourceTable("weekday", "cheonan_asan", "general", _ASAN_COLS,
                _weekday_rows("cheonan_asan", _A1, 3, _A1_VEHICLES), SOURCE_WEEKDAY),
    SourceTable("weekday", "cheonan", "weekday_general", _CHEONAN_WEEKDAY_COLS,
                _weekday_rows("cheonan", _A2, 3), SOURCE_WEEKDAY),
    SourceTable("weekday", "terminal", "general", _TERMINAL_WEEKDAY_COLS,
                _weekday_rows("terminal", _A3, 3), SOURCE_WEEKDAY),
    SourceTable("weekday", "onyang", "general", _ONYANG_COLS,
                _weekday_rows("onyang", _A4, 6), SOURCE_WEEKDAY),
    # B. 토요일
    SourceTable("saturday", "cheonan_asan", "general", _ASAN_COLS, _simple_rows("""
1 8:00 8:20 8:35
2 12:00 12:20 12:35
3 16:10 16:30 16:45
4 18:20 18:40 18:55
"""), SOURCE_HOLIDAY),
    SourceTable("saturday", "cheonan", "holiday_general", _CHEONAN_HOLIDAY_COLS, _simple_rows("""
1 8:00 8:30 9:00
2 12:00 12:30 13:00
3 16:00 16:30 17:00
4 18:10 18:40 19:10
"""), SOURCE_HOLIDAY),
    SourceTable("saturday", "terminal", "general", _TERMINAL_HOLIDAY_COLS, _simple_rows("""
1 8:00 8:30 9:00
2 12:00 12:30 13:00
3 16:00 16:30 17:00
4 18:00 18:30 19:00
"""), SOURCE_HOLIDAY),
    # C. 일요일·공휴일
    SourceTable("sunday_holiday", "cheonan_asan", "general", _ASAN_COLS, _simple_rows("""
1 9:00 9:20 9:35
2 12:00 12:20 12:35
3 16:10 16:30 16:45
4 18:20 18:40 18:55
5 19:10 19:30 19:45
6 20:00 20:20 20:35
"""), SOURCE_HOLIDAY),
    SourceTable("sunday_holiday", "cheonan", "holiday_general", _CHEONAN_HOLIDAY_COLS, _simple_rows("""
1 9:00 9:30 10:00
2 12:00 12:30 13:00
3 16:00 16:30 17:00
4 18:10 18:40 19:10
5 19:00 19:30 20:00
"""), SOURCE_HOLIDAY),
    SourceTable("sunday_holiday", "terminal", "general", _TERMINAL_HOLIDAY_COLS, _simple_rows("""
1 9:00 9:30 10:00
2 12:00 12:30 13:00
3 16:00 16:30 17:00
4 18:00 18:30 19:00
5 19:30 20:00 20:30
"""), SOURCE_HOLIDAY),
]

# ---------- 템플릿·자료 범위·예외 (04 3·8·9장, 05 3장) ----------

TEMPLATES = {
    "weekday": ("2026-2학기 평일", WEEKDAY_RANGE, SOURCE_WEEKDAY),
    "saturday": ("2026-2학기 토요일", HOLIDAY_RANGE, SOURCE_HOLIDAY),
    "sunday_holiday": ("2026-2학기 일요일·공휴일", HOLIDAY_RANGE, SOURCE_HOLIDAY),
}

# 노선별 원문 행 수 (04 12장 FR-RD-01·03). 적재 결과와 독립된 기대값이라 부분 적재를 잡아낸다
EXPECTED_TRIP_COUNTS = {
    ("weekday", "cheonan_asan"): 42,
    ("weekday", "cheonan"): 33,
    ("weekday", "terminal"): 38,
    ("weekday", "onyang"): 7,
    ("saturday", "cheonan_asan"): 4,
    ("saturday", "cheonan"): 4,
    ("saturday", "terminal"): 4,
    ("sunday_holiday", "cheonan_asan"): 6,
    ("sunday_holiday", "cheonan"): 5,
    ("sunday_holiday", "terminal"): 5,
}

# 휴일 원본의 전체 노선 범위를 확인해 온양 미운행을 명시 등록한다 (04 13장)
NO_SERVICE_COVERAGE = {("saturday", "onyang"), ("sunday_holiday", "onyang")}


@dataclass(frozen=True)
class ExceptionDef:
    day: date
    exception_type: str
    note: str
    alternate_day_type: str | None = None


EXCEPTIONS = [
    ExceptionDef(date(2026, 9, 24), "no_service", "추석연휴"),
    ExceptionDef(date(2026, 9, 25), "no_service", "추석연휴"),
    ExceptionDef(date(2026, 9, 26), "no_service", "추석연휴"),
    ExceptionDef(date(2026, 10, 3), "no_service", "개천절연휴"),
    ExceptionDef(date(2026, 10, 4), "no_service", "개천절연휴"),
    ExceptionDef(date(2026, 10, 5), "alternate_schedule", "개천절 대체휴일, 일요일 시간표 적용", "sunday_holiday"),
    ExceptionDef(date(2026, 10, 9), "no_service", "한글날"),
    ExceptionDef(date(2026, 10, 28), "no_service", "개교기념일"),
]
EXCEPTION_SOURCE = f"{SOURCE_WEEKDAY}; {SOURCE_HOLIDAY} 공휴일 안내"


@dataclass(frozen=True)
class RangeAnnotation:
    route: str
    trip_no: int
    covered_stops: tuple[str, ...]
    raw_text: str
    min_seconds: int
    max_seconds: int
    reference_stop: str | None


# 04 6장 평일 중간노선 안내. '5~20분' 안내는 위치를 특정할 원문 표기가 없어 등록하지 않았다
ANNOTATIONS = [
    RangeAnnotation("cheonan", 5, ("하이렉스파건너편", "용암마을"), "2~5분", 120, 300, None),
    RangeAnnotation("terminal", 9, ("홈마트 에브리데이", "서울대정병원", "갤러리아 건너편"), "5~10분", 300, 600, None),
]
