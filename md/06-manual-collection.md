# 06 · 수동 관측 수집

> 동승한 입력자가 버튼으로 통과를 기록한다. Phase 1의 유일한 수집 경로이며, **Phase 2에서도 GPS 검증용으로 계속 쓴다.**
> 참조: [공통 규약](01-conventions.md) · [관측 계약](02-observation-contract.md)

이 문서는 **관측을 어떻게 만드는가**를 다룬다. 관측이 무엇인지는 `02`가 정의한다. GPS 수집(`07`)과 서로 참조하지 않는다.

---

## 1. 수집 세션

세션은 **한 생산자가 한 차량 슬롯을 관측하는 단위**다. Phase 1 생산자는 입력자이며 Phase 2 GPS는 별도 생산자 세션을 사용한다.

| 열 | 설명 |
|---|---|
| `collection_session_id` | PK |
| `trip_vehicle_id` | 관측 대상 차량 슬롯 |
| `shuttle_id` | 실제 차량. 확인되면 기록 |
| `collector_id` | 수동 입력자 계정. GPS 세션은 null |
| `producer_type` | manual / gps |
| `device_id` | GPS 단말 ID. 수동 세션은 null |
| `comparison_policy` | manual_only / manual_reference / gps_primary. 세션 생성 시 확정 |
| `review_required`, `review_reason` | 검토 플래그와 사유. 종료 상태와 별개 |
| `collection_start_trip_stop_id` | 중간 탑승 시 시작 방문 |
| `collection_status` | not_started / collecting / ended / needs_review |
| `input_version` | 입력 충돌 검사용 (`01` 3장) |
| `writer_instance_id` | 수동 세션의 쓰기 기기 식별자. 동시 기기 순번 충돌 방지 |
| `end_reason` | 종료 사유. GPS 세션은 `07` 1장의 네 값, 수동 세션은 null |
| `started_at`, `ended_at` | |

`UNIQUE (trip_vehicle_id, producer_type) WHERE ended_at IS NULL` — 차량 슬롯당 열린 수동 세션 하나와 열린 GPS 세션 하나를 허용한다. 종료 상태는 ended_at과 일치시킨다. `needs_review`라도 ended_at이 null이면 열린 세션이다. 생산자 종류별로 순번과 소유권을 분리한다.

### 소유권

| 상황 | 처리 |
|---|---|
| 같은 입력자가 같은 슬롯의 열린 세션을 다시 시작 | **기존 열린 세션을 반환한다.** 새로 만들지 않는다 |
| 종료 후 다시 수집 | 명시적인 새 시작 요청으로 새 세션 생성. 기존 세션의 발생 시각·순번·소유권은 보존 |
| 다른 입력자가 점유 중인 슬롯 | `SESSION_OWNERSHIP_CONFLICT` |
| 인계가 필요한 경우 | 관리자 확인. **자동 인계는 MVP 범위 밖**. 기기 분실·앱 재설치로 점유가 풀리지 않으면 관리자가 `POST /collection-sessions/{id}/end`로 종료하고, 입력자가 새 세션을 시작한다 (2026-09-15) |

여러 입력자가 같은 차량을 동시에 기록하면 이벤트 순서가 충돌한다. **MVP는 열린 수동 세션 하나·세션당 입력자 하나다.** 로그인 계정이 같아도 복수 기기에서 동시에 순번을 발급하지 않는다. 수집 시작 시 writer_instance_id를 배정하고 같은 세션의 다른 기기 시작은 SESSION_OWNERSHIP_CONFLICT로 거절한다. 새로고침은 기존 writer_instance_id를 로컬에서 복구한다. GPS 세션은 별도의 단말 소유권을 검사한다.

### 중간 탑승

회차 도중에 타면 `collection_start_trip_stop_id`를 지정한다. 그 앞 방문은 `not_collected`이며 **실측 누락과 구분한다** (`02` 8장). 회차 시작부터 탑승했다고 가정하지 않는다.

