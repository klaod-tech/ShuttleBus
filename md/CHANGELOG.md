# 변경 기록

큰 변화만 적는다 — 설계 문서(md) 내용, 실제 기능 처리, 데이터 활용이 바뀐 것. 같은 항목을 다시 바꾸면 이전 기록을 지우고 최신으로 대체한다.

**최근 작업 3회분만 이 파일에 둔다** (날짜 간격이 아니라 작업 횟수. 2026-09-22 확정). 그보다 오래된 기록은 핵심 한 줄만 남기고 [보관 기록](CHANGELOG-ARCHIVE.md)으로 옮긴다.

## 2026-09-22

연구 참고: [논문 기록](논문.md)에 논문 5편, 정상 GPS 중심·장애 보완 연구 방향, 핵심 질문 3가지의 답과 미확인 항목을 정리했다. IMPROVEMENTS의 중복 설명은 링크로 대체했다. 공개 자료를 확인했으며 전체 본문 검토·실험 재현·코드 시험은 수행하지 않았다. 설계 계약·구현 단계 변경은 없다.

추가 검토: [최근 변경 재검토](REVIEW-2026-09-22.md)에 데모 CLI의 저장 우회와 시각 없는 기록의 자기검증 공백을 기록했다. 메모리 재현 2건과 화면 타입 검사를 실행했다. 기능 수정·DB 변경·전체 서버 시험 재실행은 하지 않았다.

변경 기록 점검에서 찾은 오류를 고쳤다. 새 기능·API·스키마 변경은 없다.

| 무엇 | 어떻게 |
|---|---|
| **데모 자료가 `verified`가 되던 것** | `survey.verify_path`가 데모 트랙(`gpx-demo`가 creator·note에 박는 표시)과 **경로를 만든 그 기록**을 거절한다. 시험은 `allow_demo=True`·CLI는 `--allow-demo`로만 데모를 쓴다. 출처 트랙 ID 열이 없어 자기검증은 경로 점 시각 90% 겹침으로 판정한다 — 열 추가는 스키마 승인 사항 (REVIEW-2026-09-21 P1) |
| 기록 보존 규칙 | "3일이 지난 기록" → **최근 작업 3회분**. 날짜 간격이 아니라 횟수다. 밀려난 기록은 핵심 한 줄만 남기고 [보관 기록](CHANGELOG-ARCHIVE.md)으로 옮긴다 |
| 지침 파일 두 벌 | `AGENTS.md`와 `CLAUDE.md`가 59줄 동일본이었다. 내용은 `CLAUDE.md`에만 두고 `AGENTS.md`는 가리키기만 한다 |
| 미등재 오류 코드 | `HTTP_ERROR`(errors.py의 마지막 봉투)를 `01` 오류 코드 인덱스에 넣었다. 09-18 기록의 "오류 코드 불일치 0"은 사실이 아니었다 |
| **경로 전체가 `verified`로 표시되던 것** | `GET /routes/{id}/path`가 구간 수를 그 경로 버전의 정거장 수−1과 비교한다. 좌표 없는 정거장 때문에 구간이 빠져 있으면 `partial`이다 (REVIEW-2026-09-21 P1) |
| 모듈 상수 → 설정 | GPX 적재 시험값 5개를 `Settings`로 옮기고 `01` 설정 인덱스에 등재 (REVIEW P2) |
| 화면 의존성 고정 | `web/package-lock.json` 생성(설치 재현·취약점 검사 가능). `npm audit`이 postcss 경유 2건(high 1·moderate 1)을 보고하며 해결에는 Next 16 상향이 필요하다 — 화면 담당자 판단 사항으로 남긴다 |
| 기록 정리 | 9/18 작업이 9/15 섹션에 섞여 있던 블록 2개를 합치고 중복 행 제거, 빈 섹션 삭제, 제목 단계 통일, 낡은 검증표 대체 |

### 같은 날 2차 — 재검토 지적 반영 ([REVIEW-2026-09-22](REVIEW-2026-09-22.md))

