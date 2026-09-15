# 03 · 상태 계약

> 확정된 회차·차량·방문 상태를 REST와 실시간 전송에서 동일한 구조로 제공한다.
> 참조: [관측 계약](02-observation-contract.md) · [예측](08-prediction.md) · [탑승 후보](11-boarding-candidates.md)

## 1. 전체 데이터와 화면 필터

`stops[]`는 해당 회차의 전체 방문 정적 정보를 한 번씩 담는다. `vehicles[].visits[]`도 각 차량의 전체 방문을 한 번씩 담는다. 두 배열은 trip_stop_id로 연결한다. 이미 지난 방문도 서버 응답에서 삭제하지 않는다.

학생 기본 화면에는 앞으로의 방문만 보여주고 지난 방문은 ‘지난 기록’ 영역으로 접는다. 마지막 확인 위치에는 지난 방문 정보를 사용할 수 있다. 한 차량이 지났다는 이유로 다른 차량의 방문을 삭제하지 않는다. 예측 시각 경과만으로 방문을 통과 처리하지 않는다.

## 2. 회차 공통 필드

| 필드 | 의미 |
|---|---|
| trip_id, route_id, route_version_id, service_date | 회차 식별과 적용 경로·날짜 |
| state_version, control_version | 공개 상태 버전·관리 버전 |
| server_time | 응답 생성 시각. 상태 본문 버전과 구분하는 메타데이터 |
| schedule_status, schedule_reason | 05의 날짜 자료 상태·사유 |
| operation_status, cancellation_reason | 회차 운행 상태·취소 사유(null 허용) |
| scheduled_vehicle_count, tracked_vehicle_count | 예정 슬롯 수·현재 유효 관측을 보유한 차량 수 |
| stops[], vehicles[] | 정적 방문과 차량별 동적 상태 |

tracked_vehicle_count는 단순 세션 수가 아니다. collecting 세션이 있어도 공개 유효 관측이 없으면 실측 차량으로 세지 않는다. 오래된 관측만 있는 차량은 현재 실측 대수에서 제외하되 차량 항목 자체는 유지한다.

## 3. stops[] — 정적 방문

필드: `trip_stop_id`, `stop_id`, `stop_name`, `stop_sequence`, nullable `latitude`·`longitude`, `boarding_policy`, `alighting_policy`, `verification_status`, nullable `scheduled_arrival_at`·`scheduled_departure_at`·`scheduled_unspecified_at`.

좌표 미확정은 null이다. 공시 시각의 사건 의미가 미확정이면 unspecified에만 저장한다. 같은 시각을 도착·출발 양쪽에 복제하지 않는다. 기점 승차와 종점 하차 정책은 04·05를 따른다.

## 4. vehicles[] — 차량별 상태

| 필드 | 의미 |
|---|---|
| trip_vehicle_id, vehicle_slot, nullable shuttle_id | 슬롯·실제 차량 |
| operation_status, nullable cancellation_reason | 해당 차량의 운행 상태·사유 |
| information_status | timetable_only / observed / stale / unavailable |
| last_observation | 마지막 진행을 확인한 유효 관측 요약. 없으면 null |
| position_status | not_enabled / locating / current |
| last_position | nullable {latitude, longitude, measured_at}. 검증된 실제 좌표만 |
| visits[] | 차량별 전체 방문 상태 |

information_status는 관측·예측의 유효성이다. timetable_only는 유효 관측 없음, observed는 신선한 유효 관측 보유, stale은 관측 유효기간 경과, unavailable은 관측 경로 신뢰성 문제로 현재 위치 기반 예측을 제공할 수 없는 상태다. 정확한 만료·경로 유효성은 08이 결정한다. GPS 수신과 학생 앱의 서버 연결 상태를 동일시하지 않는다.