이전 방문을 가짜 통과나 누락 실측으로 만들지 않는다.

### 수집 종료 ≠ 운행 완료

`ended_at`은 **입력자가 기록을 그만둔 시각**이다. 버스가 운행을 마쳤다는 뜻이 아니다. 실제 완료 확정은 관리자 몫이다 (`13`).

화면에서도 두 버튼을 분리하고 문구를 다르게 쓴다.

## 2. 입력 흐름

```
버튼 클릭
  └ occurred_at, client_event_id, client_sequence 즉시 저장
  └ 로컬 영속 큐에 넣고 '전송 대기' 표시
      └ 전송 시도
          ├ 성공     → 큐에서 제거, 확정 표시
          ├ 통신 실패 → '재전송 대기', 같은 Idempotency-Key로 재시도
          └ 409      → 코드별 처리 (아래 4장)
```

**버튼을 누른 순간의 시각이 `occurred_at`이다.** 전송 시각이 아니다.

`client_sequence`는 단말 내 발생 순번이다. 재전송해도 유지한다. `(session_id, client_sequence)`가 유일하므로 순서 검증에 쓴다.

## 3. 순서 검증

건너뛴 입력을 허용하고 서버가 중간 방문을 `skipped`로 채운다. 규칙은 `02` 7장에 있다.

| 입력 | 처리 |
|---|---|
| 다음 방문 | 정상 저장 |
| 몇 개 건너뜀 (`max_skip_stops` 이내) | 중간 방문 자동 `skipped` 생성 후 저장 |
| `max_skip_stops` 초과 | `SKIP_LIMIT_EXCEEDED` → 사용자 확인 후 `confirm_skip=true`로 재요청 |
| 이미 지난 방문 (실시간) | `EVENT_ORDER_CONFLICT` → 취소를 쓰도록 안내 |
| 이미 지난 방문 (대기 큐 지연) | 이력 보충 또는 `needs_review` |

**버스에서 정거장을 연달아 놓쳤을 때 버튼을 여러 번 누르게 하지 않는다.** 조작 부담이 크고 오입력이 는다.

자동 생성 구간이 있으면 화면에 "3·4번 정거장이 누락으로 기록됨"을 표시해 입력자가 인지하게 한다.

## 4. 오류 처리

| 코드 | 화면 동작 |
|---|---|
| `EVENT_ORDER_CONFLICT` | "이미 지난 정거장입니다. 잘못 입력했다면 취소를 사용해 주세요." + 취소 버튼. **자동 재시도하지 않는다** |
| `INPUT_VERSION_CONFLICT` | `loadCollectionSession`으로 최신 `input_version` 조회 → **`client_event_id`·`client_sequence` 유지, 새 `Idempotency-Key`**로 재전송 |
| `SKIP_LIMIT_EXCEEDED` | 건너뛴 방문 목록을 보여주고 확인받음 → **논리 관측 ID 유지, 새 키**로 `confirm_skip=true` 재요청 |
| `SESSION_OWNERSHIP_CONFLICT` | "다른 기기에서 수집 중입니다" + 관리자 확인 필요 안내. 자동 인계 없음 |
| `EVENT_ID_REUSED` | 클라이언트 버그. 큐 항목을 `needs_review`로 표시하고 사용자에게 알림 |
| 401 만료 | 재로그인 유도. **대기 큐는 유지한다** |
| 5xx / 네트워크 | '재전송 대기', 지수 백오프. **무한 자동 재시도하지 않는다** |

**어느 경우에도 큐 항목을 조용히 버리지 않는다.**

## 5. 오프라인 큐

버스 안은 통신이 불안정하다. 큐가 핵심 장치다.

| 규칙 | 내용 |
|---|---|
| 저장 위치 | 로컬 영속 저장소. 새로고침·재로그인 후에도 복구 |
| 제거 시점 | **성공 응답 또는 확정된 기존 관측 조회 후에만** |
| 재전송 시 유지 | `client_event_id`, `client_sequence`, `occurred_at` |
| 상태 구분 | 전송 대기 / 재전송 대기 / 인증 실패 / 검토 대기 / 확정 |

