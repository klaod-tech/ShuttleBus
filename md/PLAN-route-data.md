# 계획 — 노선 경로 자료: 좌표 씨앗 → GPX 적재 → 경로 API → 실시간 GPS

> 작성 2026-09-18. 현장 자료(정거장 좌표·GPX·GPS 단말)가 아직 없는 동안 **가짜 자료로 파이프라인 전체를 먼저 돌려 보고**, 진짜 자료가 오면 같은 명령에 넣기만 하면 되게 만든다. 규칙은 `04`·`07`·`10`이 소유하고 이 문서는 순서와 완료 판정만 정한다. 화면(FE)은 외부에 맡기므로 여기서는 `web/`에 경로선 표시 최소만 붙인다.

## 질문에 대한 답 — "이 정도로 충분한가"

셔틀 위치를 지도에 실시간으로 보이려면 네 단계가 전부 있어야 한다. 지금 있는 것과 없는 것:

| 단계 | 무엇 | 현재 | 이번에 |
|---|---|---|---|
| ① 정거장 좌표 | 마커를 찍을 위치 | 테이블 있음, **0/22 등록** | 임시 좌표 씨앗 (`needs_interpretation`) |
| ② 경로 자료 | GPS Logger의 GPX → `route_path_points`·`route_stop_segments` | 테이블 있음, **적재기 없음** | 적재기·단순화·구간 분할·검증 CLI |
| ③ 경로 표시 | 서버가 경로를 내주고 지도가 그림 | **API 없음, 화면 없음** | `GET /routes/{id}/path` + `web/` 폴리라인 |
| ④ 실시간 위치 | 단말 → 서버 → 지오펜스 판정 → 관측 | **없음** (P6) | 계획만. 수신 형식을 Traccar/OsmAnd로 확정 |

**②가 ④의 전제다.** `07`의 경로 이탈·공백 복원은 `route_stop_segments`가 `verified`일 때만 켜진다. 경로 없이 GPS 단말을 달면 좌표는 쌓이지만 "어느 구간에 있는가"를 못 정한다. 그래서 순서가 ①②③ → ④다.

**충분하지 않은 것** — 코드로 못 대신하는 것 세 가지: 실제 정거장 좌표(현장), 실제 GPX 2회 이상(같은 패턴을 두 번 타야 `verified`), 단말 설치 허가. 이번 작업은 그 자료가 들어올 자리와 명령을 만드는 것이다. 가짜 자료로 `verified`를 만들지 않는다.

## ① 정거장 임시 좌표

`api/samples/stops-provisional.json` — 역·터미널처럼 공개된 지점만, 전부 `needs_interpretation`. 캠퍼스 안 승차 위치·아파트 정류장처럼 현장이 아니면 모르는 곳은 넣지 않는다 (좌표를 지어내지 않는다).

```powershell
python -m app.stops import --file samples\stops-provisional.json
```

- 이미 `verified`인 정거장은 덮지 않는다 (`--no-overwrite-verified` 기본).
- 화면은 `verification_status != verified`를 '확인 필요' 마커로 구분한다 (`10` 3장).
- **완료 판정:** `app.stops list`에 좌표 7개 이상, 지도에 마커가 뜬다.

## ② GPX 적재기 — `python -m app.survey`

IMPROVEMENTS '등록 절차' 7단계를 명령으로 만든다. 원본(⓪ 조사 층)은 절대 고치지 않고, 정제 결과(① `route_path_points`·`route_stop_segments`)는 언제든 다시 만든다.

