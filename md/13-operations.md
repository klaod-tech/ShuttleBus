# 13 · 운영 관리

> 관리자가 실제 운행 완료를 확정하고, 회차를 취소하고, 공지를 관리하고, 검토가 필요한 기록을 처리한다.
> 참조: [공통 규약](01-conventions.md) · [상태 계약](03-state-contract.md)

**수집 종료(`06`)와 운행 완료는 다르다.** 이 문서는 그 차이를 다룬다.

---

## 1. 왜 자동으로 확정하지 않나

시스템은 두 가지를 구분할 수 없다.

```
버스가 일찍 운행을 마쳤다        →  실제 완료
입력자가 기록을 놓쳤다           →  기록 누락
```

둘 다 "관측이 끊긴 채 시간이 지남"으로 보인다. **예상 종료 시각만으로 실제 운행 완료를 기록하지 않는다.** 근거가 없을 때의 판단은 관리자에게 맡긴다.

금지되는 것은 **근거 없는 자동 완료**이지 자동 완료 자체가 아니다. 종점 방문에 유효 관측이 있으면 그것은 시간 경과가 아니라 실측이므로 완료 근거가 된다. Phase 1은 그런 관측이 드물어 사실상 전부 관리자 확정이지만, Phase 2에서 단말이 종점 도착을 기록하면 3장의 규칙으로 자동 확정할 수 있다.

## 2. 검토 대상 판정

`mark_sessions_for_review` — 주기 실행.

```
기준 시각 = 마지막 유효 관측의 occurred_at
           없으면 예정 기점 출발 시각

기한 = 기준 시각
     + 기준 지점부터 종점까지 예상 소요시간
     + session_review_grace_seconds

기한 경과 AND 완료 근거 없음
  → review_required = true, review_reason 기록
  → 열린 세션(ended_at IS NULL)만 collection_status = needs_review
  → 이미 종료된 세션은 ended 유지
```

**구간 소요시간 값이 없으면 검토 대상으로 올리지 않는다.** 기한을 계산할 근거가 없기 때문이다. `travel_times`가 비어 있는 초기에는 모든 회차가 걸려 목록이 무의미해지므로, 대체 기한을 따로 두지 않고 통계가 쌓인 구간부터 판정을 시작한다.

### 학생 화면에는 어떻게 보이나

`needs_review`가 되어도 **"운행 완료"로 표시하지 않는다.** 정보 신선도는 실제 관측 나이로 별도 판단하고 화면은 "최신 통과 정보 확인 필요"와 마지막 기록·시간표를 보여준다 (`03` 7장).

**`needs_review`는 버스가 운행을 마쳤다는 뜻이 아니다.**

### CronJob의 역할

확인이 필요한 회차를 관리자 목록에 반영한다. **별도 외부 알림은 후속 기능이다.**

## 3. 차량 완료 확정

`POST /api/v1/admin/trip-vehicles/{trip_vehicle_id}/completion`

| 요청 | 설명 |
|---|---|
| `evidence_type` | 완료 근거의 종류 |
| `note` | 관리자 메모 |
| `observed_completed_at` | 실제 완료 시각. 확인된 경우만 |
| `expected_control_version` | 낙관적 잠금 |

### 규칙

- **차량 단위다.** 한 차량이 종점에 도착해도 다른 슬롯을 완료 처리하지 않는다.
- **실제 근거가 있을 때만 확정한다.** 단순 기록 정리는 실측 완료 시각을 생성하지 않는다.
- `observed_completed_at`을 지어내지 않는다. 근거가 없으면 null로 두고 `evidence_type`만 기록한다.
- 회차 명시 취소 또는 모든 슬롯 취소이면 `cancelled`다. 취소가 아니고 모든 슬롯이 완료·취소이면서 최소 한 슬롯이 완료이면 `completed`다. 나머지는 회차의 예정·운행 상태를 유지한다. 빈 슬롯 집합을 완료로 집계하지 않는다.

### `evidence_type`