1차 수정이 "데모로는 verified를 만들 수 없다"고 적었지만 우회로가 남아 있었다.

| 무엇 | 어떻게 |
|---|---|
| CLI 우회 옵션 | `--allow-demo`를 없앴다. 그 옵션은 데모 차단을 풀고 결과를 **실제 DB에 커밋**했다. `allow_demo`는 시험 함수 전용 인자로만 남는다 |
| 출처 확인 불가 | 측정 시각이 없어 같은 기록인지 확인할 수 없으면 **거절**한다. 이전 구현은 확인 불가를 '다른 기록'으로 통과시켰다 |
| 판정 상수 | `SAME_RECORDING_OVERLAP` → `survey_same_recording_overlap` 설정과 `01` 인덱스. 겹침률만으로 독립 기록을 보장하지 못한다는 한계도 함께 적었다 |
| 문서 | 9/15 본문을 [보관 기록](CHANGELOG-ARCHIVE.md)으로 옮겨 최근 3회분 규칙을 실제로 지켰다. `PLAN-route-data` 상태 최신화, `REVIEW-2026-09-21`의 다음 순서 갱신, `00` 문서 지도에 '계약이 아닌 기록'(계획·논문·점검·근거) 등재 |
| 문헌 기록 | [논문.md](논문.md) — 교수님 조언(칼만필터·신호 교차로·IMU)에 대한 논문 5편 검토. 인용 5건의 저자·학술지·권·쪽·DOI를 재확인했고 모두 실재한다. 새 계약은 만들지 않았다 |

검증: 서버 시험 **211개 통과**(회귀 시험 4개 추가 — 데모 거절, 자기검증 거절, 출처 확인 불가 거절, CLI 우회 부재, 경로 구간 커버리지). `npm run typecheck` 통과. 화면 코드·스키마·API 계약은 건드리지 않았다.

### 같은 날 3차 — 출처 트랙 기록 (사용자 승인)

| 무엇 | 어떻게 |
|---|---|
| **마이그레이션 0008 `survey_path_builds`** | 정제 경로가 어느 조사 기록에서 나왔는지 ⓪ 조사 층에 남긴다. `route_path_points`에 열을 두면 ①→⓪ 참조로 FR-DM-01을 어기므로 조사 층에 두고 ⓪→① 예외를 쓴다 (`15` 1장) |
| 검증 판정 | `verify`가 시각 겹침 추정이 아니라 **출처 트랙 ID**로 자기검증을 막는다. 출처 기록이 없으면 거절, **데모 기록으로 만든 경로**는 실제 트랙으로도 거절. 시각 겹침은 같은 녹화를 두 번 적재한 경우를 잡는 보조 검사로 남는다 |
| 검증 이력 | 어느 트랙이 검증했는지·언제·최대 편차를 같은 행에 기록한다 |

검증: 서버 시험 **213개 통과**(출처 기록·ID 기반 자기검증 거절·데모 경로 거절 3개 추가). FR-DM-01 층 참조 검사 통과, 마이그레이션 up/down 왕복 통과.

남은 것: 화면 2건(미검증 마커 구분, 경로 요청 취소 처리)과 의존성 취약점 2건은 외부 화면 담당 몫이다 — 취약점은 `next`가 쓰는 `postcss` 문제로 API와 무관하다.

## 2026-09-21 (작업 1회 전)

- 사전 검토 결과·실제 로컬 DB 건수·카카오맵 브라우저 확인·남은 결함은 [검토 문서](REVIEW-2026-09-21.md)에 기록했다.
- `api/app/config.py`: 실행 폴더에 따라 루트 `.env`의 CORS 설정이 누락되던 문제 수정. 루트 → API 환경 파일 → 프로세스 환경변수 순서로 우선한다.
- 검증 상태: 서버 시험 **207개 통과**(설정 우선순위 시험 2개 포함), 화면 타입 검사 통과. Docker·프로덕션 빌드·실제 위치 정확도는 검증하지 않았다.

## 2026-09-18 (작업 2회 전)