| 명령 | 하는 일 | 04·07 근거 |
|---|---|---|
| `gpx-demo --pattern cheonan_asan/general --out demo.gpx` | ①의 좌표를 이어 **가짜 트랙** 생성. 정거장마다 정차(속도 0) 구간, 좌표 흔들림, `<wpt>` 주석. 파일 이름에 `demo`가 박힌다 | 시험 전용. 진짜 자료가 오면 안 쓴다 |
| `import --file x.gpx --pattern route/code` | GPX 1.0/1.1 파싱 → `survey_tracks`(파일 해시로 멱등)·`survey_track_points`·`survey_annotations`(`<wpt>`). `<extensions>`는 원문 그대로 `raw_extensions`에 | `04` 1장 조사 트랙 |
| `build-path --track <id> [--tolerance 5]` | 이상치 제거(불가능 속도·튄 점) → Douglas-Peucker 단순화 → `route_path_points`(`recorded_track`) → 정거장 좌표에 가장 가까운 점으로 `route_stop_segments` 분할 (`unverified`) → 주석을 정차 구간과 대조해 `resolved_route_stop_id` | IMPROVEMENTS 2~7단계 |
| `verify --track <id> [--max-deviation 30]` | 두 번째 트랙을 현재 경로와 구간별로 대조. 겹치면 `verified`, 어긋나면 `needs_interpretation` | IMPROVEMENTS '두 번째 트랙' |
| `list` | 트랙·경로 상태 | |

정하는 것들:

- **단순화 오차 5m 시작값** (IMPROVEMENTS). `--tolerance`로 바꿔 다시 만들 수 있다 — 그래서 원본을 남긴다.
- **정거장 매핑은 좌표가 있는 정거장만.** 좌표 없는 정거장 사이 구간은 만들지 않고 `list`에 '구간 없음'으로 보인다.
- **첫 트랙은 전부 `unverified`.** `verified`는 `verify`로만 올라간다. 가짜 트랙 두 개로 `verify`를 돌리면 당연히 verified가 되므로 **데모 트랙에는 `verify`를 걸지 않는다** — 시험은 기대 결과만 확인하고 DB에 남기지 않는다.
- 데모 파일 해시는 진짜 파일과 절대 같을 수 없으니 나중에 `survey_tracks`에서 `note = demo` 행만 지우면 된다.
- **완료 판정:** 시험 `test_survey.py` — 데모 GPX 생성→적재→경로 생성→구간 수 = 좌표 있는 인접 정거장 쌍 수, 재적재 멱등, 오차 바꿔 재생성.

## ③ 경로 API와 지도 표시

`GET /api/v1/routes/{route_id}/path?service_date` — 그 날짜에 적용되는 패턴별로:

```
route_version_id, pattern_code, path_source, point_count,
points: [[lat, lng], …],
segments: [{from_route_stop_id, to_route_stop_id, path_from_seq, path_to_seq, distance_m, verification_status}],
verification: verified | partial | unverified | none
```

`web/components/KakaoMap.tsx`에 `kakao.maps.Polyline` 한 종류 추가:

| `verification` | 표시 |
|---|---|
| `verified` | 실선 |
| `partial`·`unverified` | **점선 + "미검증 경로"** 표시 |
| `manual_trace` 구간 | 점선 + "추정 경로" (`10` 5장) |
| `none` (행 없음) | 아무것도 안 그림 — 직선 연결도 하지 않는다 (must_do F8) |

`10` 5장에 위 표를 옮겨 적는다. **완료 판정:** 데모 트랙을 적재한 뒤 지도에 점선 경로가 뜨고, 아무것도 안 적재하면 마커만 뜬다.

## ④ 실시간 GPS 수신 — 다음 작업 (P6)

기기는 **남는 안드로이드 폰 + Traccar Client**로 정했다 (2026-09-18). 무료이고 OsmAnd 형식으로 HTTP 전송한다. 설치 허가가 나면 폰을 차량에 두고 보조배터리로 하루를 버틴다.

수신 계약 초안 — `07` 1장 단말 인증·배정에 맞춰 다음 작업에서 문서로 확정한 뒤 만든다:

```
POST /api/v1/device/positions?id={device_token}&lat=&lon=&timestamp=&speed=&bearing=&accuracy=&batt=
```

- `id`는 관리자가 발급한 단말 토큰. 차량 배정(`trip_vehicle_id`)은 서버가 `07` 1장 규칙으로 한다 — 폰은 자기가 몇 회차인지 모른다.
- 도착 순서 그대로 `device_positions`에 저장(`07` 4장), 재정렬·지오펜스·이탈 게이트는 그 다음 단계.
- `accuracy` 필드가 여기서 들어오므로 `max_position_accuracy_m`을 실측할 수 있다 (조사 트랙 GPX에는 없음).
- 시험은 가짜 단말이 데모 경로를 따라 좌표를 쏘는 스크립트로 한다.

