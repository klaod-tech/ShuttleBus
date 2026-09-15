# 01 · 공통 규약

> 모든 기능 문서가 참조한다. 여기 정의된 것은 다른 문서에서 다시 정의하지 않는다.
> 참조: [개요](00-overview.md)

이 문서는 **횡단 규칙과 인덱스**를 담는다. 특정 기능에만 해당하는 상태값·필드는 소유 문서에 정의하고, 여기에는 어디에 있는지만 적는다.

---

## 1. 식별자 체계

같은 물리적 정거장이 여러 노선에, 한 회차 안에서도 여러 번 등장한다. 그래서 "정거장"을 가리키는 ID가 세 층이다. **이 구분이 무너지면 순환 노선과 왕복 회차가 전부 깨진다.**

| ID | 가리키는 것 | 예 |
|---|---|---|
| `stop_id` | 물리적 정거장 | 아산캠퍼스 |
| `route_pattern_id` | 같은 날 공존하는 운행 경로 | 천안역 일반 왕복 / 천안역 중간노선 전용 |
| `route_version_id` | 패턴의 개정판 | 2026-2학기 천안역 일반 v1 |
| `route_stop_id` | 노선 버전 안의 특정 방문 | 그 버전의 5번째 방문(아산캠퍼스 종점) |
| `trip_id` | 날짜별 회차 | 2026-09-10 천안아산역 순1 |
| `trip_stop_id` | 날짜별 회차의 특정 방문 | 그 회차의 아산캠퍼스 종점 도착 |
| `trip_vehicle_id` | 같은 회차의 차량 슬롯 | 순4의 2번째 차량 |
| `session_id` | 실제 수집 세션 | 그 차량을 동승 기록한 세션 |
| `event_id` | 저장된 관측 | 그 세션의 3번째 통과 기록 |

### 사용 규칙

- **정거장 선택은 `origin_stop_id`·`destination_stop_id`(각각 물리 stop_id)**, 이벤트 기록은 `trip_stop_id`를 쓴다.
- 캠퍼스 출발 방문과 캠퍼스 종점 방문은 물리적 지점이 같아도 **다른 `trip_stop_id`**다.
- 순환 노선의 재방문도 다른 `trip_stop_id`다. 따라서 재방문은 순서 역행이 아니다.
- API에서 `trip_id`는 DB `scheduled_trip_id`의 별칭이다.
- 서버 리소스 ID는 UUID 문자열이다. `client_event_id`·`client_position_id`는 생산자가 생성하는 불투명 문자열이며 해당 계약의 유일성 규칙을 따른다. 문서의 ID 예시는 설명용이며 실제 데이터가 아니다.
- 서버는 클라이언트가 보낸 ID 조합을 그대로 신뢰하지 않는다. `session → trip_vehicle → trip → trip_stop`의 소속을 검증한다.

## 2. 시각 표현

| 규칙 | 내용 |
|---|---|
| 저장 | UTC |
| 판정·표시 | `Asia/Seoul` |
| 전송 형식 | 시간대 포함 ISO 8601 |
| 소요시간 | 초 |
| 거리 | 미터 |
| 좌표 | WGS84 위도·경도 |

시간표의 `TIME` 값은 날짜와 결합할 때 `Asia/Seoul`로 해석한다. 자정 이후 운행은 `day_offset`으로 표현하며, 입력 자료의 모든 행이 당일 증가한다는 이유로 자정 넘김을 자동 추측하지 않는다.

### 경계 정책 — 두 규칙이 다르다

같은 시스템 안에 반열린 구간과 닫힌 구간이 함께 있다. **혼용하면 판정이 갈린다.**

| 대상 | 경계 | 근거 |
|---|---|---|
| `time_bands` (시간대) | **반열린** `[start, end)` | 천안역 순31 캠퍼스 19:30 출발이 `[17:30, 19:30)`의 끝과 겹침 → `offpeak` |
| 학생회관 승차 창 | **닫힘** `[start, end]` | 천안아산역 순26 15:30 해당, 순27 15:35 비해당 |

시간 범위는 `start_second`·`end_second`(0–86400)로 표현해 24:00 끝을 지원한다. 자정에 걸친 범위는 두 행으로 나눈다.