| 값 | 의미 | 누가 만드나 |
|---|---|---|
| `terminal_observation` | 종점 방문의 유효 관측(arrived 또는 passed) | 서버 자동 또는 관리자 |
| `collector_report` | 입력자가 운행 종료를 확인해 전달 | 관리자 |
| `operator_notice` | 운영 측 안내·연락 | 관리자 |
| `admin_judgement` | 위 어디에도 해당하지 않는 관리자 판단 | 관리자 |

`terminal_observation`만 자동 확정이 가능하다. 조건은 **회차 마지막 방문에 `validation_status = valid`이고 `time_confidence ∈ {observed, interpolated}`인 관측이 있을 것**이다. `inferred`와 `skipped`는 근거가 아니다. 이때 `observed_completed_at`은 그 관측의 `occurred_at`이며, `time_confidence = interpolated`이면 자동 확정하되 근거가 보간임을 결정 이력에 남긴다.

자동 확정도 3장의 나머지 규칙을 그대로 따른다. **차량 단위이며 다른 슬롯에 번지지 않는다.** 회차 완료는 모든 슬롯이 완료·취소이고 최소 한 슬롯이 완료일 때만이다.

GPS 세션 종료(`07` 1장)와 완료 확정은 별개다. `end_reason = signal_lost`나 `service_day_closed`는 근거가 아니라 수집이 멈춘 사정이므로 완료를 만들지 않는다.

### 완료 근거의 취소

완료 근거로 쓴 이벤트가 나중에 취소되면 **관리자 재검토 대상으로 남긴다.** 자동으로 완료를 해제하지 않는다.

## 4. 회차 취소

`POST /api/v1/admin/scheduled-trips/{trip_id}/cancellation`

| 요청 | 설명 |
|---|---|
| `reason` | 취소 사유 |
| `expected_control_version` | 낙관적 잠금 |

### 규칙

- **공지 유형 `cancel`만으로 취소하지 않는다.** 명시적인 취소 요청이 필요하다. 공지는 안내이고 취소는 상태 변경이다.
- 회차 취소는 소속 차량 슬롯을 전부 `cancelled`로 만든다.
- 이미 공개한 회차를 취소하면 **사유와 상태 변경을 전송한다** (`12`).
- 학생 화면은 결정 트리 2번에서 "운행 취소"와 사유를 표시한다 (`03` 6장).

### 취소 후 늦게 도착한 기록

실제 관측 시각이 유효 수집 기간 안이면 검토 후 이력에 보충할 수 있다. **다만 차량·회차를 자동으로 재개하지 않는다.**

## 5. 버전 사용

관리 변경에는 `control_version`을 쓴다 (`01` 3장).

```
차량 완료 · 회차 취소
  → expected_control_version 검증
  → 불일치면 CONTROL_VERSION_CONFLICT
  → 같은 트랜잭션에서 control_version 과 state_version 을 함께 증가
```

**`state_version`을 함께 올리는 이유**는 취소와 완료가 학생에게 보이는 상태를 바꾸기 때문이다. 올리지 않으면 낮은 버전을 되돌리지 않는 규칙과 맞물려 학생 화면이 변경을 반영하지 못한다.

일반 관측 입력은 input_version 및 공개 변경 시 state_version을, 순수 ETA 갱신은 state_version만 증가시킨다. 관측 검토는 §13의 별도 관리 변경이다. 따라서 **관리자가 들고 있는 `expected_control_version`은 학생 화면의 잦은 갱신에 영향받지 않는다.**

## 6. 공지

| 테이블 `notices` | 설명 |
|---|---|
| `notice_id` | PK |
| `route_id` | 대상 노선 |
| `scheduled_trip_id` | 특정 회차 대상이면. null이면 노선 전체 |
| `notice_type` | `delay` / `cancel` / `info` |
| `message` | 내용 |
| `created_at` | |
| `expires_at` | 만료 예정 시각 |
| `expired_early_at` | 관리자가 먼저 내린 시각 |

### 유효 판정

```
expired_early_at IS NULL
AND now() < expires_at
```

### API

| 경로 | 동작 |
|---|---|
| `GET /notices` | `route_id`, 선택 `trip_id` → 현재 유효 공지 |
| `POST /admin/notices` | 공지 생성 |
| `POST /admin/notices/{notice_id}/expire` | `expired_early_at`을 현재 시각으로 설정 |

