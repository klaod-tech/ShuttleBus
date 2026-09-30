# 작업 상태 — 관리판 자동 생성

- 분야: 문서·연구

> **이 파일은 자동으로 만들어진다. 직접 고치지 않는다.** 상태의 주인은 작업 관리판 카드다
> (`scripts/board/workspace.json`). 카드가 바뀌면 관리판 저장 때 다시 쓰이고, 손으로 다시 만들려면
> `python scripts/board/work.py export`. `work.py check`가 이 파일이 최신인지 검사한다.
>
> md 표의 `카드` 열(`SB-0000`)이 가리키는 상태를 여기서 찾는다.

| 상태 | 카드 |
|---|---|
| 완료 | 48 |
| 검수 | 0 |
| 진행 중 | 1 |
| 할 일 | 51 |
| 결정·확인 필요 | 7 |
| 합계 | 107 |

## P0 골격 — 완료 1/1

| 카드 | 상태 | 제목 | 분야 | 원래 항목 |
|---|---|---|---|---|
| SB-0001 | 완료 | P0 골격 | 서버 | ROADMAP P0 |

## P1 기준 자료 — 완료 1/1

| 카드 | 상태 | 제목 | 분야 | 원래 항목 |
|---|---|---|---|---|
| SB-0002 | 완료 | P1 기준 자료 | 서버 | ROADMAP P1 |

## P2 시간표 학생 화면 — 완료 14/26

| 카드 | 상태 | 제목 | 분야 | 원래 항목 |
|---|---|---|---|---|
| SB-0009 | 완료 | P2 서버 — 회차 상태·탑승 후보·회차 목록 | 서버 | ROADMAP P2 서버 · README 진행 상황 P2 백엔드 |
| SB-0010 | 완료 | 정거장별 다음 버스 조회 API | 서버 | must_do S1 · 04-review 높음 1 |
| SB-0011 | 완료 | CORS 설정 (REST·Socket.IO) | 인프라 | must_do S2 · IMPROVEMENTS 한계 7 · 04-review 높음 2 |
| SB-0012 | 완료 | 실측 이력 observed_* 필드 | 서버 | 04-review 높음 3 |
| SB-0013 | 완료 | 정거장 조회 방향 표시 필드 | 서버 | 04-review 중간 방향 표시 |
| SB-0014 | 완료 | 학생 화면 기본 배치 합의 | 화면 | ROADMAP 사용자 4 · md_frontend/README 합의한 기능 |
| SB-0015 | 완료 | 학생 화면 골격 — 지도·정거장 목록·카드·노선/날짜 선택 | 화면 | must_do F1 (골격) · README 진행 상황 P2 화면 |
| SB-0016 | 완료 | 지도: 정거장 점만·직선 연결 없음·SDK 실패 시 목록 | 화면 | must_do F8 |
| SB-0017 | 완료 | 미검증 좌표 마커·목록 구분 | 화면 | PLAN-screen-fixes 2절 · REVIEW-21 P2 KakaoMap · REVIEW-22 P2 |
| SB-0018 | 완료 | 경로·정거장 요청 경쟁 방지 (abort 확인) | 화면 | PLAN-screen-fixes 3절 · REVIEW-21 P2 page.tsx · REVIEW-22 P2 |
| SB-0019 | 완료 | Next 16.3.5 전환·의존성 취약점 해소 | 화면 | PLAN-screen-fixes 4절 · REVIEW-21 의존성 |
| SB-0020 | 완료 | 화면 설계 남은 선택 결정 (방향 합치기·분 단위 표시·세부 디자인·프로필 항목) | 화면 | must_do F2 · ROADMAP 결정 대기 2 · 03 남은 선택 2~4 |
| SB-0103 | 완료 | 다른 날짜 조회·자정 표시 제안 채택 여부 | 화면 | 03 남은 선택 3 (SB-0020에서 분리) |
| SB-0107 | 완료 | 출발 시각 선택 — '지금 출발' 칩과 depart_after 조건 (API 계약 변경) | 서버 | SB-0103 논의 A안 (2026-09-30) |
| SB-0021 | 할 일 | 학생 화면 남은 부분 — 검색(출발·도착)·시간표 메뉴·왼쪽 햄버거 패널·프로필 설정·공지 배너 | 화면 | must_do F1 (남은 화면) |
| SB-0022 | 할 일 | 근거 구분 표시 — 실측·예측·시간표 기준을 문구로 구분 | 화면 | must_do F3 |
| SB-0023 | 할 일 | needs_review·수집 종료를 '운행 완료'로 표시하지 않기 | 화면 | must_do F4 |
| SB-0024 | 할 일 | 공지 배너 만료 시각에 서버 이벤트 없이 제거 | 화면 | must_do F5 |
| SB-0025 | 할 일 | 실시간 연결 (Socket.IO 구독·재연결) | 화면 | must_do F6 |
| SB-0026 | 할 일 | 조회 결과 없음 사유 구분과 무운행일 표시 | 화면 | must_do F7 · 04-review 중간 무운행일 |
| SB-0027 | 할 일 | 시간표 중간 지점 공시 시각 제공 방식 | 서버 | 04-review 중간 시간표 중간 지점 |
| SB-0029 | 할 일 | 실제 승차 위치(외부역 출구 등)·학생회관 승차 지점 확인 | 자료·현장 | IMPROVEMENTS 확인대기 4 · ROADMAP 사용자 1 |
| SB-0030 | 할 일 | 실제 지도 화면 확인 (localhost:3000 지도 타일·목록·카드·노선/날짜 변경) | 화면 | PLAN-screen-fixes 8절 4 · must_do 0절 실제 지도 |
| SB-0031 | 할 일 | 화면 프로덕션·Docker 실행 검증 | 인프라 | PLAN-screen-fixes 8절 5 · REVIEW-21 P2 Compose · REVIEW-21 다음 준비 5 · must_do 0절 Docker |
| SB-0104 | 할 일 | 세부 크기·시각 디자인·프로필 설정 항목 | 화면 | 03 남은 선택 4 (SB-0020에서 분리) |
| SB-0028 | 결정·확인 필요 | 정보 만료(신선도) 기준의 서버 전달 방식 합의 | 서버 | 04-review 중간 정보 만료 |