시간대 정의와 적용은 `08-prediction`, 승차 창은 `10-stop-discovery`가 소유한다.

### 시각의 세 가지 시계

| 필드 | 잰 주체 | 쓰임 |
|---|---|---|
| `occurred_at` | 단말 (버튼 클릭 또는 GPS 측정) | 사건이 실제로 일어난 시각 |
| `received_at` | 서버 | 수신 시각. 전송 지연 측정용이며 시계 오류의 단독 근거로 사용하지 않음 |
| `server_time` | 서버 | 응답 생성 시각. 남은 시간 계산 기준 |

**남은 시간은 저장하지 않는다.** `estimated_event_at − server_time`으로 매번 계산한다.

## 3. 세 가지 버전

세 버전은 서로 다른 충돌을 막는다. 하나로 합치면 관계없는 변경이 서로를 실패시킨다.

| 버전 | 저장 위치 | 기대값을 보내는 요청 | 충돌 코드 |
|---|---|---|---|
| `state_version` | `scheduled_trips` | **없음** — 공개 스냅샷 순서 판정 전용 | — |
| `input_version` | `collection_sessions` | 관측 입력, 입력 취소, 수집 종료, 관리자 관측 검토 | `INPUT_VERSION_CONFLICT` |
| `control_version` | `scheduled_trips` | 차량 완료, 회차 취소, 관측 검토·취소 복구, 완료 결정 재검토 | `CONTROL_VERSION_CONFLICT` |

### 규칙

- 클라이언트는 `state_version`을 기대값으로 **보내지 않는다.** 더 새로운 스냅샷만 반영하는 데만 쓴다. 입력 충돌에 쓰면 ETA 자동 갱신이나 다른 차량의 입력만으로 입력자가 계속 409를 받는다.
- **`control_version`이 증가하는 변경은 같은 트랜잭션에서 `state_version`도 증가시킨다.** 회차 취소와 차량 완료는 학생에게 보이는 상태를 바꾸기 때문이다. 올리지 않으면 낮은 버전을 되돌리지 않는 규칙과 맞물려 학생 화면이 취소를 반영하지 못한다.
- 새로운 관측 저장·입력 취소·수집 종료는 `input_version`을 증가시킨다. 공개 상태가 바뀌면 `state_version`도 같은 트랜잭션에서 증가한다. 순수 ETA 갱신·정보 만료는 `state_version`만 증가한다. 일반 관측 입력은 `control_version`을 증가시키지 않는다.
- 관리자 관측 검토는 대상 세션의 `expected_input_version`과 회차의 `expected_control_version`을 함께 검증하고 두 버전 및 `state_version`을 증가시킨다. 이미 처리된 동일 요청 재전송은 버전을 증가시키지 않는다.
- `input_version`은 세션 단위다. 두 차량이 같은 회차를 각각 수집해도 서로 충돌하지 않는다. 다만 양쪽 관측이 모두 공개 상태를 바꾸므로 `state_version`은 공통으로 증가한다.

### 원자성

버전 번호만 원자적으로 증가시키는 것으로는 응답 일관성이 보장되지 않는다. MVP는 **회차 단위 잠금** 아래 유효 이벤트·차량별 상태·예측·상태 버전·전송 대기 레코드를 같은 DB 트랜잭션으로 확정한다. 서비스 분리 후에도 완성된 상태 버전만 공개하고 미완성 계산 결과를 새 버전으로 내보내지 않는다.

## 4. 멱등 계약

논리 관측 ID와 요청 시도 ID는 **다른 것**이다. 이 구분이 재시도의 핵심이다.

| | `client_event_id` | `Idempotency-Key` |
|---|---|---|
| 무엇 | 논리 관측 ID | 한 HTTP 요청 시도 ID |
| 범위 | `(collection_session_id, client_event_id)` 유일 | 요청 단위 |
| 재시도 시 | **유지한다** | 상황에 따라 다름 |

### 언제 키를 새로 발급하나

| 상황 | `client_event_id` | `Idempotency-Key` |
|---|---|---|
| 같은 본문 통신 재전송 (타임아웃·연결 끊김) | 유지 | **유지** |
| `INPUT_VERSION_CONFLICT` 후 재검증 | 유지 | **새로 발급** |
| `SKIP_LIMIT_EXCEEDED` 후 `confirm_skip=true` | 유지 | **새로 발급** |

