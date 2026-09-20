# 변경 기록

큰 변화만 적는다 — 설계 문서(md) 내용, 실제 기능 처리, 데이터 활용이 바뀐 것. 같은 항목을 다시 바꾸면 이전 기록을 지우고 최신으로 대체한다. 3일이 지난 기록은 각 문서 본문에 이미 반영되어 있으므로 정리한다 (2026-09-18 규칙).

# 2026-09-18

## 서버 — 새 기능·계약 변경

| 무엇 | 어떻게 | 영향 |
|---|---|---|
| **정거장 단독 조회 API** | `GET /api/v1/stops/{stop_id}/upcoming?route_id&service_date`. 방향은 합쳐서 가까운 2개 + 행마다 `next_stop_name`·`terminal_stop_name`. 대표 시각은 같은 출처 안에서 **도착 → 출발** (후보 검색의 출발 우선과 반대). `upcoming(≤2)`·`attention`·`reference_timetable`·`empty_reason` 네 갈래 | `11` 11장 신설, FR-BC-23~28. `app/candidates/upcoming.py`, `app/api/stop_upcoming.py`. 화면의 정거장 카드가 이것만 쓴다 |
| **visits[] 실측 시각** | `observed_arrival_at`·`observed_departure_at`·`observed_passed_at` 추가. 이 방문·이 차량의 유효 관측만, 예측 아님 | `03` 5장, FR-ST-14. **기존 상태 스냅샷과 내용이 달라져 배포 후 첫 조회에서 회차마다 `state_version`이 한 번 오른다** |
| **로그인 시도 제한** | 연속 5회 실패 시 15분 잠금 `LOGIN_LOCKED`(429, retryable=true). 잠긴 동안은 맞는 비밀번호도 거절. 없는 아이디는 잠그지 않고 401만 | `01` 5장·오류 코드·설정 인덱스(`login_max_failures`·`login_lockout_seconds`), `14` 4장. 마이그레이션 **0007** (`staff_accounts.failed_login_count`·`locked_until`) |
| **토큰 즉시 차단** | `staff_accounts.token_not_before`(0007). 비밀번호 재설정(`accounts create`)과 새 CLI `accounts revoke-tokens`가 갱신하고, 그 이전에 발급된 토큰은 만료 전이라도 401 | IMPROVEMENTS 한계 1·2 해결. 화면은 이 401에도 대기 큐를 유지한다 |
| **경로 자료 파이프라인** (`PLAN-route-data.md`) | ① `samples/stops-provisional.json` 임시 좌표 7개(`needs_interpretation`, verified 덮지 않음) · ② `python -m app.survey` — GPX 적재(해시 멱등)·이상치·Douglas-Peucker 단순화·정거장 구간 분할(첫 트랙은 `unverified`)·두 번째 트랙 `verify`·시험용 `gpx-demo` · ③ `GET /routes/{id}/path` + `web/` 폴리라인 (verified 실선, 그 외 점선 "미검증 경로", 행 없으면 선 없음) | `10` 5장 표시 규칙, IMPROVEMENTS 등록 절차에 명령. **가짜 자료로 verified를 만들지 않는다.** P6 수신은 Traccar Client(OsmAnd 형식)로 다음 작업 |
| **작업 지침 `CLAUDE.md`** | 문서 우선·멈춰서 허락받는 것·변경 기록 규칙·검증·자료 원칙·코드 관례. 채팅 설명은 문서로 옮긴다 | 저장소 루트 |
| 중복·불일치 정리 (2차 검토) | `_local` 5중 정의 → `timeutil.to_seoul` · `admin.stop_out` → `admin_stop_out` (build.stop_out과 이름 충돌) · `arrived_freshness_seconds`·`refresh_after_seconds` 모듈 상수 → `Settings` (14가 ConfigMap이라 함) · `01` 설정 인덱스에 코드에만 있던 5개 등재 · `CACHE_REBUILDING` 미구현 표시 · PLAN의 `/device-positions` → 07의 `/device/positions` · `app.survey --version` | 기계 대조 결과: 오류 코드 코드↔문서 불일치 0, API 경로 불일치 0 (P6 `/device/positions`만 문서 선행) |
| 회차 보충 루프 | API 프로세스가 하루 한 번 오늘부터 14일치 회차를 보충 (`realtime/server.py`). K8s CronJob 전까지의 대체 | IMPROVEMENTS 한계 4 완화 — 학생 첫 조회가 회차를 생성하는 쓰기가 되지 않는다 |
| CORS | `CORS_ORIGINS`(쉼표 구분)로 REST·Socket.IO 함께 허용. `SOCKET_CORS_ORIGINS`로 따로 지정 가능. `*` 금지 | must_do S2, `.env.example` |
| 개발용 임시 계정 | `admin/admin`·`user/1234`. 개발 DB에만. `APP_ENV=production`은 8자 미만 거부 | **공개 전 재설정** (must_do S3) |
| 정거장 좌표 등록 | `GET/POST /admin/stops`, CLI `app.stops set`. 재시드가 등록 좌표를 지우지 않는다 | 현재 0/22 등록 |
| 멱등 기록 정리 | 보존 7일. `app.jobs purge-records`와 서버 내부 1시간 주기 | `01` 설정 인덱스 |