## P3 관리자 수동 수집 — 완료 4/25

| 카드 | 상태 | 제목 | 분야 | 원래 항목 |
|---|---|---|---|---|
| SB-0032 | 완료 | P3 서버 1·2부 — 수집 세션·관측 입력·관리자 검토·완료·취소·공지 | 서버 | ROADMAP P3 서버 · README 진행 상황 P3 |
| SB-0033 | 완료 | 현재 개발 로그인 기준 — 아이디·비밀번호 + 24시간 토큰 | 서버 | must_do S3 |
| SB-0034 | 완료 | 로그인 시도 제한·토큰 즉시 차단 | 서버 | must_do S4 · IMPROVEMENTS 한계 1·2 · 04-review 공개 전 인증 |
| SB-0035 | 완료 | 멱등 기록 보존 기간 7일과 정리 작업 | 서버 | must_do S5 · IMPROVEMENTS 한계 3 |
| SB-0037 | 할 일 | 입력자 화면 — 로컬 영속 대기 큐 — 새로고침·재로그인 후 복구, client_event_id·순번 유지, 같은 본문 재전송은 같은 Idempotency-Key | 화면 | must_do C1 |
| SB-0038 | 할 일 | 입력자 화면 — writer_instance_id 로컬 보관, 재시작 시 세션 시작 요청에 첨부. 잃으면 관리자 종료 후 새 세션 안내 | 화면 | must_do C2 |
| SB-0039 | 할 일 | 입력자 화면 — 시계 확인 절차 — t0 전송, 응답 받은 순간 t3 전송, clock_check_id를 관측에 첨부 | 화면 | must_do C3 |
| SB-0040 | 할 일 | 입력자 화면 — SKIP_LIMIT_EXCEEDED 확인 대화상자(누락될 정거장 목록) → confirm_skip=true 재전송 | 화면 | must_do C4 |
| SB-0041 | 할 일 | 입력자 화면 — 자동 누락 발생 표시, 검토 대기 결과는 '기록 확인 필요' | 화면 | must_do C5 |
| SB-0042 | 할 일 | 입력자 화면 — '수집 종료'와 '운행 완료'를 다른 버튼·문구로. 종료 시 대기 큐 전송 후 종료 요청 | 화면 | must_do C6 |
| SB-0043 | 할 일 | 입력자 화면 — 토큰 만료 2시간 전 재로그인 안내, 401에서도 대기 큐 유지 | 화면 | must_do C7 |
| SB-0044 | 할 일 | 입력자 화면 — 오류 코드별 안내 문구 (EVENT_ORDER_CONFLICT는 취소 사용 안내 등) | 화면 | must_do C8 |
| SB-0045 | 할 일 | 관리자 화면 — 검토 목록 — 날짜별 수집 기록, 검토 필요·완료 재검토 필요 필터 | 화면 | must_do A1 |
| SB-0046 | 할 일 | 관리자 화면 — 세션 상세 — 취소·누락·검토 대기 구분, 개별 승인·기각(승인은 확인 근거 필수) | 화면 | must_do A2 |
| SB-0047 | 할 일 | 관리자 화면 — 오취소 복구 (RESTORE_CONFLICT면 대체 관측을 먼저 취소하라고 안내) | 화면 | must_do A3 |
| SB-0048 | 할 일 | 관리자 화면 — 완료 확정 — 근거 종류·메모·실제 완료 시각. '기록 정리'와 '운행 종료 확인' 문구 분리 | 화면 | must_do A4 |
| SB-0049 | 할 일 | 관리자 화면 — 완료 재검토 — 유지(새 근거) / 되돌리기(사유) | 화면 | must_do A5 · 04-review 중간 완료 재검토 필터 |
| SB-0050 | 할 일 | 관리자 화면 — 회차 취소 — 사유 입력 + 확인 단계 | 화면 | must_do A6 |
| SB-0051 | 할 일 | 관리자 화면 — 공지 관리 — 생성·목록·조기 만료 | 화면 | must_do A7 |
| SB-0052 | 할 일 | 관리자 화면 — 점유가 풀리지 않는 세션 종료 | 화면 | must_do A8 |
| SB-0053 | 할 일 | 관리자 화면 — 버전 충돌(CONTROL_VERSION_CONFLICT·INPUT_VERSION_CONFLICT) 시 최신 상태 다시 불러오기 | 화면 | must_do A9 |
| SB-0054 | 할 일 | 관리자 세션 상세에 회차·control_version 연결 | 서버 | 04-review 중간 관리자 버전·회차 연결 |
| SB-0055 | 할 일 | 관리자 수집 기록 목록의 세션당 추가 조회 2회 | 서버 | IMPROVEMENTS 한계 6 |
| SB-0106 | 할 일 | 담당자 전용 앱 만들기 — 학생 앱과 별도 프로젝트·주소·디자인 (입력자·관리자) | 화면 | 01 '담당자 화면은 별도 앱' (2026-09-30) |
| SB-0036 | 결정·확인 필요 | 입력자·관리자 로그인 방식 최종 결정 | 서버 | ROADMAP 결정 대기 1 |

