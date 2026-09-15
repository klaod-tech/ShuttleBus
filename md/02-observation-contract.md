# 02 · 관측 계약

> **관측이란 무엇인가**를 정의한다. 수동 입력(`06`)과 GPS 판별(`07`)이 이 형식을 만들고, 예측(`08`)과 통계(`09`)가 이 형식을 읽는다.
> 참조: [공통 규약](01-conventions.md)

생산자 셋과 소비자 둘이 서로를 참조하지 않고 이 계약만 본다. **여기 없는 필드를 생산자가 임의로 만들거나, 소비자가 생산 경로를 알고 분기하면 계약이 깨진다.**

---

## 1. 관측의 정의

관측은 **한 차량이 회차의 한 방문에서 무엇을 했는지에 대한 기록**이다.

```
누가   trip_vehicle_id   회차의 차량 슬롯
어디서 trip_stop_id      날짜별 회차의 특정 방문
무엇을 event_type        도착 / 출발 / 통과 / 누락
언제   occurred_at       + time_confidence
```

네 개가 다 있어야 관측이다. 하나라도 추정으로 채우면 그 사실을 `time_confidence`와 `validation_status`에 남긴다.

## 2. `location_events` 스키마

| 열 | 타입 | 설명 |
|---|---|---|
| `event_id` | UUID | PK |
| `collection_session_id` | UUID | 소속 세션 |
| `trip_vehicle_id` | UUID | 관측 대상 차량 슬롯. 세션에서 파생한 비정규화 열이며 세션 값과 일치해야 한다 |
| `trip_stop_id` | UUID | 방문 |
| `event_type` | enum | arrived / departed / passed / skipped |
| `occurred_at` | TIMESTAMPTZ **nullable** | 사건 발생 시각 |
| `time_confidence` | enum | observed / interpolated / inferred |
| `received_at` | TIMESTAMPTZ | 서버 수신 시각 |
| `source` | enum | manual / gps / system |
| `client_event_id` | text | 논리 관측 ID |
| `client_sequence` | int nullable | 생산자 세션 내 발생 순번. system 이벤트는 null |
| `clock_check_id` | UUID nullable | 발생 시각의 시계 신뢰도를 검증한 근거. 수동·단말 세션에 연결 |
| `review_reason` | text nullable | 검토 대기 사유 |
| `validation_status` | enum | valid / needs_review / cancelled |
| `parent_event_id` | UUID nullable | 자동 생성의 근거 이벤트 |
| `cancelled_at`, `cancel_reason` | | 취소 기록 |

### 제약

- `UNIQUE (collection_session_id, client_event_id)` — 논리 관측 유일성
- `UNIQUE (collection_session_id, client_sequence) WHERE client_sequence IS NOT NULL` — 생산자 세션 내 단말 순번 유일성
- 같은 `(trip_stop_id, trip_vehicle_id, event_type)`의 유효 이벤트는 하나. **`trip_vehicle_id`를 열로 저장하고** `validation_status = valid`에 한정한 부분 유일 인덱스로 강제한다. 값은 세션에서 파생하며 저장 시 세션의 `trip_vehicle_id`와 일치하는지 검사한다. 조건부 서술이 아니라 확정 규칙이다.
- `source = system`이면 `client_event_id`는 서버가 생성하고 `client_sequence = null`로 둔다. `(parent_event_id, trip_stop_id, event_type)`으로 자동 생성의 멱등성을 보장한다. 수동·GPS는 06의 생산자별 세션을 사용한다.

### 불변 내용

재전송 판정에 쓰는 값이다. 이 넷이 같으면 같은 관측으로 본다.

```
trip_stop_id · event_type · occurred_at · client_sequence
```

같은 `client_event_id`인데 넷 중 하나라도 다르면 `EVENT_ID_REUSED`로 거절한다. `expected_input_version`과 `confirm_skip`은 불변 내용이 **아니다** — 바뀌어도 같은 관측이다.

## 3. `event_type`

| 값 | 의미 | 누가 만드나 |
|---|---|---|
| `arrived` | 정거장에 도착 | 수동, GPS |
| `departed` | 정차 후 떠남 | 수동, GPS |
| `passed` | 기준 지점 통과 | 수동, GPS |
| `skipped` | 관측하지 못함 — **실측이 아니다** | 서버 (`source = system`) |

`arrived`는 `departed`·`passed`와 다르다. **`arrived`만 있는 차량을 '이미 통과'로 분류하지 않는다.** 도착만 확인되고 출발이 확인되지 않았으면 아직 탈 수 있다.