## 화면 — web/ 골격 착수

Next.js 15 · TypeScript, `web/`. 첫 화면만: 노선·날짜 선택, 카카오맵(**정거장 점만 — 경로선·직선 연결 없음**), 정거장 목록(좌표 없으면 '좌표 확인 필요'), 정거장 카드(위 조회 API). 시각 표시는 `md_frontend/02` 규칙 — 1시간 미만 'n분 뒤', 이상 HH:mm, 1분 미만 '1분 이내', 분 내림은 임시. Compose에 `web` 서비스(빌드 인자로 `NEXT_PUBLIC_*`). 남은 화면은 `md_frontend/must_do.md`.

화면 방향 합의: Transit 앱·PC 조합, Citymapper 제외. 기본 지도, 모바일 하단 카드·PC 옆 패널, 왼쪽 위 햄버거, 검색·시간표, 메뉴 맨 아래 프로필. 피그마는 필수 아님. 최초 노선 천안아산역.

## 문서 정합

00 헤더 v7.10 · ROADMAP P2 "직선 연결" 문구를 must_do F8(직선도 없음)에 맞춤 · IMPROVEMENTS 한계 1·2·4·7 해결 표시 · `md_frontend/04-review` 5행 해결 · must_do S1·S2·S4·F1·F8 갱신 · `.env.example`에 `SOCKET_CORS_ORIGINS`·web 항목 · 01 §6 상태값 인덱스에 `end_reason`·`decision`·`action`·`reason` 등재.

## 검증 상태

작성 세션은 DB·venv에 접근하지 못해 문서 기계 검사(링크 0 깨짐, FR 270개 중복·공백 없음)만 했다.
**2026-09-20에 서버 검증을 마쳤다.**

| 항목 | 결과 |
|---|---|
| `alembic upgrade head` | 0007까지 적용됨 |
| `pytest` | **205개 통과** (기존 185 + 신규 20: `test_stop_upcoming`·`test_auth_hardening`·`test_survey`) |
| `web` 타입 검사 | **아직 못 했다** — `npm install` 필요. 화면은 외부 담당이라 대기 |

```powershell
cd api; $env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m pytest
cd ..\web; npm install; npm run typecheck        # package-lock.json 생기면 함께 커밋
```

# v7.10 변경 기록 (2026-09-15)

사용자 결정 3건을 반영했다. 구현(P0·P1) 중 드러난 문서 보완도 함께 적는다.

## 사용자 결정

| 결정 | 반영 |
|---|---|
| **MVP 노선 = 천안아산역 노선** | `00` 3장, `10` 1장, `md_frontend/03` 남은 선택 |
| **주요 외부 정거장은 승차 가능** — 시각이 공시된 천안아산역·천안역·천안터미널·주은아파트·온양온천역·아산터미널 | `04` 1장. 중간 방문은 승차·하차 모두 `allowed`. 휴일 천안역의 천안아산역 두 방문 포함. 그 밖의 경유지는 `unknown` 유지 |
| **선문대 = 아산캠퍼스** | `04` 4·5·9·11·13장, `00`·`10`·IMPROVEMENTS 미확정 항목에서 제거. 휴일 잠정 패턴을 천안터미널 일반 패턴으로 합침 |