**인증 실패·일시 오류·검토 대기를 '저장 완료'와 다르게 표시한다.** 큐에 남아 있는데 저장된 것처럼 보이면 입력자가 다시 누르지 않는다.

### 지연 전송

큐에 오래 있던 항목이 뒤늦게 전송되면 서버가 `02` 6장의 지연 보충 규칙으로 처리한다. **큐를 거쳤다는 사실만으로 정상 관측으로 인정되지 않는다.** 결과에 따라 화면은 "지연 기록 반영됨" 또는 "기록 확인 필요"를 표시한다.

### 화면 재전송 절차 (2026-09-18 정리)

이 절은 01의 멱등 계약을 화면에 적용한다. 화면 구현은 아직 없으며 아래는 구현 기준이다.

1. 버튼을 누른 즉시 발생 시각·논리 기록 ID·순번·세션을 영속 저장한다. 로컬 저장 실패 시 전송 대기로 표시하지 않고 저장 실패를 안내한다.
2. 같은 세션은 발생 순번대로 한 요청씩 전송한다. 요청 키와 실제 전송 본문도 함께 저장해 새로고침 후 복원한다. 동시에 열린 탭이 중복 순번을 발급하거나 큐를 병렬 전송하지 않도록 쓰기 소유권을 제한한다.
3. 통신 끊김·응답 시간 초과는 결과 미확정이다. **동일 본문과 동일 요청 키**로 재전송한다. 응답을 못 받았다는 이유로 새 기록을 만들지 않는다.
4. 입력 버전 충돌은 세션을 다시 조회하여 기존 저장 여부와 현재 상태를 확인한다. 본문을 변경해야 하면 기록 ID·발생 시각·순번은 유지하고 새 요청 키를 발급한다. 누락 확인 후 confirm_skip=true로 변경할 때도 동일하다.
5. SKIP_LIMIT_EXCEEDED의 error.details.skipped_visits에서 방문 이름·순서를 표시한다. 사용자 확인 없이 건너뛰기를 승인하지 않는다.
6. 401은 자동 전송을 멈추고 재로그인을 안내한다. 같은 계정으로 재로그인 후 원래 세션의 큐를 복원한다. 다른 계정이나 새 세션으로 과거 큐를 자동 이전하지 않는다.
7. 네트워크 오류와 retryable=true 응답만 간격을 늘려 제한적으로 자동 재시도한다. 초기 화면 기본값은 최초 요청 이후 최대 5회, 대기 간격 1·2·4·8·16초로 한다. 소진 후에는 큐를 보존하고 수동 재시도를 제공한다. 새로고침·재연결만으로 소진 횟수를 초기화하지 않는다. 명시적 수동 재시도로 새 주기를 시작할 수 있다. 이 횟수는 클라이언트 운영 기본값이며 서버의 관측 유효성 기준을 바꾸지 않는다.
8. 403·404·422 및 순서·점유·ID 재사용 충돌은 자동 재전송하지 않는다. 해당 항목과 뒤의 항목을 보존하고 수정·확인 동작을 안내한다. 해결되지 않은 앞 기록을 넘어 뒤 기록을 자동 전송하지 않는다.
9. 서버 저장 성공 또는 동일 관측의 저장 사실이 확인된 뒤 전송 큐에서 제거한다. needs_review도 서버에는 저장된 결과이므로 ‘서버 저장 · 검토 대기’로 별도 표시하며 같은 기록을 계속 재전송하지 않는다. 저장된 기록의 validation_status가 cancelled이면 취소 상태를 그대로 표시한다.
10. 수집 종료를 누른 시각과 종료 요청도 보존한다. 새 입력을 중지하고 남은 관측을 전송한 뒤 종료 요청을 보낸다. 종료 요청의 응답이 유실되어도 동일 본문·키를 유지한다.