같은 방문에서 `arrived` → `departed` 순서는 허용한다. 실제 재방문은 다른 `trip_stop_id`이므로 이와 구분된다.

`skipped` 자체는 마지막 확인 지점을 전진시키지 않는다. 전진 근거는 후속 유효 관측이며 누락 방문은 추론 이력으로만 남긴다. **ETA 갱신 근거나 학습 표본으로 쓰지 않는다.**

## 4. `time_confidence` — 시각을 얼마나 믿을 수 있나

`occurred_at`이 어떻게 정해졌는지 나타낸다. **소비자는 이 값만 보고 사용 여부를 정한다.** 생산 경로(`source`)로 분기하지 않는다.

| 값 | `occurred_at` | 어떻게 얻었나 | ETA 갱신 근거 | 통계 표본 |
|---|---|---|---|---|
| `observed` | 있음 | 정해진 사건 기준으로 누른 버튼 시각, 또는 사건 종류까지 검증된 GPS 직접 관측 시각. 반경 안 좌표 하나만으로 승격하지 않음 | ✅ | ✅ |
| `interpolated` | 있음 | 연속한 두 GPS 좌표 사이 보간 | ✅ | ❌ |
| `inferred` | **null** | 후속 관측으로 지나갔음을 추론 | ❌ | ❌ |

### 왜 세 단계인가

미검출이 발생하면 그 방문에 `observed` 관측이 생기지 않는다. `inferred`만 만들면 `occurred_at`이 null이라 **ETA 갱신 공식에 넣을 값이 없다.** 다음 방문도 검출을 놓치면 예측이 기점 시간표 기준에 고정된 채 회복되지 않는다.

`interpolated`는 이 구멍을 메운다. 두 실측 좌표 사이의 보간이므로 시각을 만들어낸 것이 아니고, 그렇다고 직접 관측도 아니다. **예측에는 쓰되 학습에서는 뺀다.** 예측은 회복되고 통계는 오염되지 않는다.

보간 방법은 `07-gps-detection`이 소유한다.

### 소비자 규칙

- 예측(`08`)은 `time_confidence ∈ {observed, interpolated}` 이고 `validation_status = valid`인 이벤트에서 **08의 진행 순서·사건 연결 조건을 만족하는 대상별 근거**를 선택한다. 수신 시각이 늦다는 이유로 과거 방문으로 진행을 되돌리지 않는다.
- 통계(`09`)는 `time_confidence = observed` 이고 `validation_status = valid`인 이벤트만 표본으로 쓴다.
- 두 소비자 모두 `source`를 보지 않는다. 수동이든 GPS든 같은 규칙이다.

## 5. `validation_status`

| 값 | 의미 | 공개 상태 반영 | 통계 |
|---|---|---|---|
| `valid` | 검증 통과 | ✅ | 조건 충족 시 |
| `needs_review` | 모순 또는 시계 오차 의심 | ❌ | ❌ |
| `cancelled` | 취소 또는 관리자 기각 | ❌ | ❌ |

`needs_review`는 **버리지 않고 보관한다.** 관리자가 확인할 때까지 공개 상태와 통계에서 제외될 뿐이다.

## 6. 유효성 검사

저장 전에 아래를 확인한다. 하나라도 어긋나면 거절하거나 `needs_review`로 보관한다. `system/skipped`는 시각이 null이므로 시각·보관 기간 검사를 직접 적용하지 않고 유효한 부모 관측·동일 소속·중간 방문 범위로 검증한다.

| 검사 | 실패 시 |
|---|---|
| 소속: `session → trip_vehicle → trip → trip_stop` | `RESOURCE_NOT_FOUND` |
| 수집 기간: `occurred_at`이 세션 시작~종료 범위 안 | `needs_review` |
| 순서: 아래 실시간 역행·지연 보충 규칙 참조 | `EVENT_ORDER_CONFLICT` 또는 보충 |
| 중복: 동일 논리 관측 ID 재전송 | 불변 내용이 같으면 기존 결과 반환 |
| 독립 관측: 다른 논리 ID로 같은 방문·종류 기록 | 원본 보존 후 §10의 대표 관측 선택 |
| 시계: 검증된 단말 시계 오차와 불확실성이 `clock_skew_tolerance_seconds` 허용범위를 넘거나 근거 없음 | `needs_review` |
| 보관: `occurred_at`이 `pending_input_retention_hours` 초과 과거 | `needs_review` |

### 실시간 역행과 지연 보충의 구분

겉보기에 같지만 처리가 다르다.

