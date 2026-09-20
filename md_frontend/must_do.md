# must_do · UI 단계에서 반드시 할 일

작성일: 2026-09-15 · 상태: 서버 작업 중 미룬 항목 모음

서버·백엔드 작업이 끝난 뒤 화면을 만든다는 방침에 따라, **화면 설계와 함께 정해야 해서 지금 하지 않은 일**을 모았다. 화면 작업을 시작할 때 이 목록부터 확인한다. 끝낸 항목은 지우지 말고 `완료`와 날짜를 적는다.

서버 계약은 ../md 문서가 기준이다. 이 목록은 그 계약을 바꾸지 않는다.

---

## 1. 서버 쪽이지만 화면과 함께 정할 것

| # | 할 일 | 왜 미뤘나 | 근거 |
|---|---|---|---|
| S1 | ~~정거장별 다음 버스 조회 API~~ | **완료 (2026-09-18)** — `GET /stops/{stop_id}/upcoming?route_id&service_date`. 방향 합쳐서 2개 + 각 행에 `next_stop_name`·`terminal_stop_name`, 대표 시각 도착→출발, `attention`·`reference_timetable`·`empty_reason` 분리. 계약은 ../md/11 11장 | [02](02-stop-upcoming.md), ../md/11-boarding-candidates.md 11장 |
| S2 | ~~CORS 설정~~ | **완료 (2026-09-18)** — `CORS_ORIGINS`(쉼표 구분)로 REST·Socket.IO를 함께 허용. Docker는 루트 `.env`의 값을 넘긴다. 필요하면 `SOCKET_CORS_ORIGINS`로 따로 지정. `*`는 쓰지 않는다 | ../md/01-conventions.md 7장 |
| S3 | **현재 개발 로그인 기준 확인 완료 (2026-09-18)** — 아이디·비밀번호 + 24시간 토큰 | 학생은 로그인 없음. 관리자 admin/admin, 입력자 user/1234로 개발 화면을 연동한다. 대체 로그인 방식은 현 단계의 선행 조건이 아니다. **개발용 임시 계정 `admin/admin`·`user/1234`(2026-09-18)를 공개 전에 지우거나 재설정한다** | ../md/01-conventions.md 5장, ../README.md |
| S4 | ~~로그인 시도 제한·토큰 즉시 차단~~ | **완료 (2026-09-18)** — 5회 실패 15분 잠금 `LOGIN_LOCKED`(429, retryable). 화면은 이 코드에 "잠시 후 다시" 안내를 붙이고 대기 큐를 유지한다. 비밀번호 재설정 후 이전 토큰은 401 | ../md/01-conventions.md 5장 |
| S5 | ~~멱등 기록 보존 기간~~ | **완료 (2026-09-18)** — 7일 확정, 정리 작업 구현 | — |

## 2. 학생 화면

| # | 할 일 | 근거 |
|---|---|---|
| F1 | **골격 착수 (2026-09-18)** — `web/`에 지도·정거장 목록·정거장 카드·노선/날짜 선택까지. 남은 것: 검색(출발·도착 후보), 시간표 메뉴, 왼쪽 햄버거 패널, 프로필, 공지 배너 | [01](01-screens.md), [03](03-figma-handoff.md), ../web |
| F2 | 03 '화면 설계 확정 전 남은 선택' 결정 — 방향 합치기, 분 단위 표시 규칙, 세부 크기·시각 디자인·프로필 항목. 공지는 배너로 제공 | [03](03-figma-handoff.md) |
| F3 | 근거 구분 표시: 실측·예측·시간표 기준을 문구로 구분. 시간표로 ETA를 직접 계산하지 않는다 | ../md/03-state-contract.md, ../md/08-prediction.md |
| F4 | `needs_review`·수집 종료를 '운행 완료'로 표시하지 않는다 (FR-OP-03). 완료 차량은 '이번 운행 종료', 취소는 사유 표시 | ../md/13-operations.md 2장, ../md/03-state-contract.md 6장 |
| F5 | 공지 배너: 만료 시각이 되면 서버 이벤트를 기다리지 않고 제거 | ../md/13-operations.md 6장 |
| F6 | 실시간 연결 (서버 P4 완료): Socket.IO 클라이언트로 `/socket.io` 접속 → `route:subscribe`·`trip:subscribe`(응답 `{ok}`) → 12 3장 순서(핸들러 먼저, 조회 중 이벤트 보관, 더 큰 `state_version`만 반영), 재연결 시 전부 다시 조회, 연결 상태를 GPS 장애로 표시하지 않음. 이벤트: `trip:state`·`notice:changed`·`schedule:changed`·`candidates:changed`. 서버가 검증하지 못한 FR-RT-01·02·05·06·13·19·20을 화면에서 확인 | ../md/12-realtime-delivery.md 2·3장·'구현 메모' |
| F7 | 조회 결과 없음 사유 구분: 운행 없음·자료 미확인·기간 밖·남은 운행 없음. 확인 필요 항목이 있으면 '모든 버스 종료'라고 쓰지 않는다 | ../md/11-boarding-candidates.md 6장 |
| F8 | **구현 (2026-09-18)** — `web/components/KakaoMap.tsx`: 정거장 점만, 직선 연결 없음, SDK 실패 시 목록으로 진행, 좌표 없는 정거장은 목록에 '좌표 확인 필요'. **정거장 좌표는 현재 0/22 등록** — 등록 전에는 마커가 하나도 없다 | ../md/10-stop-discovery.md 2·3장 |