관측 외 변경(공지 생성·완료·취소 등)도 동일 요청 재전송 시 같은 키를 쓴다. 요청 접수증 보존 기간(7일)을 넘긴 결과 미확정 변경은 자동 재전송하지 않고 최신 상태·이력을 확인한다. 시계 확인은 일반 큐에 넣지 않으며 통신 실패 시 새로운 측정 교환을 시작한다.

## 6. 취소

직전 유효 입력을 취소한다. 원본은 삭제하지 않는다 (`02` 9장).

- 취소 요청에 `expected_input_version`을 보낸다.
- 연동된 자동 `skipped`가 함께 무효화된다.
- 취소 후 차량 상태와 예측이 재계산된다.
- 이미 취소된 기록의 재취소는 거절한다.

## 7. API

| 경로 | 요청 핵심 | 동작 |
|---|---|---|
| `POST /auth/login` | `username`, `password` | `access_token`, `expires_in`(86400) |
| `GET /collection-sessions/{session_id}` | 인증 | `input_version`, 수집 상태, 마지막 관측, 미해결 입력 |
| `POST /collection-sessions` | `trip_vehicle_id`, `shuttle_id`, 선택 `collection_start_trip_stop_id` | 세션 생성 또는 기존 열린 세션 반환. writer_instance_id 포함 |
| `POST /collection-sessions/{id}/events` | `trip_stop_id`, `event_type`, `occurred_at`, `client_event_id`, `client_sequence`, `expected_input_version`, `confirm_skip` | 관측 저장. writer_instance_id와 선택 clock_check_id 포함 |
| `POST /events/{event_id}/cancel` | `reason`, `expected_input_version` | 취소 |
| `POST /collection-sessions/{id}/end` | `ended_at`, `expected_input_version` | **수집 종료만** |

| `POST /collection-sessions/{id}/clock-checks` | `device_sent_at` | 시계 확인 1단계 (02 12장) |
| `POST /clock-checks/{id}/complete` | `device_received_at` | 시계 확인 2단계. 오차·불확실성 계산 |

모든 경로 앞에 `/api/v1`이 붙는다. 세션 시작·관측·취소·종료 요청에는 `Idempotency-Key`를 쓴다. 로그인과 시계 확인 두 요청은 요구하지 않는다 (현재 API 구현).

**writer_instance_id 주고받기 (구현 확정):** 새 세션은 서버가 `writer_instance_id`를 발급해 돌려준다. 앱은 로컬에 보관하고, 재시작·새로고침 때 `POST /collection-sessions`에 그 값을 실어 보내면 기존 세션을 받는다. 값이 없거나 다르면 같은 계정이어도 `SESSION_OWNERSHIP_CONFLICT`다. 관측 입력에는 항상 싣는다.

**계정:** 계정의 유일한 출처는 DB의 `staff_accounts`다. 환경변수·코드에 계정을 두지 않는다. `python -m app.accounts create --username … --role collector|admin`으로 만들고 비밀번호는 프롬프트로 받는다 — 저장소·시드에 넣지 않는다. 비밀번호는 운영(`APP_ENV=production`)에서 8자 이상이어야 하고, 개발에서는 4자 이상이면 경고와 함께 허용한다 (2026-09-18).

**최초 관리자 (2026-09-18):** DB가 비면 로그인해 계정을 만들 수 없으므로 `python -m app.accounts bootstrap`이 `ADMIN_BOOTSTRAP_ID`·`ADMIN_BOOTSTRAP_PASSWORD`로 관리자 1명만 만든다. **멱등이며 같은 아이디가 있으면 아무것도 하지 않는다** — 재기동마다 비밀번호가 환경변수 값으로 되돌아가면 그 파일을 가진 사람이 계정을 영구히 지배한다. 비밀번호가 비면 중단한다. 이 값은 파일에 평문으로 남으므로 계정을 만든 뒤 지운다. 두 번째 계정부터는 `create` 또는 관리자 화면으로 만든다. `staff_accounts.updated_at`이 마지막 변경 시각을 남긴다.