| 구분 | 판별 | 처리 |
|---|---|---|
| **실시간 역행** | `received_at − occurred_at ≤ realtime_input_window_seconds`이고 `stop_sequence`가 현재 마지막 유효 방문보다 앞 | `EVENT_ORDER_CONFLICT`로 거절. 잘못 눌렀다면 취소를 쓰도록 안내 |
| **지연 보충** | 같은 창을 넘겨 도착 | 이력에 보충. 해당 방문의 상태만 정정하고 **최신 위치를 뒤로 옮기지 않는다** |

역행을 거절하는 이유는 순환 노선의 재방문과 오입력을 서버가 구분할 수 없기 때문이다. **재방문은 `trip_stop_id`가 다르므로 역행이 아니다.**

둘을 가르는 것은 **서버가 잰 수신 지연 하나뿐이다.** 클라이언트가 보낸 큐 경유 플래그는 판정에 쓰지 않는다 — 오프라인 큐를 거쳤다는 사실만으로 정상 과거 기록을 인정하지 않는다. `realtime_input_window_seconds`가 미정이면 두 경로를 구분하지 못하므로 역행 입력을 거절하지 않고 전부 `needs_review`로 보관한다.

어느 경로든 소속·순서·수집 기간·시계 오차를 함께 검사한다. **거절 검사(소속 → 순서)를 먼저 모두 통과한 뒤 보관 판정(수집 기간 → 시계 → 보관 기간)을 적용한다.** 거절과 보관이 동시에 걸리면 거절이 이긴다.

## 7. 자동 누락 생성

건너뛴 입력을 허용하고 서버가 중간 방문을 `skipped`로 채운다.

```
현재 마지막 유효 방문: stop_sequence = 2
입력: stop_sequence = 5

→ 3, 4를 event_type=skipped, source=system,
   occurred_at=null, time_confidence=inferred,
   parent_event_id=(5번 이벤트) 로 생성
→ 5를 정상 저장
→ 마지막 확인 지점은 5로 전진
```

버스에서 정거장을 연달아 놓쳤을 때 버튼을 여러 번 누르게 하면 조작 부담이 크고 오입력이 늘기 때문이다.

- 자동 생성 `skipped`의 `occurred_at`을 **지어내지 않는다.** null로 두고 `parent_event_id`로 근거를 연결한다.
- 한 번에 건너뛸 수 있는 수는 `max_skip_stops`(초기 3)로 제한한다. 초과하면 확인을 요구한다 (`06`).
- 나중에 그 방문의 실제 관측이 지연 도착하면 **자동 `skipped`를 무효화하고** 실측으로 대체한다.

## 8. `visit_status` 전이

방문 하나가 차량 하나에 대해 갖는 상태다. 저장된 값이 아니라 이벤트에서 파생한다.

| 값 | 조건 |
|---|---|
| `upcoming` | 유효 이벤트 없음, 예상 시각 미도래 |
| `arrived` | arrived 있고 departed·passed 및 후속 방문 진행 근거 없음 |
| `departed` | `departed` 있음 |
| `passed` | `passed` 있음 |
| `passed_inferred` | skipped 또는 출발 누락 arrived 방문에 후속 유효 관측으로 진행이 확인됨. 실제 통과·출발 시각은 생성하지 않음 |
| `not_collected` | 수집 시작 방문보다 앞 — 중간 탑승 |
| `unknown` | 위 어디에도 해당하지 않음 |

### 구분해야 하는 것

- `not_collected`는 **실측 누락이 아니다.** 중간 탑승이면 그 앞 방문은 관측 대상이 아니었다. 회차 시작부터 탑승했다고 가정하지 않는다.
- GPS 수신 상태는 방문 상태와 분리한다. 예상 시각 경과만으로 통과·센서 미검출을 확정하지 않는다. 관측 없는 방문은 upcoming 또는 unknown으로 유지하며 위치 표시 규칙은 03, 자동 복구 확인 과제는 IMPROVEMENTS를 따른다.
- `passed_inferred`는 **실측 통과 시각이 없다.** 지나갔다는 사실만 안다.

## 9. 취소

입력 취소는 **원본을 삭제하지 않는다.**

- `validation_status = cancelled`로 바꾸고 `cancelled_at`·`cancel_reason`을 남긴다.
- 그 이벤트를 `parent_event_id`로 참조하던 자동 `skipped`가 무의미해지면 함께 무효화한다.
- 취소 후 마지막 유효 이벤트와 차량 상태·예측을 다시 계산한다.
- 이미 취소된 기록의 재취소는 거절한다. 되돌리려면 `13` 15장의 복구를 쓴다.
- `cancel_reason` 값은 09의 무효화 `reason`과 같은 이름을 쓴다 — 입력자 취소는 `observation_cancelled`, 관리자 기각은 `observation_rejected`. 두 곳에서 다른 이름을 쓰면 차단 사유를 되짚을 때 매핑표가 필요해진다.
- **과거에 학생에게 제공한 예측 이력은 삭제하지 않는다.** 근거 취소를 표시하여 평가에서 별도 분류한다 (`09`).