하차 허용은 사용자가 '승차 가능'이라고만 답한 것을 확장한 해석이다. 외부역이 하교 방향의 목적지이기도 하므로 함께 열었다. 다르면 `04` 1장과 시드의 `MAJOR_EXTERNAL_STOPS` 규칙을 고친다.

## 구현 중 보완

| 문서 | 내용 |
|---|---|
| `15` | 참조 방향 규칙의 예외 ⓪→① 명시 (조사 자료가 대상 노선 버전·방문을 가리킴). `schedule_annotations` 소유 등재 |
| `04` | 원문 칸 보존 위치 `trip_templates.source_cells` |
| `05` | 예외 범위 열을 `route_id`(null=전체)로 확정 |
| `01` | `VALIDATION_ERROR`(422) 등재 |
| ROADMAP | 참조 장 번호 3곳 정정 |
| `03` | 이벤트 없는 방문의 `upcoming`/`unknown` 기준 시각 규칙. P4 전 `state_version` 만료 미반영 한계 명시 |
| `11` | `unverified_reasons` 값 표, `is_same_stop_loop`, 회차 목록 모드 필드 |

## P3 1부 구현으로 정한 것

| 문서 | 내용 |
|---|---|
| `01` | 오류 코드 `AUTH_REQUIRED`·`FORBIDDEN`·`EVENT_ALREADY_CANCELLED`, 결정 값 `cancel`, 멱등 키 저장 규칙 |
| `02` | 시계 확인 NTP 네 시각 방식, `review_reason` 값 표, `superseded_by_observation` |
| `06` | `writer_instance_id` 발급·재전송 규칙, 시계 확인 경로, 계정 CLI |
| `15` | `staff_accounts`(①)·`idempotency_records`(⑤) 등재, `departure_observation_event_id` FK 미설정 이유 |

**설정 시험값 (2026-09-15 사용자 승인):** `clock_skew_tolerance_seconds` 5초·`clock_check_valid_seconds` 6시간·`pending_input_retention_hours` 24시간·`realtime_input_window_seconds` 120초. 시계 확인을 거친 실시간 입력은 바로 `valid`로 공개 상태에 반영된다. 값을 비우면 이전처럼 전부 `needs_review`로 보관된다 (`01` 7장, `02` 12장).

## P3 2부 구현으로 정한 것

| 문서 | 내용 |
|---|---|
| `01` | 오류 코드 `OPERATION_STATE_CONFLICT`, `decision_type`·`evidence_type` 값 |
| `13` | `decision_type` 값, 완료 재검토 필요 여부 파생 규칙, '운영 구현 메모' 절 (자동 완료와 `control_version`, 취소 시 완료 슬롯, 승인 재확인 항목, 공지 조회 범위, 관리자 취소) |
| `15` | `operation_decisions.decided_by = null` 의미 |

**구현 범위:** 마이그레이션 0004(`notices`·`operation_decisions`), 차량 완료·종점 실측 자동 완료, 회차 취소(사유가 회차 상태에 표시), 관측 승인·기각, 오취소 복구, 완료 재검토, 공지 생성·조기 만료·학생 조회, 관리자 수집 기록 목록·전체 이력, 검토 대상 판정 배치. FR-OP-01~26 중 화면 문구(03)는 UI 단계, 전송 수신(10)은 P4, GPS 세션(21)은 P6, 통계 차단(25)은 P5에서 확인한다.

## P4 구현으로 정한 것

| 문서 | 내용 |
|---|---|
| `12` | '구현 메모' 절 — 단일 백엔드 구성, 회차당 최신 스냅샷 1행, `commit_trip_state`, 시간 경과 확정 주기, 후보 서명, 회차 추가·날짜 변경 이벤트 구분, 전송 재시도, 캐시 규칙, 구독 응답, 서버 시각 단일 출처 |
| `03` | P2 한계(시간 경과 시 버전 미증가) 해소 |
| `15` | `outbox_events` 이름, 스냅샷 회차당 1행 |

