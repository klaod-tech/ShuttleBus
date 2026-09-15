# 05 · 운행 달력

> **어떤 날짜에 무엇이 운행하는가**를 판정하고, 날짜별 회차와 차량 슬롯을 생성한다.
> 참조: [공통 규약](01-conventions.md) · [기준 데이터](04-reference-data.md)

기준 데이터(`04`)는 요일 유형·적용 기간을 가진 템플릿이고, 이 문서는 그것을 **실제 날짜에 적용**한다.

---

## 1. `schedule_status` — 네 가지 상태

| 값 | 의미 | 학생 화면 |
|---|---|---|
| `available` | 자료가 있고 예외도 없다 | 회차 목록 표시 |
| `no_service` | 학교가 명시한 휴무 | "오늘 운행 없음"과 근거 |
| `unknown` | 참조할 시간표 자료가 없다 | "시간표 확인 필요" |
| `out_of_period` | 등록된 시간표 적용 기간 밖 | "적용 기간 밖" |

**`unknown`과 `no_service`는 완전히 다르다.** 전자는 우리가 모르는 것이고 후자는 학교가 안 다닌다고 한 것이다. 섞으면 실제로는 운행하는 날에 "운행 없음"을 띄우게 된다.

**`unknown`을 HTTP 404로 처리하지 않는다.** 200 응답의 `schedule_status`로 표현한다. 404는 존재하지 않는 리소스에만 쓴다 (`01` 5장).

## 2. 판정 절차

`resolve_service_calendar(route_id, service_date)` — 서울 날짜 기준. **서버 시간대에 의존하지 않는다.**

```
1. 학기 범위 확인
   service_date ∉ [2026-09-01, 2026-12-14]  →  out_of_period
   (양 끝 포함)

2. 학교 운행 예외 확인 — 최우선
   schedule_exceptions에 해당 날짜가 있으면
     exception_type = no_service          →  no_service
     exception_type = alternate_schedule  →  3단계로, 참조 템플릿 교체

3. 적용할 템플릿 결정
   대체 지정이 있으면 그 템플릿
   없으면 요일로 결정:
     월~금 → weekday
     토    → saturday
     일    → sunday_holiday

4. 템플릿 유효기간 확인
   service_date ∉ [template.effective_from, template.effective_to]  →  unknown

5. 템플릿 자료 상태 확인
   data_status ≠ available  →  unknown

6. 해당 노선의 자료 범위 확인
   coverage_status = confirmed_no_service → no_service (확인 근거 필수)
   coverage_status = unknown 또는 행 없음 → unknown
   confirmed_service인데 회차 누락·대수 키 오류·미검증 기점이 있으면 → unknown
   (빈 trip_templates 배열 자체를 미운행 근거로 사용하지 않음)

7. 그 외  →  available
```

### 판정에서 지키는 것

- **일반 국가 공휴일 달력만으로 학교 운행을 추정하지 않는다.** 학교가 명시한 예외만 쓴다.
- **대체 시간표는 참조한 `day_type`의 규칙으로 평가한다.** 10/5는 월요일이지만 `sunday_holiday` 규칙을 적용하며, 월요일 조건(예: 천안아산역 순4 2대)을 끌어오지 않는다.
- 2단계가 3단계보다 앞선다. **주말이라도 명시 휴무면 `no_service`가 우선한다.** 09/26·10/03·10/04가 여기 해당한다.
- 6단계는 노선별이다. 같은 날짜라도 노선에 따라 `available`과 `no_service`가 갈릴 수 있다.

### 2026-2학기 판정 예시

| 날짜 | 요일 | 노선 | 결과 | 근거 |
|---|---|---|---|---|
| 09-10 | 목 | 천안아산역 | `available` | 평일 템플릿 |
| 09-05 | 토 | 천안아산역 | `available` | 토요일 템플릿, 유효기간 시작일 |
| 09-05 | 토 | 온양온천역 | `no_service` | 휴일 원본의 전체 노선 범위 검수에 따른 명시적 미운행 등록 |
| 09-24 | 목 | 전체 | `no_service` | 추석연휴 명시 |
| 09-26 | 토 | 전체 | `no_service` | 명시 휴무가 토요일 템플릿보다 우선 |
| 10-05 | 월 | 천안역 | `available` | 대체 지정 → `sunday_holiday` 템플릿 |
| 10-09 | 금 | 전체 | `no_service` | 한글날 명시 |
| 08-31 | 월 | 전체 | `out_of_period` | 학기 시작 전 |
| 09-02 | 수 | 천안아산역 | `available` | 평일 |