## 10. 수동과 GPS의 중복

같은 방문·같은 종류를 수동과 GPS가 모두 나타내면 **독립 원본을 모두 보존하고 중복 집계하지 않는다.** Phase 2 비교 단계는 `manual_reference` 정책을 사용한다. 입력 자체가 검증된 수동 기록을 대표로 삼고 GPS 기록은 `needs_review` 및 `comparison_only` 사유로 보존한다. 수동이 아직 없으면 GPS 원본만 보관하며 비교 단계의 공개 대표로 자동 승격하지 않는다. 검증되지 않은 수동 기록을 억지로 대표로 삼지 않는다. GPS 단독 운영 전환은 명시적 운영 정책 변경이며 `gps_primary`를 새 세션에 적용한다. 수신 순서로 대표를 바꾸지 않는다.

`manual_only`는 비교 대상이 없는 상태다. GPS 세션이 만들어지지 않으므로 대표 선택 자체가 일어나지 않으며, 수동 기록이 곧 유일한 원본이다. **정책이 `manual_only`인 세션에 GPS 이벤트가 들어오면 저장하지 않고 매핑 오류로 보관한다** — 정책을 자동으로 `manual_reference`로 올리지 않는다. 정책 전환은 새 세션에만 적용한다 (`06` 1장).

Phase 2 초기에는 두 기록을 **일부러 모두 남겨** 판별 정확도를 측정한다. 이때도 유효 이벤트는 하나뿐이다.

## 11. 검증 기준

| ID | 요구사항 | 확인 방법 |
|---|---|---|
| FR-OB-01 | 논리 관측 재전송이 1회만 저장 | 같은 `client_event_id`로 새 키 재전송 후 행 수 확인 |
| FR-OB-02 | 불변 내용 변조 거절 | 같은 ID·다른 `occurred_at` → `EVENT_ID_REUSED` |
| FR-OB-03 | 실시간 역행 거절, 지연 보충 반영 | 두 경로로 같은 과거 방문 입력 시 결과가 갈림 |
| FR-OB-04 | 재방문은 역행이 아님 | 순환 회차에서 같은 `stop_id` 두 번째 방문 입력 성공 |
| FR-OB-05 | 자동 `skipped`의 시각이 null | 3개 건너뛴 뒤 중간 두 행의 `occurred_at` 확인 |
| FR-OB-06 | 지연 실측이 자동 `skipped`를 대체 | 건너뛴 방문의 실제 기록을 나중에 전송 |
| FR-OB-07 | `interpolated`가 ETA에는 쓰이고 통계에는 안 쓰임 | 보간 이벤트만 있는 상태에서 예측 생성·표본 수 확인 |
| FR-OB-08 | 취소가 원본을 보존 | 취소 후 원본 행과 `cancelled_at` 존재 확인 |
| FR-OB-09 | 취소가 연동 `skipped`를 무효화 | `parent_event_id`로 연결된 행 상태 확인 |
| FR-OB-10 | `arrived`만 있는 차량이 통과로 분류되지 않음 | `visit_status = arrived` 유지 확인 |

## 12. 시계 신뢰도와 지연 수신

`received_at - occurred_at`은 수신 지연이며 시계 오류의 단독 근거가 아니다. 기록 발생 시각 원문을 조용히 보정하지 않는다.

`clock_checks(clock_check_id, collection_session_id, checked_at, estimated_offset_seconds, uncertainty_seconds, valid_until)`에 서버가 측정·검증한 근거를 보관한다. 단말 보고값만으로 verified로 만들지 않는다. `abs(estimated_offset_seconds) + uncertainty_seconds <= clock_skew_tolerance_seconds`이고 발생 시각이 검증 유효범위 안일 때 시계 조건을 통과한다. 단말 시계가 바뀌면 검증을 무효화한다. 시각 교환 방법·유효기간은 실측 전 정하며, 근거가 없거나 설정이 미정이면 검토 대기로 저장한다.

수집 기간·보관 허용기간은 별도 조건이다. 종료 후 도착한 기록도 발생 시각이 유효 수집 기간 안이면 검토·채택할 수 있다. 수신이 늦었다는 이유만으로 현재 위치를 뒤로 이동시키거나 종료된 세션을 재개하지 않는다.