`GET /notices`는 **인증이 필요 없다.** 학생이 읽는다.

### 전송

공지 생성·만료 시 범위에 맞는 룸으로 `notice:changed`를 보낸다 (`12` 2장). 화면은 유효 공지를 다시 조회하고, **만료 시각이 되면 서버 이벤트를 기다리지 않고 배너를 제거한다.**

## 7. 기록 조회

| 경로 | 입력 | 응답 |
|---|---|---|
| `GET /admin/collection-sessions` | `service_date`, 선택 `collection_status` | 수집 기록 목록. 검토 대상 필터 |
| `GET /admin/collection-sessions/{id}/events` | — | 취소·누락 포함 전체 이력 |

**취소된 기록과 자동 누락도 보여준다.** 관리자가 무슨 일이 있었는지 재구성할 수 있어야 한다.

## 8. 관리 화면

| 화면 | 표시·동작 |
|---|---|
| 검토 목록 | `needs_review` 세션. 마지막 관측, 기한 초과 시간, 누락 방문 |
| 세션 상세 | 전체 이벤트 이력. 취소·누락·검토 대기 구분, 개별 관측 승인·기각 |
| 완료 확정 | 근거 종류 선택, 메모, 실제 완료 시각(선택) |
| 회차 취소 | 사유 입력. 확인 단계 필요 |
| 공지 관리 | 생성, 목록, 조기 만료 |
| 매핑 오류 | GPS 회차 배정 실패 목록 (Phase 2) |
| 승격 보류 | 자동 승격이 걸린 통계 스냅샷. 실패한 게이트, 사라진 구간 목록, 활성화·롤백 |

### 승격 보류 목록

통계 스냅샷은 게이트를 통과하면 자동 승격된다 (`08` 4장). **이 목록에는 걸린 것만 올라온다.**

| 사유 | 관리자가 할 일 |
|---|---|
| 커버리지 퇴행 — 구간이 사라짐 | 사라진 구간의 표본 취소가 타당한지 확인. 타당하면 활성화, 오취소면 검토에서 되살림 |
| 스냅샷 불완전 | 활성화하지 않는다. 다음 재계산을 기다린다 |
| `path_model_version` 변경 | 경로 구성 변경이 의도한 것인지 확인 후 활성화 |
| `auto_promote_enabled = false` | 게이트 결과를 보고 직접 활성화 |

**평상시에는 비어 있는 목록이다.** 항목이 쌓이면 자동 승격이 계속 막히고 있다는 뜻이므로 원인을 봐야 한다. 활성화와 롤백은 08의 함수를 호출하며 `control_version`을 쓰지 않는다 — 회차 상태가 아니라 계산 모델의 변경이다.

### 확정 화면에서 지키는 것

- **"기록을 정리한다"와 "운행이 끝났음을 확인한다"를 다른 문구로 쓴다.**
- 실제 완료를 확인할 근거가 없는 경우에는 완료 대신 검토 대기로 남긴다. 완료 근거는 필수이며 실제 완료 시각만 미상인 경우 observed_completed_at은 null일 수 있다.
- 취소는 되돌리기 어려우므로 확인 단계를 둔다.

## 9. 차량 교체

운행 중 실제 차량이 바뀌는 경우가 있다.

| 규칙 | 내용 |
|---|---|
| 표본 | **서로 다른 실제 차량 기록을 같은 연속 구간 표본으로 합치지 않는다** (`09` 2장) |
| 이력 | 원래 배정 이력을 덮어쓰지 않는다 |
| 처리 | 관리자 검토로 남긴다 |
| 자동 교체 | **후속 기능.** MVP 범위 밖 |

## 10. 미정 운영값

| 항목 | 예상 충돌 | 결정 전 처리 |
|---|---|---|
| `session_review_grace_seconds` | 너무 짧으면 정상 운행이 검토 대상, 길면 놓친 기록을 늦게 발견 | 실측 후 확정 |
| 여러 입력자 인계 절차 | 같은 차량 이벤트 순서 충돌 | MVP는 한 세션 한 입력자, 인계는 관리자 확인 |
| 운행 이력 보존 기간 | — | 정리 작업 미적용 |
| 자동 완료 적용 시점 | 종점 판별 정확도가 낮으면 조기 완료 | Phase 2 비교 지표(`07` 8장)가 안정된 뒤 활성화. 그전에는 관리자 확정 |