**구현 범위:** 마이그레이션 0005, Compose에 redis 추가, `uvicorn app.main:asgi`. 화면 쪽 동기화 절차(FR-RT-01·02·05·06·13·19·20)는 `md_frontend/must_do.md` F6에서 확인한다.

## 프론트엔드 연동 준비 (2026-09-18)

화면은 별도 담당자가 만든다. 이 저장소에는 화면 코드를 두지 않고 서버 쪽 조건만 갖췄다.

| 항목 | 내용 |
|---|---|
| 환경 파일 | `.gitignore`에 `.env.local`·`.env.*.local` 등 추가. `.env.example`은 값 없이 주석만 두고 자리표시 비밀값을 제거 |
| CORS | `CORS_ORIGINS`(쉼표 구분) 신설 — REST 미들웨어와 Socket.IO에 함께 적용. 비우면 같은 출처만. `*` 미사용. Docker가 루트 `.env` 값을 넘긴다 |
| 계정 | `staff_accounts.updated_at` 추가(마이그레이션 0006). `python -m app.accounts bootstrap` — `ADMIN_BOOTSTRAP_ID`·`ADMIN_BOOTSTRAP_PASSWORD`로 최초 관리자 1명, 멱등, 기존 비밀번호를 되돌리지 않음 |
| 정거장 좌표 | `GET /admin/stops`, `POST /admin/stops/{id}/location`, `python -m app.stops`. 남한 좌표 범위 검사, `verification_status` 기록 |
| 시드 결함 수정 | 원문 재적재가 `stops`를 전체 덮어써 등록한 좌표·확인 상태를 null로 되돌리던 문제. 이제 이름만 갱신한다 |

**받아들이지 않은 지시와 이유:** 새 `users` 테이블(이미 `staff_accounts`가 있고 FK 5곳이 참조 — 이름만 바뀌고 얻는 기능 없음), bcrypt·argon2 교체(현재 scrypt는 표준 메모리 강화 KDF이며 단순 해시가 아니다), 부트스트랩 비밀번호의 상시 파일 보관(평문 잔존 — 기본은 CLI 프롬프트, 부트스트랩은 무인 기동 전용·일회용).

## 운영 결정 (2026-09-18)

| 결정 | 반영 |
|---|---|
| **요청 접수증(`idempotency_records`) 보존 7일** — 재전송 대비용이라 오래 둘 이유가 없다. 관측 기록은 예측 재료라 지우지 않는다 | `01` 7장 설정값 표, `app/idempotency.purge_expired`, `python -m app.jobs purge-records`(서버 내부 1시간 주기) |
| **개발용 임시 계정** `admin/admin`·`user/1234` — 화면 없이 API를 눌러 보기 위함. 비밀번호는 개발 DB에만 있다 | README, `06` 7장. `APP_ENV=production`에서는 8자 미만 비밀번호로 계정을 만들 수 없다 |
| 남은 작업 최신화 | ROADMAP '남은 작업', README 진행 상황 |

## 구현 중 드러난 모순 — 해소

`04` 11장이 외부 정거장 열 시각을 `unspecified`로 두어, `11` FR-BC-19 규칙상 **캠퍼스 기점 회차의 천안아산역 승차가 전부 확인 필요·`sort_at = null`**이 되고 FR-BC-01(온양 순2 08:45 → 순3 08:50)도 성립하지 않았다. 사용자가 **외부 정거장 열 = 도착 시각(기점이면 출발)**으로 확인해 `04` 5장 '열의 의미'를 추가하고 11장 미확정 행을 지웠다. FR-BC-01이 설계대로 통과한다.

---


---

v7.9 이전 기록(v7.5~v7.9)은 2026-09-18에 정리했다. 그 변경은 모두 각 문서 본문에 반영되어 있고, 근거는 [RATIONALE-v7.6](RATIONALE-v7.6.md)에 남아 있다.