position_status는 위치 표시용이며 **저장하지 않고 마지막 좌표의 나이에서 파생한다.** Phase 1은 not_enabled이며 수동 마지막 확인 정거장만 표시한다. Phase 2에서 검증된 좌표가 `gps_stale_after_seconds`(`07` 6장) 안이면 current, 그렇지 않으면 locating이다.

information_status와 혼동하지 않는다. **position_status는 좌표의 나이, information_status는 통과 기록의 나이**를 본다. 정거장 사이를 정상 주행하는 동안 좌표는 계속 갱신되지만 통과 기록은 구간 소요시간만큼 늙으므로, `position_status = current`이면서 `information_status = stale`인 상태가 정상적으로 발생한다. 수신 직후 좌표 한 점만으로 복구 완료를 확정하지 않는다. 상세 자동 복구 판정은 개선사항 1순위로 확인 대기 중이다.

유효 이벤트가 없는 방문의 `visit_status`는 **방문의 기준 시각**으로 `upcoming`과 `unknown`을 가른다. 기준 시각은 그 방문의 공시 시각 중 가장 늦은 값이고, 공시 시각이 없는 방문(경유)은 뒤 방문 중 첫 공시 시각을 상한으로 쓴다. 기준 시각이 서버 시각 이후이거나 없으면 `upcoming`, 지났으면 `unknown`이다. 지났다고 `passed`로 확정하지 않는다 (`02` 8장).

last_observation은 `event_id, trip_stop_id, stop_id, stop_name, stop_sequence, event_type, occurred_at, time_confidence`를 포함한다. 지연 보충으로 현재 진행 위치를 뒤로 옮기지 않는다. 사건이 없는 위치에 가짜 관측을 만들지 않는다.

## 5. visits[] — 방문별 예측과 근거

| 필드 | 의미 |
|---|---|
| trip_stop_id, visit_status | 방문 식별·02의 진행 상태 |
| estimated_event_at | 예측 시각 또는 null |
| target_event_type | arrived / departed / passed 또는 null |
| prediction_basis | scheduled_departure / observed_event / interpolated_event 또는 null |
| basis_observation | 대상별 계산 근거. 관측 없는 경우 null. last_observation과 같은 필드 구조 |
| unavailable_reason | 예측을 제공하지 못하는 이유 또는 null |

응답에는 **근거를 `basis_observation` 하나로만 싣는다.** 이전의 `basis_event_id`·`basis_observed_at`은 이 객체의 `event_id`·`occurred_at`과 같은 값이라 세 곳에 두면 어긋날 수 있었다. 두 열은 `eta_predictions` 이력에 남아 있으며(`08` 7장) 응답은 그 ID로 객체를 구성한다.

`prediction_basis`는 실제로 선택한 계산 근거를 나타낸다. 관측 근거이면 `basis_observation`의 신뢰도와 일치해야 한다. 관측 객체가 null인 것만으로 시간표 근거를 확정하지 않는다.

| `prediction_basis` | 등가 조건 |
|---|---|
| scheduled_departure | 확인된 기점 공시 출발을 계산 근거로 선택했고 `basis_observation = null` |
| observed_event | `basis_observation.time_confidence = observed` |
| interpolated_event | `basis_observation.time_confidence = interpolated` |

근거를 선택하지 못하면 prediction_basis와 basis_observation 모두 null이다. 특히 no_observation을 시간표 기준으로 표시하지 않는다. 관측 근거의 종류가 모순되면 basis_observation을 기준으로 정정한다. null 객체만으로 scheduled_departure를 추론하지 않는다.

사유: no_observation, missing_baseline, stale_observation, prediction_expired, already_passed, trip_completed, trip_cancelled, awaiting_departure, position_unverified, event_confirmed.

event_confirmed는 목표 도착 등 해당 사건이 이미 관측되었다는 뜻이다. 미래 ETA 대신 확인 시각을 표시한다. 같은 방문의 이후 출발 예측은 별도 사건으로 계산할 수 있다.