기대 버전이나 확인 옵션이 바뀌면 본문이 달라지므로 새 키가 필요하다. 논리 관측은 같은 것이므로 `client_event_id`는 그대로다. DB 유일성이 중복 저장을 막는다.

### 서버 처리 순서

1. 인증·권한 검증
2. `Idempotency-Key` 재사용 검증 — 같은 키·다른 본문이면 `IDEMPOTENCY_KEY_REUSED`
3. 이미 확정된 논리 관측 조회 — 있고 불변 내용이 같으면 **기존 결과 반환**
4. 불변 내용이 다르면 `EVENT_ID_REUSED`
5. 기대 버전 검증 → 유효성 검사 → 저장

기존 논리 관측의 불변 내용 판정(3~4단계)이 기대 버전 검증(5단계)보다 앞선다. **성공한 요청을 재전송했는데 버전만 오래됐다는 이유로 실패시키지 않는다.**

불변 내용의 정의는 `02-observation-contract`에 있다.

## 5. API 공통 규칙

- 기본 경로 `/api/v1`
- JSON 필드와 DB 열은 `snake_case`, TypeScript 변수·함수는 `camelCase`
- 변경 요청에는 `Idempotency-Key`를 사용한다. 없으면 422. 키는 계정별로 `idempotency_records`에 요청과 같은 트랜잭션으로 저장하고, 성공 응답만 기록한다. 시계 확인 두 요청은 매번 새 측정이므로 키를 요구하지 않는다
- 관리자·입력자는 `Authorization: Bearer {access_token}`으로 인증하고 역할을 검증한다
- **입력자 토큰 수명은 24시간**이다. 왕복 운행 중 만료를 피하기 위함이며 MVP에는 refresh 토큰을 두지 않는다. 만료 2시간 전부터 재로그인을 안내한다. 재로그인해도 로컬 대기 입력 ID는 유지한다.
- 단말 인증은 별도 토큰·차량 배정이며 발급·회수는 Phase 2에서 설계한다 (`07-gps-detection`)
- **`retryable=true`는 동일 요청의 일시 오류 재전송에만 쓴다**

### HTTP 상태

401 인증, 403 권한, 404 대상 없음, 409 충돌, 422 형식, 503 일시 실패. 오류 본문은 `error.code` / `error.message` / `error.retryable`. 화면 안내는 한국어로 작성한다.

```json
{
  "error": {
    "code": "EVENT_ORDER_CONFLICT",
    "message": "이미 지난 정거장입니다. 잘못 입력했다면 취소를 사용해 주세요.",
    "retryable": false
  }
}
```

### 오류 코드 인덱스

| 코드 | HTTP | 발생 | `retryable` | 소유 문서 |
|---|---|---|---|---|
| `EVENT_ORDER_CONFLICT` | 409 | 실시간 입력이 현재 방문보다 앞선 순번 | false | `02` |
| `EVENT_ID_REUSED` | 409 | 같은 논리 관측 ID에 다른 불변 내용 | false | `02` |
| `INPUT_VERSION_CONFLICT` | 409 | `expected_input_version` 불일치 | false | `06` |
| `CONTROL_VERSION_CONFLICT` | 409 | `expected_control_version` 불일치 | false | `13` |
| `IDEMPOTENCY_KEY_REUSED` | 409 | 같은 키에 다른 본문 | false | `01` |
| `SESSION_OWNERSHIP_CONFLICT` | 409 | 다른 입력자가 점유한 세션. 자동 인계 금지 | false | `06` |
| `SKIP_LIMIT_EXCEEDED` | 409 | `max_skip_stops` 초과. `confirm_skip=true`로 재요청 | false | `06` |
| `RESOURCE_NOT_FOUND` | 404 | 실제 노선·회차·세션 ID 없음 | false | `01` |
| `AUTH_REQUIRED` | 401 | 토큰 없음·만료·잘못된 로그인. 화면은 재로그인 안내, 대기 큐 유지 | false | `01` |
| `FORBIDDEN` | 403 | 역할이 맞지 않음, 다른 입력자의 세션 조회 | false | `01` |
| `EVENT_ALREADY_CANCELLED` | 409 | 이미 취소된 기록의 재취소. 되돌리려면 13 복구 | false | `02` |
| `VALIDATION_ERROR` | 422 | 필수 입력 누락·형식 오류·소속이 맞지 않는 ID 조합 (예: 날짜 없는 정거장 조회) | false | `01` |
| `REVIEW_CONFLICT` | 409 | 검토 대상 상태 변경 또는 대표 관측 충돌 | false | `13` |
| `RESTORE_CONFLICT` | 409 | 복구하면 한 방문에 유효 관측이 둘이 됨 | false | `13` |
| `CLOCK_EVIDENCE_INVALID` | 422 | 시계 검증 근거 형식·소속 불일치 | false | `02` |
| `CACHE_REBUILDING` | 503 | 캐시 복원 중 | true | `12` |