## 11. 함수

| 함수 | 입력 → 결과 | 핵심 규칙 |
|---|---|---|
| `mark_sessions_for_review` | 현재 시각 → 검토 목록 | 운행 완료로 단정 금지 |
| `complete_trip_vehicle` | 차량 슬롯·근거·기대 버전 → 완료 | 다른 슬롯 상태 유지 |
| `cancel_scheduled_trip` | 회차·사유·기대 버전 → 취소 | 공지와 별개 명시 요청 |
| `create_notice` | 노선·회차·유형·내용·만료 → 공지 | 범위 룸으로 전송 |
| `expire_notice` | noticeId → 조기 만료 | `expired_early_at` 설정 |
| `completeTripVehicle` | tripVehicleId·근거·기대 버전 → 완료 | 근거 종류 필수 |
| `cancelScheduledTrip` | tripId·사유·기대 버전 → 취소 | 확인 단계 |
| `expireNotice` | noticeId → 만료 | 조기 만료 표시 |
| `review_observation` | eventId·결정·근거·입력/관리 기대 버전 → 검토 결과 | 원본 보존, 재검증, 재계산 연결 |
| `reviewObservation` | 검토 기록·결정 → 관리 API | 승인·기각 결과와 충돌 안내 |
| `review_completion` | 완료 결정·재검토 결과·관리 기대 버전 → 결정 이력 | 자동 재개 금지 |

이름이 `snake_case`이면 서버, `camelCase`이면 화면 함수다 (`01` 8장). 별도 표기를 붙이지 않으며 짝을 이루는 함수는 같은 어간을 쓴다.

## 12. 검증 기준

| ID | 요구사항 | 확인 방법 |
|---|---|---|
| FR-OP-01 | 수집 종료가 운행 완료로 안 됨 | 종료 후 `operation_status` 확인 |
| FR-OP-02 | 기한 초과만으로는 완료 안 됨 | 종점 관측 없이 기한 경과 시 `needs_review`만, 완료 미발생 |
| FR-OP-03 | `needs_review`가 학생에게 완료로 안 보임 | 화면 문구 확인 |
| FR-OP-04 | 차량 완료가 다른 슬롯에 안 번짐 | 2대 회차에서 한 대만 완료 |
| FR-OP-05 | 모든 슬롯 완료 시 회차 완료 | 두 대 모두 완료 |
| FR-OP-06 | 회차 취소가 차량 전부를 취소 | 취소 후 슬롯 상태 |
| FR-OP-07 | 공지 `cancel`만으로 취소 안 됨 | 공지 생성 후 `operation_status` 불변 |
| FR-OP-08 | `control_version` 증가 시 `state_version` 동반 증가 | 취소 전후 두 버전 |
| FR-OP-09 | 관측 입력이 `control_version`을 안 올림 | 입력 전후 확인 |
| FR-OP-10 | 취소가 학생 화면에 전파 | `trip:state` 수신 확인 |
| FR-OP-11 | 조기 만료 후 공지가 사라짐 | `GET /notices` 응답 |
| FR-OP-12 | 완료 근거 취소가 재검토로 남음 | 근거 이벤트 취소 후 상태 |
| FR-OP-13 | 취소 후 늦은 기록이 회차를 재개 안 함 | 취소 후 지연 전송 |

## 13. 검토 대기 관측의 결정

`POST /api/v1/admin/events/{event_id}/review`

| 요청 | 설명 |
|---|---|
| `decision` | approve / reject |
| `reason`, `evidence_note` | 판단 사유와 확인 근거 |
| `expected_input_version` | 대상 생산자 세션 버전 |
| `expected_control_version` | 회차 관리 버전 |

Idempotency-Key와 관리자 권한을 검증한다. 회차 잠금 아래 대상이 여전히 needs_review인지, 사건의 소속·시각·순서·시계 근거·유효 관측 유일성이 맞는지 다시 확인한다. 근거 없는 승인이나 이미 대표가 있는 비교용 GPS의 중복 승인은 허용하지 않는다. 대상 변경은 REVIEW_CONFLICT, 버전 불일치는 01의 해당 충돌 코드를 반환한다.