**10/5가 `unknown`에서 해소됐다.** 일요일 시간표를 확보하기 전에는 참조 대상이 없어 `unknown`이었다.

## 3. 데이터 모델

| 테이블 | 주요 열 |
|---|---|
| `schedule_exceptions` | `exception_id`, `exception_date`, `route_id`(범위. null이면 전체 노선), `exception_type`, `alternate_schedule_template_id`, `source_reference`, `note`. `UNIQUE (exception_date, route_id) NULLS NOT DISTINCT` |
| `service_calendar` | `service_date`, `route_id`, `schedule_status`, `reason`, `applied_schedule_template_id`, `actual_weekday`, `effective_service_weekday`, `effective_day_type`, `resolved_at` |
| `schedule_route_coverage` | 키 `(schedule_template_id, route_id)`; `coverage_status`(confirmed_service/confirmed_no_service/unknown), `source_reference`, `verified_at`, `expected_trip_count`, `note` |
| `scheduled_trips` | `scheduled_trip_id`, `trip_template_id`, `service_date`, `route_version_id`, `origin_trip_stop_id`, `operation_status`, `scheduled_vehicle_count`, `state_version`, `control_version`, `source_row_key` |
| `scheduled_trip_stops` | `trip_stop_id`, `scheduled_trip_id`, `route_stop_id`, `stop_sequence`, 공시 도착·출발·미분류 시각, `boarding_policy`, `alighting_policy`, `verification_status` |
| `trip_vehicles` | `trip_vehicle_id`, `scheduled_trip_id`, `vehicle_slot`, nullable `shuttle_id`, `operation_status`, `information_status`, nullable `departure_observation_event_id` |

### 예외 충돌 방지

- 같은 범위·같은 날짜의 중복 예외를 금지한다.
- **노선 전용 예외가 전체 예외보다 우선한다.**
- 날짜별 공지 근거(`source_reference`)와 최종 선택을 기록한다.
- 학기 밖 운행은 새 유효 시간표 없이는 생성하지 않는다.

### `service_calendar`는 캐시가 아니다

판정 결과를 저장하고 `resolved_at`을 남긴다. 시간표가 개정되면 영향받은 날짜를 다시 판정한다. **과거 날짜의 판정 결과는 보존한다** — 그날 학생에게 무엇을 보여줬는지가 이력이다.

## 4. 회차 생성

`ensure_scheduled_trips(route_id, from_date, to_date)` — 멱등이다.

```
각 날짜에 대해
  resolve_service_calendar → available 인 날짜만 생성

  적용 템플릿의 trip_templates 중
    excluded_weekdays에 effective_service_weekday가 없는 것만 선택

  각 trip_template에 대해
    scheduled_trips 1행 생성
    scheduled_trip_stops = route_version의 route_stops 복사
      (기점 이전 방문은 제외)
    scheduled_stop_times의 공시 시각을 날짜와 결합해 채움
    trip_vehicles = vehicle_count_by_weekday[effective_service_weekday] 만큼 슬롯 생성
    필요한 키 누락·0대·비정수이면 생성하지 않고 자료 오류로 남김
```

### 중복 방지

- `UNIQUE (trip_template_id, service_date)`
- 템플릿 버전이 수정되어도 같은 원본 행이 두 번 생성되지 않도록 `source_row_key`도 함께 관리한다.
- **금요일 표를 별도 템플릿으로 등록하지 않는다.** 같은 원본 행에 `excluded_weekdays`로 조건을 건다.

### 기점 이전 방문은 넣지 않는다

회차가 실제로 제공하지 않는 방문은 `scheduled_trip_stops`에 만들지 않는다.

