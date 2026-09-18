# ShuttleBus

학교 셔틀 도착 예측 서비스. 설계는 [md/](md/00-overview.md), 구현 순서는 [ROADMAP](md/ROADMAP.md), 화면 구상은 [md_frontend/](md_frontend/README.md).

## 진행 상황

| 단계 | 상태 | 확인 |
|---|---|---|
| P0 골격 | 스키마 ⓪①② 층, 오류 봉투, Compose 구성 | FR-DM-01, 마이그레이션 up/down 왕복 |
| P1 기준 자료 | 시간표 148행 적재, `X` 판별, 운행 달력, 회차·슬롯 생성, 날짜별 정거장 API | FR-RD-01~13·23, FR-SC-01~15 |
| P2 백엔드 | 회차 상태(`/scheduled-trips/{id}/state`), 출발·도착 탑승 후보, 회차 목록 모드. 시간표만 있는 단계의 예측 판정 | FR-ST 적용분, FR-BC-01~22 |
| P2 화면 | 미착수 — `md_frontend` 방침에 따라 도안·정거장별 조회 계약 확정 후 | — |
| P3 서버 (1부) | 로그인·계정, 수집 세션, 관측 입력(02 유효성·자동 누락·지연 보충), 취소, 수집 종료, 시계 확인, 멱등 키. 관측이 회차 상태·후보에 반영 | FR-MC-01·02·05·06·09~13·16, FR-OB-01~03·05·06·08~11 |
| P3 서버 (2부) | 차량 완료(종점 실측 자동 완료 포함), 회차 취소, 관측 승인·기각, 오취소 복구, 완료 재검토, 공지, 관리자 수집 기록 조회, 검토 대상 판정 배치 | FR-OP-01·02·04~09·11~20·22~24·26 (03은 화면, 10은 상태 버전까지, 21은 P6 GPS, 25는 P5) |
| P4 실시간 | 상태 확정 스냅샷·outbox·Socket.IO(`/socket.io`)·Redis 캐시 복원, 시간 경과 상태 확정 작업. Docker에서 전달 0.2~0.3초, Redis 초기화 후 복원 확인 | FR-RT-03·04·07·08·09·11·12·14~18 (01·02·05·06·13·19·20은 화면) |
| P5 통계·예측 | 대기 — 실제 탑승 표본이 필요 (시간대 밴드 각 5회 이상) | — |
| P6 GPS 자동화 | 대기 — 단말 설치 허가와 경로(GPX) 자료가 필요 | — |
| 화면 (P2 화면·P7) | 미착수 — [md_frontend/must_do.md](md_frontend/must_do.md)가 할 일 목록을 갖는다 | — |

남은 작업 전체는 [ROADMAP 남은 작업](md/ROADMAP.md)에 있다. 미뤄 둔 현장 확인·측정 작업은 [개선사항 — 사용자 확인 대기](md/IMPROVEMENTS.md)에 모아 두었다. 그 자료 없이도 개발은 계속되며, 채워지면 '확인 필요' 표시가 정상 정보로 바뀐다.

층 순서대로 마이그레이션을 추가한다 — ⓪①(0001), ②(0002), ③과 계정·멱등(0003), ⑤ 공지·운영 결정(0004), ⑤ 스냅샷·outbox(0005). **④ 계산 층은 P5에서 추가한다.**

## 로컬 실행 — Docker 없이

```powershell
setup.cmd                                                          # 도구·패키지 설치
powershell -ExecutionPolicy Bypass -File scripts\dev-db.ps1 start  # PostgreSQL(55432) 기동·마이그레이션·시드

cd api
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m pytest                               # 시험
.\.venv\Scripts\python.exe -m app.jobs ensure-trips --days 14      # 회차 보충 생성
.\.venv\Scripts\python.exe -m app.jobs mark-sessions-for-review   # 검토 대상 판정 (P5 전에는 0건)
.\.venv\Scripts\python.exe -m app.jobs purge-records              # 보낸 전송 기록·만료된 멱등 기록 정리 (7일)
.\.venv\Scripts\python.exe -m app.accounts create --username kim --role collector  # 입력자 계정 (비밀번호 프롬프트)
.\.venv\Scripts\python.exe -m uvicorn app.main:asgi --reload       # http://127.0.0.1:8000/docs · Socket.IO /socket.io
```

## 개발용 임시 계정 (2026-09-18)

화면 작업 전 API를 직접 눌러 보기 위한 계정이다. **개발 DB와 Docker DB에만 만들었고 저장소에는 비밀번호 해시도 넣지 않는다.**

| 역할 | 아이디 | 비밀번호 |
|---|---|---|
| 관리자 | `admin` | `admin` |
| 입력자 | `user` | `1234` |

`APP_ENV=production`에서는 8자 미만 비밀번호로 계정을 만들 수 없다(`app/accounts.py`). 외부 공개 전에 이 두 계정을 지우거나 비밀번호를 재설정한다 — `md_frontend/must_do.md` S3·S4.

## Docker로 실행

```powershell
docker compose up --build   # postgres·redis → migrate(마이그레이션·시드·회차 보충) → api:8000 (REST + Socket.IO)
```

2026-09-15 Docker 29.8 / Compose v5.5에서 기동 확인 (FR-IN-01). 재기동해도 시드·회차 생성이 중복되지 않는다. API 문서: http://127.0.0.1:8000/docs

## 구성

```text
api/
  app/models/        ⓪① reference.py (04) · ② calendar.py (05)
  app/timetable/     source_2026_2.py 원문 그대로 · parse.py X·경유·비고 판별
  app/calendar/      resolve.py 날짜 판정(순수 함수) · service.py 저장·회차 생성
  app/state/         03 회차 상태 — 방문 상태·예측 판정, 응답 조립
  app/candidates/    11 탑승 후보 — classify.py(순수 함수) · service.py
  app/observation/   02·06 관측 수집 — rules.py(진행 규칙) · ingest.py(세션·입력·취소·종료·시계)
  app/realtime/      12 실시간 — state.py(상태 확정·서명) · outbox.py · cache.py(Redis) · server.py(Socket.IO·작업)
  app/operations/    13 운영 — completion.py(완료·회차 상태 집계) · service.py(완료·취소·검토·복구·공지·검토 대상)
  app/auth.py        로그인 토큰·비밀번호 해시 · app/idempotency.py 멱등 키 · app/accounts.py 계정 CLI
  app/api/           /api/v1/routes · /service-calendar · /routes/{id}/stops · /scheduled-trips · /scheduled-trips/{id}/state
                     collection.py 입력자 (06) · admin.py 관리자 /admin/* 와 학생 /notices (13)
  app/seed.py        멱등 시드
  app/jobs.py        회차 보충 · 검토 대상 판정 배치
  alembic/versions/  0001 ⓪①층 · 0002 ②층 · 0003 ③층·계정·멱등 · 0004 ⑤층 공지·운영 결정 · 0005 ⑤층 스냅샷·outbox
  tests/
scripts/dev-db.ps1   휴대용 PostgreSQL
```