- approve: validation_status=valid. 공개 상태·남은 ETA를 재계산하고 이미 집계된 구간은 재집계 대상으로 등록한다. 지연 승인으로 현재 위치를 뒤로 옮기거나 완료·취소 회차를 재개하지 않는다.
- reject: validation_status=cancelled, cancelled_at 및 cancel_reason=observation_rejected를 기록한다. 원본 필드를 삭제하지 않는다. **같은 트랜잭션에서 09의 무효화 등록과 08의 영향 갱신을 함께 확정한다** — 그 표본을 사용한 모든 `travel_times` 행을 `travel_time_invalidations`에 `reason=observation_rejected`로 멱등 등록하고, 영향 회차의 예측·`state_version`·outbox를 갱신한다 (`09` 10장, `08` 11장). 야간 배치를 기다리지 않는다. 입력자 취소(`02` 9장)도 같은 등록 경로를 쓰며 `reason=observation_cancelled`다.
- 원본 occurred_at을 수정하는 API는 아니다. 시각을 확인할 수 없으면 보류하거나 기각한다. 시각 정정이 필요한 별도 편집 계약은 후속으로 정의하며 이번 승인 경로에서 임의 시각을 만들지 않는다.

`observation_reviews(review_id, event_id, decision, reason, evidence_note, reviewed_by, reviewed_at, input_version, control_version)`에 결정 이력을 저장한다. 새 결정은 input_version·control_version·state_version과 상태/전송을 한 트랜잭션에서 확정한다. 재전송은 동일 결과를 반환하며 중복 결정하지 않는다. 세션 ended 여부와 관측 검토 여부는 독립이다.

## 14. 완료 근거 재검토와 결정 이력

`operation_decisions(decision_id, trip_id, trip_vehicle_id, decision_type, evidence_type, evidence_event_id, note, observed_completed_at, decided_by, decided_at, supersedes_decision_id, control_version)`에 완료·취소·정정 이력을 남긴다. 이벤트 근거의 취소는 review_required를 올리고 기존 완료를 즉시 해제하지 않는다.

**구현 확정 (2026-09-15):** `decision_type`은 `complete`(차량 완료) / `cancel_trip`(회차 취소, 차량 없음, 사유는 `note`) / `keep_completed` / `reopen`이다. `decided_by = null`은 서버 자동 완료다. 완료 재검토 필요 여부는 별도 열에 저장하지 않고 **대체되지 않은 최근 완료 결정의 `evidence_event_id`가 더 이상 `valid`가 아닌지**로 파생한다. 관리자 수집 기록 목록의 `completion_review_required`로 보인다.

`POST /api/v1/admin/trip-vehicles/{trip_vehicle_id}/completion-review`는 `decision=keep_completed|reopen`, 대체 근거 또는 사유, expected_control_version을 받는다. keep_completed는 새 근거를 요구한다. reopen은 관리자가 실제 완료 오판을 확인한 경우만 허용하고 취소 회차에는 적용하지 않는다. 이전 결정은 보존하고 상태·control_version·state_version·outbox를 함께 확정한다. 단순히 오래된 기록을 정리하려고 다시 운행 중으로 만들지 않는다.

| ID | 사례 | 기대 결과 |
|---|---|---|
| FR-OP-14 | 모든 차량 슬롯 취소 | 회차 cancelled, completed 아님 |
| FR-OP-15 | 검토 대기 승인·기각 및 동일 요청 재전송 | 원본·결정 이력 보존, 각 결정은 한 번 반영 |
| FR-OP-16 | 완료 근거 취소 | 자동 재개 없이 재검토 표시, 명시적 결정만 상태 변경 |
| FR-OP-17 | 종료 세션의 검토 기한 경과 | ended 유지, review_required로 별도 표시 |
| FR-OP-18 | 종점 유효 관측 존재 | `terminal_observation`으로 자동 완료, `observed_completed_at`이 그 관측 시각 |
| FR-OP-19 | 종점 관측이 inferred·skipped | 자동 완료 금지, 검토 대기 |
| FR-OP-20 | 2대 회차에서 한 대만 종점 도착 | 그 슬롯만 완료, 회차는 미완료 |
| FR-OP-21 | `signal_lost`로 GPS 세션 종료 | 완료 미발생, 운행 상태 불변 |