| 회차 | 기점 | 제외되는 방문 |
|---|---|---|
| 평일 천안아산역 순2 | 천안아산역 08:35 | 캠퍼스 출발, 탕정역, 시티프라디움 |
| 평일 천안역 순5 | 하이렉스파건너편 08:50 | 그 앞 전부 (중간노선 전용 패턴) |
| 평일 온양 순2 | 온양온천역 08:45 | 캠퍼스 출발, 주은아파트 |

온양 순2의 주은아파트는 **기점 이전**이다 — X 뒤쪽 온양온천역에 시각이 있다 (`04` 2장). 캠퍼스 출발과 같은 이유로 제외되므로 이 표의 다른 행과 처리가 같다. 원문 재확인 상태를 함께 관리한다.

### 차량 슬롯

한 행은 시간표상 출발 묶음이며 차량 실측 기록이 아니다. **실제 차량 번호가 없어도 슬롯은 생성한다.**

| 요일 | 슬롯 수 | 근거 |
|---|---|---|
| 월·화 | 122 | 120행 + 천안아산역 순4·순7 각 1대 추가 |
| 수·목 | 121 | 120행 + 순7 1대 추가 |
| 금 | 61 | 추가 차량 없음 |
| 토 | 12 | 추가 차량 없음 |
| 일 | 16 | 추가 차량 없음 |

**예정 대수를 수집 세션 수에서 추론하지 않는다.** 한 대만 동승해도 슬롯은 둘이다.

## 5. 보충 생성과 개정

### CronJob 보충

학기 중 오늘부터 일정 범위 앞까지를 생성한다. 실행 시점은 세 가지다.

1. 서비스 시작 시
2. 정기 실행 (매일)
3. 요청 시 — 조회 대상 날짜가 미생성이면 즉시 보충

**CronJob이 실패해 며칠 누락돼도 다음 실행이 메운다.** 멱등이므로 중복 생성되지 않는다.

### 시간표 개정

- **미수집·미시작 미래 회차만 재조정한다.**
- 이미 수집을 시작한 회차는 예정 출발 전이라도 경로·시각을 조용히 교체하지 않는다.
- 이미 수집한 과거 회차는 시각·방문·버전을 그대로 보존한다.
- 이미 공개한 회차를 취소하면 사유와 상태 변경을 전송한다 (`13`).
- 노선 개정은 새 `route_version`으로 남기고, 과거 회차는 자기 `route_version_id`를 계속 참조한다.

## 6. 다음 운행일 안내

오늘 남은 회차가 없거나 오늘이 `available`이 아닐 때, 다음 운행일을 안내한다.

```
next_known_service_date        확인된 시간표가 있는 다음 날짜
has_unknown_dates_before       그 사이에 unknown 날짜가 있었는가
```

**자료 없는 날짜를 건너뛰어 먼 미래 회차를 '바로 다음 버스'라고 안내하지 않는다.** `has_unknown_dates_before = true`면 화면은 "다음 확인된 시간표"로만 표현한다 (`03` 6장).

현재 세 템플릿 자료를 확보했지만 부분 등록·미검증 기점·잘못된 대수 설정이면 학기 중에도 `unknown`이 가능하다. 다음 학기 시간표를 등록하기 전까지 12/15 이후는 `out_of_period`다.

## 7. API

| 경로 | 입력 | 응답 |
|---|---|---|
| `GET /service-calendar` | `route_id`, `from_date`, `to_date` | 날짜별 `schedule_status`, 사유, 적용 템플릿 |
| `GET /routes` | — | 노선 목록 |
| `GET /routes/{route_id}/stops` | `service_date` **필수**, 선택 `route_pattern_id`·`route_version_id` | 그 날짜에 적용되는 패턴의 방문 목록 |

`GET /routes/{route_id}/stops`에 **`service_date`가 필수인 이유**는 천안역 노선이 요일별로 다른 패턴을 갖기 때문이다. 날짜 없이 "오늘"을 가정하면 주말에 평일 정거장 목록을 보여준다.

지정한 `route_version_id`가 그 노선·패턴 소속인지 검증한다.

## 8. 함수