### 소속 검증

서버는 `session → trip_vehicle → trip → trip_stop`의 소속을 검증한다. **클라이언트가 보낸 ID 조합을 그대로 신뢰하지 않는다.**

`POST /collection-sessions`는 `trip_vehicle_id`와 `collection_start_trip_stop_id`가 같은 회차인지 확인한다.

### 종료된 세션에 늦게 도착한 기록

발생 시각이 수집 기간 안이면 이력에 반영하되 **현재 운행을 다시 열지 않는다.** 세션 상태는 `ended`를 유지한다.

## 8. 입력자 화면

| 화면 | 표시·동작 |
|---|---|
| 로그인 | 인증 만료 안내, 재로그인 후 대기 입력 보존 |
| 회차 선택 | 날짜·노선·회차·차량 슬롯. 중간 탑승 시 시작 방문 지정 |
| 수집 | 다음 방문 버튼을 **크게**, 현재 회차·직전 입력·전송 상태 함께 |
| 기록 확인 | 누락 표시, 취소, 수집 종료 |

### 수집 화면 구성

```
┌────────────────────────────────┐
│ 천안아산역 순1 · 1호차           │  현재 회차
│ 직전: 탕정역 통과 08:12 ✓       │  확정 표시
│                                │
│  ┌──────────────────────────┐  │
│  │   시티프라디움 통과       │  │  다음 방문. 크게
│  └──────────────────────────┘  │
│                                │
│  [도착] [출발] [통과]           │  이벤트 종류 선택
│                                │
│  전송 대기 1건                  │  큐 상태
│  [직전 입력 취소] [수집 종료]    │
└────────────────────────────────┘
```

- **버튼 기준은 실측 전에 확정한다.** "정거장 표지판과 나란해지는 순간"처럼 재현 가능한 기준이어야 한다.
- 같은 방문의 도착→출발 기록은 허용한다. 통과는 정차하지 않고 기준점을 지난 기록이다. 모순되는 arrived·passed 조합을 임의로 함께 확정하지 않고 02의 검증·검토 경로를 따른다.
- 수집 종료와 운행 완료를 별도 버튼·별도 문구로 구분한다.

### 프론트 상태

| 변수 | 의미 |
|---|---|
| `sessionId`, `inputVersion` | 세션과 입력 버전 |
| `collectionStatus` | 수집 상태 |
| `nextTripStopId` | 다음 방문 |
| `lastConfirmedEvent` | 직전 확정 관측 |
| `pendingInputEvents` | 전송 대기 큐 |
| `authExpiresAt` | 토큰 만료. 2시간 전부터 재로그인 안내 |

## 9. 함수

| 함수 | 입력 → 결과 | 핵심 규칙 |
|---|---|---|
| `loginCollector` | 사용자명·비밀번호 → 토큰 | 만료 24시간 |
| `loadCollectionSession` | sessionId → `input_version`·상태 | 충돌 후 재조회 |
| `startCollection` | 차량 슬롯·탑승 방문 → sessionId | 중복 시작 방지, 소유권 검사 |
| `submitObservation` | 방문·이벤트 종류 → 대기 입력·서버 결과 | 큐 우선 저장 |
| `restorePendingInputs` | 로컬 저장 → 대기 큐 | 앱 시작·재로그인 |
| `flushPendingInputs` | 대기 큐 → 멱등 재전송 | ID 유지 |
| `confirmSkippedVisits` | 서버 경고 → 확인 후 새 요청 | 새 키, 논리 ID 유지 |
| `cancelObservation` | eventId·사유·기대 버전 → 재계산 | 원본 보존 |
| `endCollection` | sessionId·시각·기대 버전 → 수집 종료 | 운행 완료와 구분 |
| `start_collection_session` | 슬롯·차량·방문 → 세션 | 충돌·중복 방지 |
| `validate_observation` | 이벤트·현재 상태 → 검증 결과 | `02` 6장 |
| `ingest_observation` | 검증 입력 → 저장·상태 확정 | 멱등, 회차 단위 잠금 |
| `resolve_existing_event` | 논리 관측 ID·불변 내용 → 기존 결과 | 재전송 판정 |