03의 표시 우선순위에 따라 완료 차량은 ‘이번 운행 종료’를 표시한다. 과거 arrived 기록 때문에 출발 미확인으로 되돌아가지 않는다.

## 운영 구현 메모 (P3 2부, 2026-09-15)

설계에 명시되지 않아 구현에서 정한 것이다. 다르면 이 절과 `app/operations`를 함께 고친다.

| 항목 | 결정 |
|---|---|
| 자동 완료와 `control_version` | 종점 실측으로 인한 자동 완료는 관측 입력 경로이므로 `control_version`을 올리지 않는다 (FR-OP-09). `state_version`만 오르고 결정 행에는 당시 `control_version`을 기록한다 |
| 자동 완료 적용 범위 | 수동 입력의 종점 유효 실측(arrived·passed, observed·interpolated)과, 승인·복구로 유효가 된 종점 관측. GPS 판별 결과의 자동 완료는 10장대로 P6 비교 지표 이후 |
| 관리자의 `terminal_observation` 선택 | `evidence_event_id`로 그 차량의 종점 유효 실측을 지정해야 한다. `observed_completed_at`은 그 관측 시각 |
| 회차 취소와 완료 슬롯 | 이미 완료된 슬롯은 `completed`로 둔다(실제 운행 사실). 나머지 슬롯이 `cancelled`, 회차는 `cancelled`. 이미 완료·취소된 회차의 취소는 `OPERATION_STATE_CONFLICT` |
| 차량 슬롯 개별 취소 | API 없음. 모든 슬롯이 취소면 회차가 `cancelled`라는 집계 규칙만 둔다 (FR-OP-14) |
| `reopen` 후 상태 | 차량 `scheduled`. 회차가 completed였다면 예정·운행 상태로 되돌린다 |
| 검토 승인의 재확인 | 한 방문 한 유효 관측(`REVIEW_CONFLICT`), 같은 방문 도착·통과 공존 금지(`REVIEW_CONFLICT`), 다른 유효 관측과 시각 순서(`EVENT_ORDER_CONFLICT`). 시계·보관 사유는 관리자가 근거(`evidence_note` 필수)로 넘는다 |
| 승인·복구의 파생 | 입력 경로와 같은 함수로 누락 대체·자동 누락 생성·기점 출발 연결·자동 완료를 적용한다. 복구 시 파생 `skipped`는 새 행으로 다시 계산한다 |
| 버전 | 검토·복구는 `input_version`·`control_version`·`state_version`을 모두 올린다 |
| 관리자 취소 | 관리자는 다른 입력자의 관측도 `POST /events/{id}/cancel`로 취소할 수 있다 (15장 대체 관측 정리) |
| 공지 조회 | `trip_id`를 주면 노선 전체 공지 + 그 회차 공지, 생략하면 노선의 모든 유효 공지 |
| 검토 대상 판정 | `python -m app.jobs mark-sessions-for-review`. P5 `travel_times`와 `session_review_grace_seconds`가 없으면 0건 (2장) |
| 후속 연결 | 기각·취소의 `travel_time_invalidations` 등록과 재집계 등록은 P5, outbox·`notice:changed`·`trip:state` 전송은 P4에서 같은 트랜잭션에 붙인다 |

## 15. 오취소 복구

`POST /api/v1/admin/events/{event_id}/restore`

취소를 되돌리는 유일한 경로다. 13장의 검토 결정과 **분리한다.** 검토 결정은 `needs_review`에서 나가는 전이만 다루고 대상이 여전히 `needs_review`인지 확인하는 가드를 갖는다. 복구는 `cancelled`에서 들어오는 전이이며 확인할 충돌이 다르다. 한 엔드포인트에 끼우면 그 가드를 풀어야 한다.