## 3. 입력자 화면

| # | 할 일 | 근거 |
|---|---|---|
| C1 | 로컬 영속 대기 큐: 새로고침·재로그인 후 복구, 논리 관측 ID(`client_event_id`)·순번 유지, 동일 본문 통신 재전송은 같은 `Idempotency-Key` 유지. 버전·확인 옵션 등 본문 변경 시에만 새 키 발급 | ../md/06-manual-collection.md 5장 |
| C2 | `writer_instance_id` 로컬 보관, 재시작 시 세션 시작 요청에 실어 보내기. 잃어버리면 관리자 종료 후 새 세션 안내 | ../md/06-manual-collection.md 7장 |
| C3 | 시계 확인 절차: 단말 송신 시각 t0 전송 → 응답 받은 순간 t3 전송. 받은 `clock_check_id`를 관측에 첨부 | ../md/02-observation-contract.md 12장 |
| C4 | `SKIP_LIMIT_EXCEEDED` 확인 대화상자(누락될 정거장 목록 표시) → `confirm_skip=true` 재전송 | ../md/06-manual-collection.md |
| C5 | 자동 누락 발생 시 "3·4번 정거장이 누락으로 기록됨" 표시. 검토 대기 결과는 "기록 확인 필요" | ../md/06-manual-collection.md 3·5장 |
| C6 | '수집 종료'와 '운행 완료'를 다른 버튼·문구로. 종료 시 대기 큐 전송 후 종료 요청 | ../md/06-manual-collection.md 1장, 9장 |
| C7 | 토큰 만료 2시간 전 재로그인 안내, 401에서도 대기 큐 유지 | ../md/01-conventions.md 5장 |
| C8 | 오류 코드별 안내 문구 (`EVENT_ORDER_CONFLICT`는 취소 사용 안내 등) | ../md/06-manual-collection.md 4장, ../md/01-conventions.md 오류 코드 인덱스 |

## 4. 관리자 화면

| # | 할 일 | 서버 API (구현됨) |
|---|---|---|
| A1 | 검토 목록: 날짜별 수집 기록, 검토 필요·완료 재검토 필요 필터 | `GET /admin/collection-sessions` |
| A2 | 세션 상세: 취소·누락·검토 대기 구분, 개별 승인·기각(승인은 확인 근거 필수) | `GET /admin/collection-sessions/{id}/events`, `POST /admin/events/{id}/review` |
| A3 | 오취소 복구 (`RESTORE_CONFLICT`면 대체 관측을 먼저 취소하라고 안내) | `POST /admin/events/{id}/restore`, `POST /events/{id}/cancel` |
| A4 | 완료 확정: 근거 종류 선택, 메모, 실제 완료 시각(선택). '기록 정리'와 '운행 종료 확인' 문구 분리 | `POST /admin/trip-vehicles/{id}/completion` |
| A5 | 완료 재검토: 유지(새 근거) / 되돌리기(사유) | `POST /admin/trip-vehicles/{id}/completion-review` |
| A6 | 회차 취소: 사유 입력 + **확인 단계** | `POST /admin/scheduled-trips/{id}/cancellation` |
| A7 | 공지 관리: 생성·목록·조기 만료 | `POST /admin/notices`, `POST /admin/notices/{id}/expire`, `GET /notices` |
| A8 | 점유가 풀리지 않는 세션 종료 | `POST /collection-sessions/{id}/end` |
| A9 | 버전 충돌(`CONTROL_VERSION_CONFLICT`·`INPUT_VERSION_CONFLICT`) 시 최신 상태 다시 불러오기 | 모든 관리 변경 |

## 5. 문서 정리

| # | 할 일 |
|---|---|
| D1 | **완료 (2026-09-18)** — README·01·02의 끊긴 문장 복구. 분 단위 내림·올림은 미확정으로 통일 |
| D2 | **완료 (2026-09-18)** — README 기준을 v7.10 변경 기록과 2026-09-18 운영 결정으로 갱신 |
| D3 | **점검 완료 (2026-09-18), 후속 작업 남음** — [문서·연동 점검](04-review.md)의 응답 부족·조회 연결·화면 호환성 항목을 구현 시 확인 |

## 서버 단계와의 관계

- **예측(P5)과 GPS 위치(P6)** 는 사용자 현장 작업(탑승 기록·GPX·단말 허가) 뒤에 진행한다. 화면은 그 전에 만들어도 된다. 응답에 예상 시각 칸과 '자료 없음' 사유가 이미 있어 값만 채워진다.
- **실시간(P4)** 서버 구현은 완료했다. F6은 P4 계약을 따른다.