**날짜 자료 미확보는 404가 아니다.** 200 응답의 `schedule_status = unknown`으로 표현한다. 404는 존재하지 않는 리소스에만 쓴다.

## 6. 상태값 인덱스

각 상태값의 **정의와 전이 규칙은 소유 문서에 있다.** 여기에는 목록과 소재만 둔다.

| 상태 | 값 | 저장 위치 | 소유 문서 |
|---|---|---|---|
| `schedule_status` | available / no_service / unknown / out_of_period | `service_calendar` | `05` |
| `operation_status` (회차) | scheduled / scheduled_running / completed / cancelled | `scheduled_trips` | `05`, `13` |
| `operation_status` (차량) | scheduled / scheduled_running / completed / cancelled | `trip_vehicles` | `13` |
| `collection_status` | not_started / collecting / ended / needs_review | `collection_sessions` | `06` |
| `producer_type` | manual / gps | `collection_sessions` | `06` |
| `comparison_policy` | manual_only / manual_reference / gps_primary | `collection_sessions` | `06`, `02` |
| `event_type` | arrived / departed / passed / skipped | `location_events` | `02` |
| `source` | manual / gps / system | `location_events` | `02` |
| `time_confidence` | observed / interpolated / inferred | `location_events` | `02` |
| `validation_status` | valid / needs_review / cancelled | `location_events` | `02` |
| `visit_status` | upcoming / arrived / departed / passed / passed_inferred / not_collected / unknown | 파생 | `02`, `03` |
| `information_status` | timetable_only / observed / stale / unavailable | `trip_vehicles` | `03` |
| `position_status` | not_enabled / locating / current | 파생 | `03` |
| `target_event_type` | arrived / departed / passed | `eta_predictions` | `03`, `08` |
| `prediction_basis` | scheduled_departure / observed_event / interpolated_event | `eta_predictions` | `03`, `08` |
| `prediction_models.status` | draft / validating / active / retired | `prediction_models` | `08` |
| `baseline_source` | manual_measurement / school_timetable / estimate / operation_history | `travel_times` | `09` |
| `unavailable_reason` | missing_baseline / stale_observation / prediction_expired / already_passed / trip_completed / trip_cancelled / no_observation / awaiting_departure / position_unverified / event_confirmed | 파생 | `03` |
| `boarding_policy`, `alighting_policy` | allowed / not_allowed / unknown | `scheduled_trip_stops` | `04` |
| `schedule_source` | school_pdf / operator_entry / unknown | `scheduled_stop_times` | `04` |
| `path_source` | recorded_track / operator_provided / manual_trace | `route_path_points`, `route_stop_segments` | `04` |
| `punctuality_assumption` | user_asserted_on_time / not_assumed | `trip_templates` | `04` |
| `data_status` | draft / available / missing | `schedule_templates` | `04` |
| `exception_type` | no_service / alternate_schedule | `schedule_exceptions` | `05` |
| `coverage_status` | confirmed_service / confirmed_no_service / unknown | `schedule_route_coverage` | `05` |
| `notice_type` | delay / cancel / info | `notices` | `13` |
| `verification_status` | verified / needs_interpretation / unverified | 여러 곳 | `04` |
| `end_reason` | reassigned / terminal_departed / signal_lost / service_day_closed | `collection_sessions` | `07` |
| `observation_reviews.decision` | cancel / approve / reject / restore. cancel은 입력자 취소 이력 (02 v7.8) | `observation_reviews` | `13` |
| `staff_accounts.role` | collector / admin | `staff_accounts` | `06` |
| `model_decisions.action` | promote / rollback / block / unblock / resume_auto | `model_decisions` | `08` |
| `travel_time_invalidations.reason` | observation_cancelled / observation_rejected | `travel_time_invalidations` | `09` |
| `connectionStatus` (로컬) | connecting / connected / disconnected | 화면 상태 | `12` |