| 요청 | 설명 |
|---|---|
| `reason` | 왜 오취소였는지 |
| `evidence_note` | 원래 관측이 맞다고 판단한 근거 |
| `expected_input_version` | 대상 생산자 세션 버전 |
| `expected_control_version` | 회차 관리 버전 |

Idempotency-Key와 관리자 권한을 검증한다. 회차 잠금 아래 처리한다.

### 어디로 돌아가나

**`valid`가 아니라 취소 직전 상태로 돌아간다.** `observation_reviews`에 남긴 이전 `validation_status`를 읽어 그 값으로 되돌린다. 취소 전이 `needs_review`였다면 복구 결과도 `needs_review`이며, 그 뒤 승인은 13장의 검토 결정을 다시 거친다. 복구가 검토를 대신하지 않는다.

`event_id`와 원본 `occurred_at`·좌표를 그대로 쓴다. 새 사건을 만들지 않는다. `cancelled_at`·`cancel_reason`은 비우되 취소가 있었다는 사실은 `observation_reviews` 이력에 남는다.

### 거절 조건

| 조건 | 코드 |
|---|---|
| 대상이 `cancelled`가 아님 | `REVIEW_CONFLICT` |
| 같은 `trip_stop_id`·`event_type`에 이미 다른 유효 관측이 있음 | `RESTORE_CONFLICT` |
| 복구하면 이후 유효 관측과 순서가 어긋남 (`02` 6장 재적용) | `EVENT_ORDER_CONFLICT` |
| 버전 불일치 | `INPUT_VERSION_CONFLICT` · `CONTROL_VERSION_CONFLICT` |

두 번째가 핵심이다. 취소 이후 관리자가 대체 관측을 넣었을 수 있고, 그대로 복구하면 **한 방문에 유효 관측이 둘이 된다.** 자동으로 어느 쪽을 이기게 하지 않는다. 관리자가 대체 관측을 먼저 취소해야 한다.

### 복구가 하지 않는 것

- **기존 통계 차단을 해제하지 않는다.** `travel_time_invalidations`의 행은 남는다 (`09` 10장). 복구된 표본은 **다음 스냅샷에서만** 반영된다. 복구 사실만으로 과거 통계값이나 과거 예측이 다시 공개되지 않는다.
- **완료·취소 회차를 재개하지 않는다.** 그 회차의 복구는 통계 표본으로만 쓰이고 공개 상태는 그대로다. 운행 상태를 바꾸려면 14장의 완료 근거 재검토를 따로 쓴다.
- **파생 행을 되살리지 않는다.** 취소로 무효화된 연동 `skipped`(`02` FR-OB-09)는 복구 대상이 아니라 재계산 대상이다. 파생은 재계산 경로가 다시 만든다.
- **`auto_promotion_blocked`를 풀지 않는다** (`08` 11장).

### 확정하는 것

회차가 아직 진행 중이면 공개 상태와 남은 ETA를 재계산한다. 이미 집계된 구간은 재집계 대상으로 등록한다 — 13장 `approve`와 같다. `observation_reviews`에 `decision=restore` 행을 추가하고, 상태·`input_version`·`control_version`·`state_version`·outbox를 한 트랜잭션에서 확정한다. 재전송은 동일 결과를 반환한다.

`observation_reviews`에 `previous_validation_status` 열을 추가한다. 취소·기각 시 이전 상태를 기록해야 복구가 돌아갈 곳을 안다. 이 열 없이는 복구가 `valid`를 추측하게 된다.

| ID | 사례 | 기대 결과 |
|---|---|---|
| FR-OP-22 | `needs_review`에서 기각된 관측 복구 | `needs_review`로 복귀, 자동 승인 없음 |
| FR-OP-23 | 취소 후 대체 관측이 들어온 방문의 복구 | `RESTORE_CONFLICT`, 유효 관측 둘 생기지 않음 |
| FR-OP-24 | 복구 요청 재전송 | 동일 결과, 이력 한 건 |
| FR-OP-25 | 복구 후 기존 통계 조회 | 차단 유지, 새 스냅샷에서만 재반영 |
| FR-OP-26 | 완료 확정된 회차의 관측 복구 | 표본만 복구, 운행 재개 없음 |