**시각 교환 방법 (구현 확정):** NTP 방식 네 시각을 쓴다. ① 단말이 송신 시각 t0를 보내면(`POST /collection-sessions/{id}/clock-checks`) 서버가 수신 t1·응답 t2를 기록해 돌려주고, ② 단말이 수신 시각 t3를 보내면(`POST /clock-checks/{id}/complete`) 서버가 `estimated_offset_seconds = ((t0−t1)+(t3−t2))/2`(단말 − 서버), `uncertainty_seconds = ((t3−t0)−(t2−t1))/2`를 계산한다. 서버 시각 둘을 서버가 보관하므로 단말 보고만으로 검증되지 않는다. 관측 발생 시각이 `checked_at ± clock_check_valid_seconds` 안이어야 근거로 인정한다. **시험값 (2026-09-15 승인, 실측 후 교체):** `clock_skew_tolerance_seconds` 5초, `clock_check_valid_seconds` 6시간, `pending_input_retention_hours` 24시간, `realtime_input_window_seconds` 120초. 값을 비우면 `clock_unverified` 등으로 검토 대기다.

### `review_reason` 값

| 값 | 판정 |
|---|---|
| order_backward_window_undefined | 역행 입력인데 `realtime_input_window_seconds` 미정 |
| before_collection_start | 중간 탑승 시작 방문보다 앞 |
| duplicate_observation | 같은 방문·종류의 유효 관측이 이미 있음 |
| departed_before_arrived | 먼저 있는 arrived보다 이른 departed |
| conflicting_event_types | 같은 방문의 arrived와 passed 충돌 |
| outside_collection_period | 세션 시작~종료 밖. 열린 세션의 끝은 수신 시각 + `clock_skew_tolerance_seconds` (미래 발생 시각 차단) |
| clock_unverified / clock_skew_exceeded / clock_check_out_of_range | 시계 근거 없음·설정 미정 / 허용 초과 / 유효 범위 밖 |
| retention_undefined / retention_exceeded | 보관 허용기간 미정 / 초과 |

여러 사유는 쉼표로 함께 싣는다. 지연 실측이 자동 `skipped`를 대체하면 그 skipped의 `cancel_reason`은 `superseded_by_observation`이다 (사용자 취소·기각과 구분).

검토 결정은 13의 `review_observation`으로 처리한다. 초기 실측 시작 전 시계 검증 설정 또는 관리자 검토 경로를 준비한다.

### 추가 검증 기준

| ID | 사례 | 기대 결과 |
|---|---|---|
| FR-OB-11 | 단말 순번 2와 서버 자동 누락 2개 | 서버 순번은 null, 다음 단말 순번 3 저장 가능 |
| FR-OB-12 | 시계 검증 통과 기록이 통신 장애로 늦게 도착 | 수신 지연만으로 시계 오류 처리하지 않음 |
| FR-OB-13 | 수동·GPS 수신 순서를 바꾸어 비교 | manual_reference에서 공개 대표와 비교 원본 수가 동일 |
| FR-OB-14 | GPS 생존 중 실제 교통 지연 | 통과 미확인으로만 표시, 확정 미검출률에 포함하지 않음 |

### 같은 방문의 사건 전이

arrived→departed는 허용한다. passed는 비정차 통과 기록이다. 같은 방문에 arrived와 passed가 충돌하면 후속 입력을 needs_review로 보존하고 임의 상태 우선순위로 덮지 않는다. departed 단독은 직접 출발을 확인한 경우 허용하되 먼저 있는 arrived보다 발생 시각이 앞서면 검토한다. 후속 방문이 확인되어도 이전 arrived에 가짜 departed 시각을 생성하지 않는다. 이전 방문이 더 이상 승차 가능하지 않은 것은 후속 유효 진행 근거로 판정하며 visit_status=passed_inferred로 표시할 수 있고 관련 부모 근거를 보존한다. 최초 도착 실측은 삭제하지 않는다. 노선 기반 GPS 공백 자동 추론은 별도 확인 대기다.

### v7.8 취소 이력·복구 연결

모든 취소는 13의 observation_reviews에 이전 상태와 취소 사유를 추가 기록한다. 취소된 표본을 사용한 통계는 09의 무효화 기록으로 즉시 차단하고 08의 영향 예측 갱신을 함께 수행한다. 오취소 복구는 13의 별도 restore 계약만 사용한다. 원본 사건과 event_id를 보존하며, 성공 후 현재 취소 필드는 비우되 과거 취소 사실은 이력에 남긴다. 취소 복구만으로 기존 통계 차단을 해제하지 않는다.