예측이 없으면 estimated_event_at은 null이다. 과거 예측의 근거를 유지할 수 있지만 지금도 유효한 예측처럼 표시하지 않는다. 차량의 마지막 관측과 다른 근거를 사용했다면 대상별 근거를 표시한다.

## 6. 표시 결정 — 우선순위

회차 상세와 선택 차량의 상태를 함께 판단한다. 학생에게 내부 오류 코드나 ‘GPS 오류·서버 끊김’을 그대로 노출하지 않는다.

| 순서 | 조건 | 주 표시 |
|---|---|---|
| 1 | 회차 또는 선택 차량 cancelled | 이번 운행 취소 + 사유 |
| 2 | 선택 차량 completed | 이번 운행 종료. 종점 arrived 이력이 있어도 출발 미확인으로 표시하지 않음 |
| 3 | 날짜 schedule_status ≠ available | unknown: 시간표 확인 필요 / no_service: 오늘 운행 없음 / out_of_period: 적용 기간 밖 |
| 4 | 선택 방문 departed·passed·passed_inferred | 이번 방문 지남. 추론 기록은 실제 시각 미확인으로 구분 |
| 5 | 선택 방문 arrived | 도착 기록과 시각 표시. 신선하면 도착 확인·출발 미확인, 오래됐으면 현재 승차 여부 확인 필요. **같은 방문의 departed 예측이 있으면 예상 출발을 보조로 함께 표시** |
| 6 | 위치 재확인 또는 position_unverified | 위치 확인 중. 검증되지 않은 현재 위치·ETA를 표시하지 않음 |
| 7 | stale_observation 또는 prediction_expired | 최신 도착 정보 확인 중. 공시 시각이 있으면 시간표를 보조 표시 |
| 8 | awaiting_departure | 출발 확인 중. 이전의 도착 기록은 유지 |
| 9 | 유효 estimated_event_at | 목표 사건에 맞춰 예상 도착 / 예상 출발 / 예상 통과 |
| 10 | 공시 시각만 있음 | 시간표 시각. unspecified는 도착·출발로 단정하지 않음 |
| 11 | 그 외 | 예상 시각 확인 필요 + 필요한 보조 설명 |

5단계의 보조 표시가 필요한 이유는 정거장에 서 있는 학생에게 가장 중요한 정보가 "언제 떠나는가"이기 때문이다. 08은 같은 방문의 arrived 관측으로 departed를 예측하는 것을 허용하므로 값은 이미 계산되어 있다. 그 방문에 `target_event_type = departed`인 유효 예측이 있으면 도착 줄 아래에 예상 출발을 덧붙인다. 예측이 없거나 `awaiting_departure`이면 덧붙이지 않고 '출발 미확인'을 유지한다. **보조 표시가 주 표시를 대체하지 않으며 도착 기록을 지우지 않는다.**

지난 기록 표시와 위치 상태 배지는 독립이다. 현재 차량이 locating이면 과거 도착·통과 기록을 보더라도 차량 위치 영역에는 ‘위치 확인 중’을 표시한다. 날짜 조회처럼 선택 차량이 없는 화면은 날짜 상태부터 판단한다.

운행 완료는 실제 종료 결정이다. 예측 만료는 예상 시각을 넘겼지만 관측이 없는 경우이며 운행 종료나 정거장 통과의 증거가 아니다. 공시 시각이 있다고 만료 안내를 숨기지 않는다.

## 7. 근거 문구

`formatBasisLabel(visit, serverTime)`은 visit.basis_observation을 사용한다. 시간표 근거이면 ‘시간표 기준’, observed이면 ‘N분 전 · B 통과 확인’, interpolated이면 ‘N분 전 · B 부근 자동 추정’으로 표시한다. 사건 종류는 실제 계산 근거의 event_type을 따른다.

숫자만 강조하지 않고 근거·예상 시각·공시 참고 시각을 구분한다. 남은 시간은 estimated_event_at−현재 서버 시각 추정으로 표시하며 음수가 되면 0분으로 고정하지 않는다. 응답 이후 경과 시간은 단조 시계로 갱신하고 화면 복귀 시 재조회한다.