### 서버 — 새 기능·계약 변경

| 무엇 | 어떻게 | 영향 |
|---|---|---|
| **정거장 단독 조회 API** | `GET /api/v1/stops/{stop_id}/upcoming?route_id&service_date`. 방향은 합쳐서 가까운 2개 + 행마다 `next_stop_name`·`terminal_stop_name`. 대표 시각은 같은 출처 안에서 **도착 → 출발** (후보 검색의 출발 우선과 반대). `upcoming(≤2)`·`attention`·`reference_timetable`·`empty_reason` 네 갈래 | `11` 11장 신설, FR-BC-23~28. `app/candidates/upcoming.py`, `app/api/stop_upcoming.py`. 화면의 정거장 카드가 이것만 쓴다 |
| **visits[] 실측 시각** | `observed_arrival_at`·`observed_departure_at`·`observed_passed_at` 추가. 이 방문·이 차량의 유효 관측만, 예측 아님 | `03` 5장, FR-ST-14. **기존 상태 스냅샷과 내용이 달라져 배포 후 첫 조회에서 회차마다 `state_version`이 한 번 오른다** |
| **로그인 시도 제한** | 연속 5회 실패 시 15분 잠금 `LOGIN_LOCKED`(429, retryable=true). 잠긴 동안은 맞는 비밀번호도 거절. 없는 아이디는 잠그지 않고 401만 | `01` 5장·오류 코드·설정 인덱스(`login_max_failures`·`login_lockout_seconds`), `14` 4장. 마이그레이션 **0007** (`staff_accounts.failed_login_count`·`locked_until`) |
| **토큰 즉시 차단** | `staff_accounts.token_not_before`(0007). 비밀번호 재설정(`accounts create`)과 새 CLI `accounts revoke-tokens`가 갱신하고, 그 이전에 발급된 토큰은 만료 전이라도 401 | IMPROVEMENTS 한계 1·2 해결. 화면은 이 401에도 대기 큐를 유지한다 |
| **경로 자료 파이프라인** (`PLAN-route-data.md`) | ① `samples/stops-provisional.json` 임시 좌표 7개(`needs_interpretation`, verified 덮지 않음) · ② `python -m app.survey` — GPX 적재(해시 멱등)·이상치·Douglas-Peucker 단순화·정거장 구간 분할(첫 트랙은 `unverified`)·두 번째 트랙 `verify`·시험용 `gpx-demo` · ③ `GET /routes/{id}/path` + `web/` 폴리라인 (verified 실선, 그 외 점선 "미검증 경로", 행 없으면 선 없음) | `10` 5장 표시 규칙, IMPROVEMENTS 등록 절차에 명령. 가짜 자료로 verified를 만들지 않는다는 원칙은 2026-09-22에 코드로 막았다(아래 항목). P6 수신은 Traccar Client(OsmAnd 형식)로 다음 작업 |
| **작업 지침 `CLAUDE.md`** | 문서 우선·멈춰서 허락받는 것·변경 기록 규칙·검증·자료 원칙·코드 관례. 채팅 설명은 문서로 옮긴다 | 저장소 루트 |
| 중복·불일치 정리 (2차 검토) | `_local` 5중 정의 → `timeutil.to_seoul` · `admin.stop_out` → `admin_stop_out` (build.stop_out과 이름 충돌) · `arrived_freshness_seconds`·`refresh_after_seconds` 모듈 상수 → `Settings` (14가 ConfigMap이라 함) · `01` 설정 인덱스에 코드에만 있던 5개 등재 · `CACHE_REBUILDING` 미구현 표시 · PLAN의 `/device-positions` → 07의 `/device/positions` · `app.survey --version` | API 경로 불일치 0 (P6 `/device/positions`만 문서 선행). **오류 코드는 0이 아니었다** — `HTTP_ERROR`가 미등재였고 2026-09-22에 `01`에 넣었다 |
| 회차 보충 루프 | API 프로세스가 하루 한 번 오늘부터 14일치 회차를 보충 (`realtime/server.py`). K8s CronJob 전까지의 대체 | IMPROVEMENTS 한계 4 완화 — 학생 첫 조회가 회차를 생성하는 쓰기가 되지 않는다 |
| CORS | `CORS_ORIGINS`(쉼표 구분)로 REST·Socket.IO 함께 허용. `SOCKET_CORS_ORIGINS`로 따로 지정 가능. `*` 금지 | must_do S2, `.env.example` |
| 개발용 임시 계정 | `admin/admin`·`user/1234`. 개발 DB에만. `APP_ENV=production`은 8자 미만 거부 | **공개 전 재설정** (must_do S3) |
| 정거장 좌표 등록 | `GET/POST /admin/stops`, CLI `app.stops set`. 재시드가 등록 좌표를 지우지 않는다 | 현재 0/22 등록 |
| 멱등 기록 정리 | 보존 7일. `app.jobs purge-records`와 서버 내부 1시간 주기 | `01` 설정 인덱스 |
| 환경 파일 정리 | `.gitignore`에 `.env.local` 계열 추가. `.env.example`은 값 없이 주석만 — 자리표시 비밀값 제거 | FR-IN-08 |
| 계정 관리 | `staff_accounts.updated_at`(마이그레이션 0006)과 `app.accounts bootstrap` — 최초 관리자 1명, 멱등, 기존 비밀번호를 되돌리지 않는다 | `06` 7장 |
| 시드 결함 수정 | 원문 재적재가 `stops`를 전체 덮어써 등록한 좌표·확인 상태를 null로 되돌리던 문제. 이제 이름만 갱신한다 | `04` 11장 |