**서버 연결 상태를 운행 상태로 저장하지 않는다.** 통과 이벤트가 없는 것과 네트워크가 끊긴 것은 다르다.

### 헷갈리기 쉬운 짝

| 짝 | 무엇이 다른가 |
|---|---|
| `source` vs `producer_type` | `source`는 **이벤트**의 출처이고 `producer_type`은 **세션**의 생산자다. 서버가 만든 `skipped`는 `source = system`이지만 그 세션의 `producer_type`은 여전히 manual이다. `producer_type`에 system은 없다 |
| `information_status` vs `position_status` | 전자는 **통과 기록**의 유효성, 후자는 **좌표**의 신선도다. 좌표는 멀쩡한데 통과 기록만 오래된 상태가 정상적으로 발생한다 |
| `coverage_status` vs `schedule_status` | 전자는 **자료 범위**(그 노선 자료를 확보했나), 후자는 **최종 판정**(오늘 운행하나)이다. 값 이름이 겹치지만 다른 층이다 |
| `visit_status = passed` vs `passed_inferred` | 후자는 **실측 통과 시각이 없다.** 지나갔다는 사실만 안다 |

`position_status`는 저장하지 않고 마지막 좌표의 나이에서 파생한다. 위치 재확인 세부 판정은 개선사항 1순위의 자료 등록 대기이며, 검증 전 자동 복원에 사용하지 않는다.

## 7. 설정값 인덱스

미정 표시된 값은 **임의로 채우지 않는다.** 미설정 상태의 기본 동작은 소유 문서에 정의한 보수적 처리를 따른다.

**여기에는 이름·용도·상태만 둔다. 실제 숫자는 소유 문서에만 있다.** 값을 양쪽에 적으면 한쪽만 고쳐져 어긋난다. 상태는 넷이다 — `확정` / `시험값`(쓰고 있으나 실측으로 교체 예정) / `실측 후 확정`(근거가 없어 아직 못 정함) / `미정`(값이 없어 기능이 보류됨).

| 이름 | 판단하는 것 | 상태 | 소유 문서 |
|---|---|---|---|
| `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET` | 접속·서명 비밀값 | 서버 전용 | `14` |
| `ACCESS_TOKEN_TTL_SECONDS` | 입력자 토큰 수명 | 확정 | `01` |
| `observation_grace_seconds` | 통과 기록이 오래됐는가 | 시험값 | `08` |
| `auto_promote_enabled` | 통계 스냅샷을 자동 활성화할 것인가 | 최초 기본 참, 롤백 시 false·명시 재개 | `08`·`14` |
| `arrived_freshness_seconds` | arrived를 추천해도 되는가 | 시험값 | `11` |
| `realtime_input_window_seconds` | 실시간 입력인가 지연 보충인가 | 시험값 (비우면 역행을 `needs_review`) | `02` |
| `clock_skew_tolerance_seconds` | 단말 시계를 믿을 수 있는가 | 시험값 (비우면 `needs_review`) | `02` |
| `clock_check_valid_seconds` | 시계 확인 근거가 유효한 범위 | 시험값 (비우면 `needs_review`) | `02` |
| `pending_input_retention_hours` | 지연 입력을 채택할 것인가 | 시험값 (비우면 `needs_review`) | `02` |
| `session_review_grace_seconds` | 기록을 검토해야 하는가 | 실측 후 확정 | `13` |
| `max_skip_stops` | 한 번에 건너뛸 수 있는 방문 수 | 시험값 | `06` |
| `refresh_after_seconds` | 후보를 다시 조회할 때인가 | 시험값 | `11` |
| `gps_report_interval_seconds` | 단말 전송 주기 | 시험값 | `07` |
| `geofence_radius_m` | 정거장 반경. 정거장별로 다를 수 있음 | 시험값 | `07` |
| `detection_delay_seconds` | 재정렬 지연 창 | 시험값 | `07` |
| `gps_stale_after_seconds` | GPS 좌표가 만료됐는가 | 시험값 | `07` |
| `gps_session_idle_seconds` | 좌표 두절로 세션을 닫을 시점 | 시험값 | `07` |
| `trip_binding_window_seconds` | 기점 이탈을 어느 회차에 붙일 것인가 | 시험값 | `07` |
| `dwell_min_seconds` | 정차로 볼 최소 체류 | **미정** → `arrived` 미생성 | `07` |
| `detection_grace_seconds` | 통과 미확인 점검을 시작할 것인가 | **미정** → 점검 미시작 | `07` |
| `max_route_deviation_m` | 경로를 벗어났는가 | **미정** → 이탈 판정 미수행 | `07` |
| `route_deviation_min_points` | 이탈로 확정할 연속 점 수 | **미정** → 이탈 판정 미수행 | `07` |
| `terminal_boundary_min_points` | 종점 진입·이탈의 연속 유효 좌표 수 | **미정** → terminal_departed 미적용 | `07` |
| `route_rejoin_min_points` | 정상 복귀로 볼 연속 점 수 | **미정** → 이탈 판정 미수행 | `07` |
| `max_interpolation_gap_seconds` | 이 간격을 넘는 좌표를 보간할 것인가 | **미정** → 보간 미확정 | `07` |
| `max_position_accuracy_m` | 이 오차의 좌표를 판정에 쓸 것인가 | **미정** → 보간 미확정 | `07` |
| `max_plausible_speed_mps` | 물리적으로 불가능한 이동인가 | **미정** → 보간 미확정 | `07` |
| `raw_position_retention_days` | 원시 좌표를 언제까지 보관하는가 | **미정** → 정리 미적용 | `07` |