## 8. GPS 복구 표시 범위

학생 표시 방향은 ‘위치 확인 중 → 검증 후 정상 갱신’으로 확정한다. 별도 복구 완료 알림은 기본적으로 없다. 마지막 좌표에는 측정 시각을 남기며 관측되지 않은 이동을 만들지 않는다.

학교 문의 결과 공식화된 경로 자료를 확보하지 못했다. 실제 경로·우회·방향·단말 저장 여부는 사용자가 업체 문의 또는 현장 확인으로 확보하는 것으로 [개선사항 1순위](IMPROVEMENTS.md)에서 방침이 확정되었다. 방침 확정과 자료 등록은 다르므로 자동 복구·누락 방문 판정은 자료가 들어온 뒤 활성화한다. 현재 설계에서 detection_missed는 공개 방문 상태로 사용하지 않는다.

## 9. 버전·조회

`GET /api/v1/scheduled-trips/{trip_id}/state`와 trip:state는 위 구조가 같다. 모든 차량과 방문은 한 확정 버전으로 제공한다. 버전이 낮은 응답으로 되돌리지 않고, 동일 버전의 캐시 복원은 동일 본문을 복사한다. server_time만 전송 시점의 메타데이터다.

**구현 (P4, 2026-09-15):** `/state`는 확정 스냅샷의 버전만 돌려준다. 시간 경과로 내용이 바뀌면(공시 출발 경과로 `prediction_expired`, 관측 `stale` 등) 조회 시점 또는 30초 주기 확정 작업이 새 `state_version`으로 확정하고 `trip:state`를 보낸다. 같은 버전 번호로 다른 내용을 돌려주지 않는다 (`12` 10장).

시간 경과에 따른 만료는 서버의 정상 상태 변경으로 새 버전을 생성한다. 갱신 전달이 지연되어도 화면은 이미 지난 ETA를 실시간 값으로 계속 보여주지 않는다. 재연결·선택 변경의 조회·버퍼 규칙은 12를 따른다.

## 10. 검증 기준

| ID | 사례 | 기대 결과 |
|---|---|---|
| FR-ST-01 | 두 차량 중 한 차량만 B 통과 | 공통 stops 유지, 다른 차량의 B 방문 표시 가능 |
| FR-ST-02 | REST와 실시간 상태 | 동일 계약·동일 버전 본문 |
| FR-ST-03 | 지난 방문 기본 목록 | 숨김 가능, 과거 기록·마지막 확인 정보는 보존 |
| FR-ST-04 | 완료 차량 종점 arrived | 운행 종료 우선 |
| FR-ST-05 | ETA 만료·공시 시각 존재 | 만료 안내 + 시간표 보조 표시 |
| FR-ST-06 | 대상별 근거와 차량 마지막 기록이 다름 | 실제 basis_observation의 문구 표시 |
| FR-ST-07 | 위치 검증 중 | 위치 확인 중, 좌표 복구만으로 방문 자동 확정 금지 |
| FR-ST-08 | 데이터 미확보 | 운행 없음으로 단정 금지 |
| FR-ST-09 | 도착한 방문에 departed 예측 존재 | 도착 기록 + 예상 출발 보조 표시 |
| FR-ST-10 | 도착했으나 awaiting_departure | 보조 표시 없이 출발 미확인 유지 |
| FR-ST-11 | 좌표는 신선하고 통과 기록은 오래됨 | position_status=current, information_status=stale 동시 성립 |

### v7.4 추가 검증 기준

| ID | 사례 | 기대 결과 |
|---|---|---|
| FR-ST-12 | 관측과 기점 시각 모두 없음 | prediction_basis=null, basis_observation=null, 시간표 기준 문구 없음 |
| FR-ST-13 | 기점 공시 출발을 계산 근거로 선택 | scheduled_departure와 null 관측 객체, 시간표 기준 표시 |