**받아들이지 않은 지시와 이유:** 새 `users` 테이블(이미 `staff_accounts`가 있고 FK 5곳이 참조 — 이름만 바뀌고 얻는 기능 없음), bcrypt·argon2 교체(현재 scrypt는 표준 메모리 강화 KDF이며 단순 해시가 아니다), 부트스트랩 비밀번호의 상시 파일 보관(평문 잔존 — 기본은 CLI 프롬프트, 부트스트랩은 무인 기동 전용·일회용).

### 화면 — web/ 골격 착수

Next.js 15 · TypeScript, `web/`. 첫 화면만: 노선·날짜 선택, 카카오맵(**정거장 점만 — 경로선·직선 연결 없음**), 정거장 목록(좌표 없으면 '좌표 확인 필요'), 정거장 카드(위 조회 API). 시각 표시는 `md_frontend/02` 규칙 — 1시간 미만 'n분 뒤', 이상 HH:mm, 1분 미만 '1분 이내', 분 내림은 임시. Compose에 `web` 서비스(빌드 인자로 `NEXT_PUBLIC_*`). 남은 화면은 `md_frontend/must_do.md`.

화면 방향 합의: Transit 앱·PC 조합, Citymapper 제외. 기본 지도, 모바일 하단 카드·PC 옆 패널, 왼쪽 위 햄버거, 검색·시간표, 메뉴 맨 아래 프로필. 피그마는 필수 아님. 최초 노선 천안아산역.

### 문서 정합

00 헤더 v7.10 · ROADMAP P2 "직선 연결" 문구를 must_do F8(직선도 없음)에 맞춤 · IMPROVEMENTS 한계 1·2·4·7 해결 표시 · `md_frontend/04-review` 5행 해결 · must_do S1·S2·S4·F1·F8 갱신 · `.env.example`에 `SOCKET_CORS_ORIGINS`·web 항목 · 01 §6 상태값 인덱스에 `end_reason`·`decision`·`action`·`reason` 등재.

### 검증 상태

작성 세션은 DB·venv에 접근하지 못해 문서 기계 검사만 했고, 2026-09-20에 서버 시험(당시 205개)을 확인했다.
최신 결과는 맨 위 2026-09-21 항목에 있다 — 중복을 남기지 않는다.

---

이보다 오래된 기록은 [보관 기록](CHANGELOG-ARCHIVE.md)에 있다.