이름이 `snake_case`이면 서버, `camelCase`이면 화면 함수다 (`01` 8장). 별도 표기를 붙이지 않는다.

## 10. 검증 기준

| ID | 요구사항 | 확인 방법 |
|---|---|---|
| FR-MC-01 | 같은 입력자 반복 시작이 기존 세션 반환 | 두 번 호출 후 `session_id` 동일 |
| FR-MC-02 | 타 입력자 점유 시 자동 인계 안 됨 | `SESSION_OWNERSHIP_CONFLICT` |
| FR-MC-03 | 재로그인 후 대기 큐 보존 | 큐 항목 있는 상태에서 토큰 만료 → 재로그인 |
| FR-MC-04 | 새로고침 후 대기 큐 복구 | 로컬 저장 확인 |
| FR-MC-05 | 재전송 시 논리 ID 유지 | `INPUT_VERSION_CONFLICT` 후 재전송, 행 수 불변 |
| FR-MC-06 | `confirm_skip` 재요청도 논리 ID 유지 | 4개 건너뛴 뒤 확인 재요청 |
| FR-MC-07 | 실시간 역행이 409, 큐 지연은 보충 | 두 경로로 같은 과거 방문 입력 |
| FR-MC-08 | 큐 항목이 성공 전에 제거되지 않음 | 5xx 응답 후 큐 확인 |
| FR-MC-09 | 중간 탑승 전 방문이 `not_collected` | 3번 방문부터 수집 시작 |
| FR-MC-10 | 수집 종료가 운행 완료로 표시되지 않음 | 종료 후 `operation_status` 확인 |
| FR-MC-11 | 종료된 세션에 늦은 기록이 세션을 다시 열지 않음 | 종료 후 지연 전송 |
| FR-MC-12 | 취소가 연동 `skipped`를 무효화 | `parent_event_id` 연결 행 상태 |

## 11. 종료 요청과 대기 기록의 순서

종료 버튼을 누르면 단말은 새 입력을 중지하고 ended_at을 즉시 로컬에 보존한다. 기존 큐를 발생 순번으로 전송한 뒤 종료를 요청하는 것을 기본 순서로 한다. 통신 상황 때문에 종료 요청이 먼저 처리되어도 수집 기간 안에 발생한 기록을 이력 보충할 수 있다.

종료 후 기록이 전송되면 input_version을 재조회해 재검증하며 원래 client_event_id·client_sequence·occurred_at을 유지한다. 종료된 세션을 다시 열거나 새 세션에 과거 큐를 옮기지 않는다. 검토 대기로 서버에 저장된 기록은 ‘서버 저장·검토 대기’로 표시하여 공개 반영 확정과 구분한다.

관리자 관측 검토 API는 13이 소유한다. 시계·지연 설정이 미정이면 초기 실측 자료도 검토 대상으로 보관될 수 있으므로 실측 전에 해당 설정 또는 검토 화면을 준비한다.

| ID | 사례 | 기대 결과 |
|---|---|---|
| FR-MC-13 | 종료 요청 뒤 수집 기간 안 기록 도착 | 이력 보충·검토 가능, 세션 ended 유지 |
| FR-MC-14 | 종료 후 명시적 재수집 | 새 세션 ID, 과거 큐는 이전 세션으로 전송 |
| FR-MC-15 | 수동·GPS 동시 수집 | 생산자별 세션·순번 분리, 공개 대표는 02 정책 |
| FR-MC-16 | 동일 계정 두 기기에서 같은 열린 세션 시작 | writer_instance_id 충돌 거절 |