## P4 실시간 — 완료 1/1

| 카드 | 상태 | 제목 | 분야 | 원래 항목 |
|---|---|---|---|---|
| SB-0056 | 완료 | P4 실시간 — 스냅샷·outbox·Socket.IO·Redis 복원 | 서버 | ROADMAP P4 · README 진행 상황 P4 |

## P5 통계와 예측 — 완료 0/2

| 카드 | 상태 | 제목 | 분야 | 원래 항목 |
|---|---|---|---|---|
| SB-0057 | 할 일 | 직접 탑승 측정 2~3회, 이후 시간대 밴드 각 5회 | 자료·현장 | IMPROVEMENTS 확인대기 7 · ROADMAP 사용자 2 |
| SB-0058 | 결정·확인 필요 | P5 통계와 예측 착수 | 서버 | ROADMAP P5 · README 진행 상황 P5 |

## P6 GPS 자동화 — 완료 16/25

| 카드 | 상태 | 제목 | 분야 | 원래 항목 |
|---|---|---|---|---|
| SB-0059 | 완료 | 경로 자료 계획 작성 | 문서·연구 | PLAN-route-data 순서 1 |
| SB-0060 | 완료 | 경로 자료 ① 임시 좌표 씨앗 samples/stops-provisional.json + app.stops import 덮어쓰기 보호 | 서버 | PLAN-route-data 순서 2 |
| SB-0061 | 완료 | 경로 자료 ② app/survey.py — gpx-demo·import·build-path·verify·list, 출처 기록(survey_path_builds, 마이그레이션 0008) | 서버 | PLAN-route-data 순서 3 |
| SB-0062 | 완료 | 경로 자료 ② tests/test_survey.py 회귀 시험 | 서버 | PLAN-route-data 순서 4 |
| SB-0063 | 완료 | 경로 자료 ③ GET /routes/{id}/path + 시험 (구간 부족 시 partial) | 서버 | PLAN-route-data 순서 5 |
| SB-0064 | 완료 | 경로 자료 ③ web/ 폴리라인 + md/10 5장 표 | 화면 | PLAN-route-data 순서 6 |
| SB-0065 | 완료 | 경로 자료 문서 — IMPROVEMENTS 등록 절차 명령 이름, CHANGELOG | 문서·연구 | PLAN-route-data 순서 7 |
| SB-0066 | 완료 | 조사 경로 검증 오판 차단 — 데모·자기검증·출처 확인 불가·CLI 우회 | 서버 | REVIEW-21 P1 verify_path · REVIEW-22 P1 CLI 우회 · REVIEW-22 P1 시각 없는 GPX |
| SB-0067 | 완료 | 경로 전체 verified 조건 — 구간 수를 정거장 수−1과 대조 | 서버 | REVIEW-21 P1 get_route_path |
| SB-0068 | 완료 | 조사 판정값을 Settings·01 설정 인덱스로 이관 | 서버 | REVIEW-21 P2 survey 시험값 · REVIEW-22 P2 SAME_RECORDING_OVERLAP |
| SB-0069 | 완료 | GPX 1.0(speed 직계·accuracy 없음·이른 주석) 적재 회귀 시험 | 서버 | IMPROVEMENTS GPS 후속 1 (GPX 1.0 부분) |
| SB-0070 | 완료 | 주석 이름과 정거장 매칭 정책 | 서버 | IMPROVEMENTS GPS 후속 2 |
| SB-0071 | 완료 | 연속 정차 후보와 반복 방문 분리 | 서버 | IMPROVEMENTS GPS 후속 3 |
| SB-0072 | 완료 | 수신 공백에서 트랙을 끊고 가장 긴 연속 조각만 경로로 | 서버 | IMPROVEMENTS 추가 검토 trkseg · CHANGELOG 09-28 수신 공백 |
| SB-0073 | 완료 | GPS 공백 복구용 경로 자료 확보 방침 확정 (학교 문의 종료) | 자료·현장 | IMPROVEMENTS 1순위 |
| SB-0077 | 완료 | GPX 파일 사전 점검 (DB 쓰기 전 버전·누락 필드·시각 순서·중복·공백 요약) | 서버 | IMPROVEMENTS GPS 후속 1 |
| SB-0074 | 할 일 | 버스 GPS 단말 설치 허가 주체와 가능 여부 확인 | 자료·현장 | IMPROVEMENTS 확인대기 6 · ROADMAP 사용자 1 · ROADMAP P6 선행 조건 |
| SB-0075 | 할 일 | GPX 경로 녹화 (탑승 중 GPS Logger) | 자료·현장 | IMPROVEMENTS 확인대기 8 · ROADMAP 사용자 3 · ROADMAP P6 선행 조건 |
| SB-0076 | 할 일 | 등교·하교 경로 동일 여부와 우회 빈도 확인 | 자료·현장 | IMPROVEMENTS 확인대기 3 · ROADMAP 사용자 1 |
| SB-0078 | 할 일 | 첫 셔틀 자료로 정거장 좌표 검토 → 구간 생성 | 자료·현장 | IMPROVEMENTS GPS 후속 4 |
| SB-0079 | 할 일 | 독립 두 번째 셔틀 자료로 검증과 부분 경로 표시 확인 | 자료·현장 | IMPROVEMENTS GPS 후속 5 |
| SB-0080 | 할 일 | 실제 노선 자료로 카카오맵 전체 흐름 점검 | 화면 | IMPROVEMENTS GPS 후속 6 |
| SB-0081 | 결정·확인 필요 | GPS 공백 복구 흐름 — 현장 확인 후 03·07·02·08·11·12 반영 | 서버 | IMPROVEMENTS 1순위 적용 게이트·확인 후 반영할 문서 |
| SB-0082 | 결정·확인 필요 | P6 GPS 자동화 착수 — ④ 실시간 GPS 수신 | 서버 | ROADMAP P6 · PLAN-route-data 순서 8 · README 진행 상황 P6 |
| SB-0083 | 결정·확인 필요 | 실시간 단말 정확도·오프라인 재전송 조사 | 서버 | IMPROVEMENTS GPS 후속 7 |

