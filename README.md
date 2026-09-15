# ShuttleBus

학교 셔틀 도착 예측 서비스. 설계는 [md/](md/00-overview.md), 구현 순서는 [ROADMAP](md/ROADMAP.md), 화면 구상은 [md_frontend/](md_frontend/README.md).

## 진행 상황

| 단계 | 상태 | 확인 |
|---|---|---|
| P0 골격 | 스키마 ⓪①② 층, 오류 봉투, Compose 구성 | FR-DM-01, 마이그레이션 up/down 왕복 |
| P1 기준 자료 | 시간표 148행 적재, `X` 판별, 운행 달력, 회차·슬롯 생성, 날짜별 정거장 API | FR-RD-01~13·23, FR-SC-01~15 |
| P2~ | 미착수 | — |

③관측·④계산·⑤운영 층 스키마는 해당 단계(P3·P5·P4)에서 층 순서대로 마이그레이션을 추가한다. 인증 뼈대는 입력자 로그인이 필요한 P3에서 만든다.

## 로컬 실행 — Docker 없이

```powershell
setup.cmd                                                          # 도구·패키지 설치
powershell -ExecutionPolicy Bypass -File scripts\dev-db.ps1 start  # PostgreSQL(55432) 기동·마이그레이션·시드

cd api
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m pytest                               # 시험
.\.venv\Scripts\python.exe -m app.jobs ensure-trips --days 14      # 회차 보충 생성
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload        # http://127.0.0.1:8000/docs
```

## Docker로 실행

```powershell
docker compose up --build   # postgres → migrate(마이그레이션·시드·회차 보충) → api:8000
```

Docker가 설치되지 않은 환경에서 작성했으므로 Compose 구성은 **아직 실제로 기동해 보지 않았다** (FR-IN-01 미확인).

## 구성

```text
api/
  app/models/        ⓪① reference.py (04) · ② calendar.py (05)
  app/timetable/     source_2026_2.py 원문 그대로 · parse.py X·경유·비고 판별
  app/calendar/      resolve.py 날짜 판정(순수 함수) · service.py 저장·회차 생성
  app/api/           /api/v1/routes · /service-calendar · /routes/{id}/stops
  app/seed.py        멱등 시드
  app/jobs.py        회차 보충 배치
  alembic/versions/  0001 ⓪①층 · 0002 ②층
  tests/
scripts/dev-db.ps1   휴대용 PostgreSQL
```