### 서로 대신 쓰지 않는 세 값

| 값 | 재는 대상 | 자릿수 |
|---|---|---|
| `gps_stale_after_seconds` | 마지막 **좌표**의 나이 | 분 |
| `arrived_freshness_seconds` | 마지막 **도착 기록**의 나이 | 분 |
| `observation_grace_seconds` | 마지막 **통과 기록**의 나이 | 수십 분 |

정거장 사이를 정상 주행하는 동안 좌표는 계속 들어오지만 통과 기록은 구간 소요시간만큼 늙는다. 그래서 셋의 자릿수가 다르다. **관측 만료 시간은 공시 구간 길이뿐 아니라 실제 관측 사이 간격·지연을 고려해야 한다.** 04의 터미널 편도 40분에 대해 08의 2400초는 여유 없는 시험값이다. GPS 세션 종료 시간은 좌표 수신 공백을 기준으로 별도 실측한다.

**`observation_grace_seconds`를 입력 허용 지연 기준으로도 재사용하지 않는다.** "정보가 오래됐으니 화면에서 예측을 숨긴다"와 "이 지연 입력을 실측으로 채택한다"는 완전히 다른 판단이다.

비밀값은 서버 전용이며 `NEXT_PUBLIC_` 변수에 넣지 않는다.

## 8. 명명 규칙

| 대상 | 규칙 |
|---|---|
| DB 열, JSON 필드 | `snake_case` |
| Python 함수·변수 | `snake_case` |
| TypeScript 함수·변수 | `camelCase` |
| 브라우저 공개 환경변수 | `NEXT_PUBLIC_` 접두 |

### 시각 필드 명명

| 접미 | 의미 |
|---|---|
| `_at` | 시간대 포함 절대 시각 (`TIMESTAMPTZ`) |
| `_time` | 날짜 없는 시각 (`TIME`). 템플릿에만 사용 |
| `_seconds`, `_hours` | 기간 |

예상 시각은 **`estimated_event_at` 하나로 통일**한다. 무엇의 예상인지는 `target_event_type`이 결정한다. `estimated_arrival_at`처럼 이벤트 종류를 이름에 박지 않는다.

미확인 값은 `null`과 이유를 쓴다. **0으로 대신하지 않는다.**

근거 관측은 `basis_observation` 하나로 싣는다. 같은 값을 `basis_event_id`·`basis_observed_at`으로 응답에 중복해서 넣지 않는다 (`03` 5장). 두 열은 `eta_predictions` 이력에만 남는다.