| 함수 | 입력 → 결과 | 핵심 규칙 |
|---|---|---|
| `resolve_service_calendar` | 노선·서울 날짜 → 상태·적용 템플릿 | 예외 우선, 요일 조건은 참조 템플릿 기준 |
| `ensure_scheduled_trips` | 날짜 범위 → 누락 회차 생성 | 멱등, 과거 보존 |
| `build_trip_stops` | 패턴·공시값 → `trip_stop` 목록 | 기점 이전 제외 |
| `build_trip_vehicle_slots` | 회차·요일 대수 → 슬롯 | 2대 분리, 차량 번호 없어도 생성 |
| `find_next_service_date` | 노선·기준 날짜 → 다음 운행일 | `unknown` 건너뜀 표시 |

## 9. 검증 기준

| ID | 요구사항 | 확인 방법 |
|---|---|---|
| FR-SC-01 | 네 상태가 구분됨 | 정상 09-10=available / 09-24=no_service / 별도 검수 자료에서 09-10의 coverage 삭제=unknown / 08-31·12-15=out_of_period |
| FR-SC-02 | 명시 휴무가 주말 템플릿보다 우선 | 09-26(토) → `no_service` |
| FR-SC-03 | 대체휴일이 참조 템플릿 규칙으로 평가 | 10-05(월) → 일요일 회차 생성, 월요일 2대 조건 미적용 |
| FR-SC-04 | 주말 온양 노선이 `no_service` | 토요일 온양 조회 |
| FR-SC-05 | 금요일에 `금(X)` 회차 미생성 | 평일 금요일 회차 수 61 |
| FR-SC-06 | 요일별 차량 슬롯 수 | 월·화 122, 수·목 121, 금 61, 토 12, 일 16 |
| FR-SC-07 | 생성이 멱등 | 같은 범위 두 번 실행 후 행 수 불변 |
| FR-SC-08 | CronJob 실패 후 누락 보충 | 며칠 건너뛴 뒤 실행 |
| FR-SC-09 | 기점 이전 방문 미생성 | 천안아산역 순2에 캠퍼스 출발 `trip_stop` 부재 |
| FR-SC-10 | 개정이 수집 시작 회차를 건드리지 않음 | 수집 중 템플릿 수정 후 해당 회차 시각 불변 |
| FR-SC-11 | 날짜 없는 정거장 조회 거부 | `service_date` 누락 시 422 |
| FR-SC-12 | 서버 시간대 비의존 | TZ 환경변수 변경 후 판정 동일 |

## 10. 요일 해석과 생성 검증

| 필드 | 결정 방법 |
|---|---|
| `actual_weekday` | 서울 기준 실제 날짜의 요일 |
| `effective_day_type` | 최종 선택한 템플릿의 day_type |
| `effective_service_weekday` | weekday면 actual_weekday, saturday면 sat, sunday_holiday면 sun |

제외 요일과 차량 대수는 `effective_service_weekday`를 쓴다. 통계 그룹에는 `effective_day_type`을 전달한다. 10/05는 actual_weekday=mon, effective_service_weekday=sun, effective_day_type=sunday_holiday이다. 해당 날짜는 16회·16슬롯이며 월요일 2대 조건은 적용하지 않는다.

명시 휴무는 시간표보다 먼저 적용한다. 동일 범위·날짜 예외 중복을 막고 노선 전용 예외가 전체 예외보다 우선한다. `confirmed_service` 등록 시 예상 행 수와 실제 등록 행 수 및 필수 대수 키를 검사해 부분 가져오기를 공개하지 않는다. 날짜별 제외 조건 적용 후 예상 수량도 별도로 검증한다.

기점 예정 출발 시각 경과로 `scheduled_running` 상태를 만들 수 있으나 실제 departed 이벤트를 생성하지 않는다. 중간 방문의 공시 시각 경과로 실제 도착·통과 상태를 만들지 않는다. 완료·취소 상태는 시간 경과로 다시 scheduled_running으로 바꾸지 않는다.

| ID | 사례 | 기대 결과 |
|---|---|---|
| FR-SC-13 | 10/05 일요일 대수 키 사용 | 전체 16회·16슬롯 |
| FR-SC-14 | confirmed_service에 회차 일부 누락 | unknown, 운행 없음으로 단정하지 않음 |
| FR-SC-15 | 휴일 대수 JSON에 sun 키 누락 | 자료 오류, 0대 자동 생성 금지 |