## P7 화면 완성 — 완료 0/2

| 카드 | 상태 | 제목 | 분야 | 원래 항목 |
|---|---|---|---|---|
| SB-0084 | 할 일 | P7 화면 완성 — 경로 폴리라인·카드 레이아웃·상태 전환·근거 표시·반응형·PWA | 화면 | ROADMAP P7 |
| SB-0085 | 할 일 | 화면 호환성 점검 (기기 폭·가로세로·안전 영역·브라우저·키보드 접근·느린 통신) | 화면 | 04-review 화면 호환성 검증 계획 |

## P8 Kubernetes — 완료 0/2

| 카드 | 상태 | 제목 | 분야 | 원래 항목 |
|---|---|---|---|---|
| SB-0086 | 할 일 | 처음 조회되는 날짜에 학생 GET이 회차를 생성(쓰기)하는 한계 | 서버 | IMPROVEMENTS 한계 4 |
| SB-0087 | 할 일 | P8 Kubernetes — 서비스 분리·minikube·리소스 매핑·장애·백업 복원 실습 | 인프라 | ROADMAP P8 |

## 상시 운영 — 완료 11/22

| 카드 | 상태 | 제목 | 분야 | 원래 항목 |
|---|---|---|---|---|
| SB-0008 | 완료 | 정상 실행에서 회차 보충 작업이 날짜별 회차를 만드는지 확인 | 서버 | REVIEW-2026-09-21 다음 준비 3 |
| SB-0088 | 완료 | 작업 관리판 도입 (proto_dashboard) | 문서·연구 | PLAN-project-board |
| SB-0089 | 완료 | README·01·02 끊긴 문장 복구, 분 단위 내림·올림 미확정으로 통일 | 문서·연구 | must_do D1 · 04-review 반영 완료 |
| SB-0090 | 완료 | README 기준을 v7.10 변경 기록과 09-18 운영 결정으로 갱신 | 문서·연구 | must_do D2 |
| SB-0091 | 완료 | 문서·연동 점검 (04-review) | 문서·연구 | must_do D3 |
| SB-0092 | 완료 | REVIEW-22 문서 정합 3건 — CHANGELOG 3회분·REVIEW-21 다음 순서·PLAN-route-data 최신화 | 문서·연구 | REVIEW-22 문서 정합 |
| SB-0095 | 완료 | 실행 안내 보완 — API·화면을 별도 터미널에서, dev-db.ps1 start의 초기화 동작 명시 | 문서·연구 | PLAN-screen-fixes 8절 3 |
| SB-0097 | 완료 | main 갱신 (develop 병합으로 옛 .env.example 값 제거) | 인프라 | REVIEW-secrets 남은 조치 2 |
| SB-0099 | 완료 | 관리판 상태를 GitHub에서 보이게 — 카드 상태 자동 생성 문서 | 문서·연구 | PLAN-project-board 6장 |
| SB-0100 | 완료 | 관리판 도입 뒤 정리 — 포트 충돌·신원 확인·P1 진행도·.claude 스킬·카드 편집 규칙·낡은 좌표 문구·브랜치 병합 | 문서·연구 |  |
| SB-0101 | 완료 | 로컬 한 번에 실행 — 서버.cmd (DB·마이그레이션·시드·회차·임시 좌표·API·화면) | 인프라 |  |
| SB-0102 | 진행 중 | 디자인 준비 메모 — 서버 작업 중 나온 화면 상태·문구 모음 | 화면 |  |
| SB-0003 | 할 일 | 중간 정거장(탕정역·시티프라디움 등) 정차 여부 확인 | 자료·현장 | IMPROVEMENTS 확인대기 1 · ROADMAP 사용자 1 |
| SB-0004 | 할 일 | 외부역 정차 시간(도착 후 몇 분 뒤 출발) 확인 | 자료·현장 | IMPROVEMENTS 확인대기 2 · ROADMAP 사용자 1 |
| SB-0005 | 할 일 | 중간 구간 대략 소요 범위 확인 | 자료·현장 | IMPROVEMENTS 확인대기 5 · ROADMAP 사용자 1 |
| SB-0006 | 할 일 | 펜타포트 위치 확인 | 자료·현장 | IMPROVEMENTS 확인대기 9 |
| SB-0007 | 할 일 | 시간표 재시드가 이미 생성된 회차 시각에 반영되지 않는 한계 | 서버 | IMPROVEMENTS 한계 5 |
| SB-0093 | 할 일 | 화면 인계 문구 정합성 보완 (must_do '정거장 22개' 구분, F8 '정거장 점만' 문구) | 문서·연구 | PLAN-screen-fixes 8절 1 |
| SB-0094 | 할 일 | 04-review 남은 항목을 항목별 상태로 정리 | 문서·연구 | PLAN-screen-fixes 8절 2 |
| SB-0096 | 할 일 | 개발 계정(admin·user) 비밀번호 재설정 | 서버 | REVIEW-secrets 남은 조치 1 · ROADMAP 운영 전 정리 · 04-review 인증 |
| SB-0098 | 할 일 | GitGuardian 경보 해결 처리 | 인프라 | REVIEW-secrets 남은 조치 3 |
| SB-0105 | 결정·확인 필요 | 외부 공개 전 로그인 보호 — IP당 로그인 시도 제한·짐작 어려운 담당자 아이디 | 서버 | 01 '담당자 화면은 별도 앱' |