`07`의 설정값(`max_route_deviation_m`, `route_deviation_min_points`, `dwell_min_seconds`, `terminal_boundary_min_points`)은 **진짜 트랙 두 개**가 있어야 정한다. 그 전까지 이탈 판정·공백 복원은 꺼져 있다 (`07` 6장 결정 전 처리).

## 데모로 돌려보기 — 무엇이 보여야 정상인가

```powershell
cd api; $env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m pytest tests\test_survey.py -v                                 # 8개
.\.venv\Scripts\python.exe -m app.stops import --file samples\stops-provisional.json           # 7개 등록
.\.venv\Scripts\python.exe -m app.survey gpx-demo --pattern cheonan_asan/general --out demo.gpx
.\.venv\Scripts\python.exe -m app.survey import --file demo.gpx --pattern cheonan_asan/general --note demo
.\.venv\Scripts\python.exe -m app.survey build-path --track <import가 출력한 id>
.\.venv\Scripts\python.exe -m app.survey list
```

| 단계 | 정상이면 |
|---|---|
| `stops import` | "7개 정거장 좌표 등록, 0개 건너뜀". 두 번 돌리면 결과 같음 |
| `gpx-demo` | "정거장 4개" — 천안아산역 노선 5방문 중 **시티프라디움은 임시 좌표가 없어 빠진다** (캠퍼스·탕정역·천안아산역·캠퍼스) |
| `import` | "적재: … 점 200~300개". 같은 파일 다시 넣으면 "이미 있는 파일" |
| `build-path` | "구간 2개 (unverified)" + "구간 없음: 시티프라디움" — 탕정역→시티프라디움, 시티프라디움→천안아산역 구간을 **만들지 않는다.** 가짜 구간을 만드느니 비워 둔다 |
| `web` (npm run dev) | 마커 4개(전부 '확인 필요' 표시) + **점선** 경로 "미검증 경로". 탕정역→천안아산역이 직선 한 줄인 것은 데모 트랙이 정거장을 직선으로 이었기 때문이지 버그가 아니다 |

**데모 자료의 한계 — 이것으로 판단하지 말 것**

- 임시 좌표는 작성자(AI) 기억의 역·터미널 대략 위치다. 수십 m 틀릴 수 있다. 그래서 `needs_interpretation`이고 지도에도 '확인 필요'로 보인다.
- 데모 트랙은 정거장 사이를 **직선**으로 잇는다. 도로를 따르지 않는다. 지오펜스 반경·이탈 거리·`dwell_min_seconds` 같은 `07` 설정값을 이 트랙으로 정하면 안 된다.
- `verify`를 데모 두 개로 돌리면 verified가 되어 버린다. **데모에는 verify를 걸지 않는다.** 시험 코드는 트랜잭션을 되돌리므로 DB에 남지 않는다.
- 진짜 GPX가 오면 `survey_tracks`에서 `note = demo` 행과 그 경로를 지우고 같은 명령을 다시 돌린다. 임시 좌표는 `app.stops set --status verified`가 덮는다.

**FE 담당자에게** — 경로선은 `GET /routes/{id}/path`의 `verification`으로만 판단한다. `none`이면 정거장을 잇지 않는다. `web/components/KakaoMap.tsx`의 `pathStyle()`이 참고 구현이다.

## 순서와 상태

| # | 작업 | 상태 |
|---|---|---|
| 1 | 이 계획 | 완료 |
| 2 | ① `samples/stops-provisional.json` + `app.stops import` 덮어쓰기 보호 | 완료 |
| 3 | ② `app/survey.py` — gpx-demo · import · build-path · verify · list | 완료 (시험 미실행) |
| 4 | ② `tests/test_survey.py` — 8개 | 완료 (미실행) |
| 5 | ③ `GET /routes/{id}/path` + `test_route_path_api` | 완료 (미실행) |
| 6 | ③ `web/` 폴리라인 + `10` 5장 표 | 완료 |
| 7 | 문서 — IMPROVEMENTS 등록 절차에 명령 이름, CHANGELOG | 완료 |
| 8 | ④ P6 수신 — 별도 작업 | 대기 (설치 허가) |
