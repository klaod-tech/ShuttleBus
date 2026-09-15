# 11 · 출발·도착 정거장별 탑승 후보

> 선택된 한 노선에서 출발 정거장에 탑승해 도착 정거장에서 하차할 수 있는 차량·방문 쌍을 찾는다.
> 참조: [정거장 선택](10-stop-discovery.md) · [상태 계약](03-state-contract.md)

## 1. 현재 범위

선택 노선 → 날짜 → 출발 정거장 → 도착 정거장 → 후보 목록.

출발 정거장은 학생이 탈 곳이며 현재 GPS 위치가 아니다. 도착 정거장은 내릴 곳이다. 전체 노선 페이지·노선명 검색·노선 간 통합 추천·환승 검색은 후순위다. 현재 화면은 설정된 노선 또는 진입 경로의 route_id를 받는다.

## 2. 후보 방문 쌍 구성

`find_boarding_candidates(route_id, service_date, origin_stop_id, destination_stop_id)`

같은 route_id·날짜의 실제 생성 회차만 검색하며 그 노선 안의 패턴은 포함한다. 같은 차량·회차에서 다음 조건을 만족하는 방문 쌍을 만든다.

```text
boarding_visit.stop_id = origin_stop_id
alighting_visit.stop_id = destination_stop_id
boarding_visit.stop_sequence < alighting_visit.stop_sequence
```

최소 하나의 중간 방문이 있어야 한다는 뜻은 아니다. 인접 방문도 가능하다. 물리 stop_id가 같더라도 서로 다른 방문이고 뒤에 다시 하차하는 유효 회차라면 허용하되 ‘같은 정거장으로 돌아오는 순환 탑승’이라고 명시한다. 같은 trip_stop_id를 승차·하차 양쪽에 쓰지 않는다.

서로 다른 회차를 연결하거나 현재 회차 이후의 다음 운행을 자동으로 이어 붙이지 않는다. 휴일 천안역의 천안아산역 두 방문은 다른 boarding_trip_stop_id다. 목적지보다 앞에 있는 방문만 후보로 남긴다. 목적지 전에 순환하는 구간이 있으면 도중 주요 정거장과 방문 순서를 함께 표시한다. 경로·도착 시각을 확인하지 않고 ‘최단·가장 빠름’이라고 표시하지 않는다.

## 3. 제외·확인 필요·추천 가능

1. schedule_status가 available이 아니면 HTTP 200으로 상태·사유와 빈 배열을 반환한다.
2. 회차 또는 차량이 completed/cancelled이면 제외한다.
3. 승차 방문 boarding_policy 또는 하차 방문 alighting_policy가 not_allowed이면 제외한다. 하나라도 unknown이면 확인 필요다.
4. 승차 방문이 departed/passed/passed_inferred이면 제외한다. 예상 시각 경과만으로 이미 지났다고 확정하지 않는다.
5. 승차 방문 arrived는 남겨 둔다. 신선한 도착 기록이며 양쪽 정책이 allowed이면 우선 후보다. 도착 관측이 `arrived_freshness_seconds`(**초기 180**)보다 오래됐으면 확인 필요다. 이 값은 "버스가 아직 그 정거장에 있다고 보아도 되는가"를 재므로 정차 시간 수준이며, 구간 소요시간을 재는 `observation_grace_seconds`(`08` 6장)와 자릿수가 다르다.
6. 그 외에는 승차 방문의 유효 미래 ETA를 사용한다. 그것이 없고 관측 만료·위치 재확인 등의 반대 근거가 없으면 확인된 공시 출발 또는 도착 시각을 시간표 후보로 쓴다. unspecified만 있으면 확인 필요다.
7. 만료·출발 미확인·위치 재확인으로 실시간 근거가 무효이면 미래 공시값이 있어도 확인 필요로 둔다. 목적지 ETA 부재만으로 유효 승차 후보를 제거하지 않고 ‘도착 예상 확인 필요’로 표시한다.

배열은 `candidates[]`, `unverified_candidates[]` 두 개다. 둘 다 학생에게 보여준다. 승하차 허용 확인과 매번 정차한다는 보장은 다르며 실제 승차 안내는 10을 따른다.

## 4. 정렬과 추천

추천 가능 후보 정렬 키:

```text
(priority_group, sort_at, trip_no, vehicle_slot,
 boarding_stop_sequence, alighting_stop_sequence,
 trip_vehicle_id, boarding_trip_stop_id, alighting_trip_stop_id)
```

group 0은 신선한 arrived이며 sort_at은 해당 도착 관측 시각, group 1은 유효 미래 시각이다. 서버가 정렬한다. 이는 승차 시점 우선 추천이며 목적지 최단 도착 보장이 아니다.

### sort_at은 어느 사건의 시각인가

먼저 정보 출처를 신선한 도착 관측 → 유효 미래 예측 → 확인된 공시 시각 순서로 선택한다. 신선한 arrived는 group 0이며 도착 관측 시각을 그대로 쓴다. 그 외 group 1은 유효 미래 예측이 있으면 이를 쓰고, 없을 때만 3장의 조건을 만족하는 공시 시각을 쓴다. 예측 후보와 시간표 후보 사이에는 별도 출처 정렬 그룹을 만들지 않고 선택한 sort_at으로 비교한다. 출발→도착→통과 우선순위는 선택한 정보 출처 안에서만 적용한다. 도착 관측을 공시 출발로 덮거나 유효 도착 예측보다 공시 출발을 먼저 고르지 않는다.

| 순위 | 사용할 시각 |
|---|---|
| 1 | 선택한 정보 출처 안의 departed 시각 |
| 2 | 같은 정보 출처에 departed가 없으면 arrived 시각 |
| 3 | 같은 정보 출처에 둘 다 없고 passed만 있으면 통과 시각 |

**한 목록 안에서 사건 종류가 섞이는 것 자체는 막을 수 없다.** 정차하는 정거장과 통과만 하는 정거장이 함께 나올 수 있기 때문이다. 대신 어느 사건을 썼는지를 `sort_basis_event_type`으로 응답에 실어 화면이 구분해 표시한다. `boarding_policy = unknown`인 경유 정거장은 대개 3순위가 되므로 확인 필요 목록에서 특히 이 표기가 필요하다.

`unspecified` 공시 시각은 사건 종류가 확정되지 않았으므로 sort_at으로 쓰지 않는다 (`03` 3장).

예: 현재 08:05, 공시 출발 08:10, 유효 도착 예측 08:20이면 sort_at은 08:20이고 sort_basis_event_type은 arrived다. 예측 만료·위치 재확인 등 반대 근거가 있으면 공시값으로 정상 추천을 되살리지 않고 확인 필요로 둔다. 신선한 arrived 후보는 예상 출발이 있어도 도착 관측 시각으로 정렬한다.

확인 필요 후보는 `(sort_at IS NULL, sort_at, trip_no, vehicle_slot, boarding_stop_sequence, alighting_stop_sequence, trip_vehicle_id, boarding_trip_stop_id, alighting_trip_stop_id)`로 정렬한다. sort_at은 해당 승차 방문의 도착 관측, 참고 예측, 의미가 확인된 공시 시각 순서로 선택하며 없으면 null이다. 같은 출처 안에서는 위 사건 우선순위를 적용하고 오래된 값은 참고용임을 표시한다. null은 마지막이다. 과거 시각은 참고값으로만 표시하고 곧 도착으로 바꾸지 않는다.

다른 방문의 기점 시각을 승차 정렬에 쓰지 않는다. 온양온천역 승차 기준 순2 08:45 → 순3 08:50이며 주은아파트 기점 08:40을 끌어오지 않는다.

추천은 candidates의 첫 항목이다. `recommended_candidate`는 `{trip_id, trip_vehicle_id, boarding_trip_stop_id, alighting_trip_stop_id}` 또는 null이다. 하차 방문도 포함해야 반복 방문 쌍이 모호하지 않다. 추천 변경으로 사용자의 선택을 자동 교체하지 않는다.

## 5. 갱신

선택 노선의 candidates:changed 또는 refresh_after_seconds(초기 30) 경과 시 재조회한다. 서버는 조회 시점의 신선도를 반영한다. 이벤트가 없어도 예상 시각 경과 시 확인 필요로 이동할 수 있다. 단순 시간 경과로 통과 이력을 만들지 않는다.

노선·날짜·출발·도착 변경 시 이전 후보·추천·선택 차량을 초기화하고 오래된 응답을 요청 ID로 폐기한다. 사용자가 선택한 후보가 통과하면 다음 후보 선택 버튼을 제공한다. 실제 선택 이동은 사용자 동작으로 수행한다.

## 6. 후보 없음

확인 필요 항목이 남아 있으면 ‘모든 버스 종료’라고 단정하지 않는다. `no_candidate_reason`은 no_remaining_service / no_matching_journey / schedule_unavailable로 구분한다. 경로 자체가 맞지 않는 출발·도착 쌍을 오늘 운행 종료라고 표시하지 않는다.

`next_known_service_date`는 같은 노선·승하차 쌍을 제공하는 다음 확인된 날짜이며 없으면 null이다. 중간 unknown 날짜를 건너뛰면 has_unknown_dates_before=true로 ‘다음 확인된 시간표’만 안내한다. 하차만 가능한 곳에서 출발하려는 경우 등 부적합 사유도 설명한다.

## 7. API·응답

기본 경로 /api/v1. `GET /scheduled-trips`는 route_id, service_date 필수다. origin_stop_id와 destination_stop_id를 둘 다 주면 후보 응답, 둘 다 생략하면 선택 노선의 날짜별 회차 목록이다. 하나만 보내면 422다. 후자의 응답은 trips[]이며 candidates[]와 혼용하지 않는다. 오래된 stop_id·direction 단일 정거장 검색 모드는 사용하지 않는다.

후보 응답: schedule_status, schedule_reason, server_time, candidates[], unverified_candidates[], recommended_candidate, refresh_after_seconds, no_candidate_reason(nullable), next_known_service_date, has_unknown_dates_before.

| 후보 필드 | 의미 |
|---|---|
| trip_id, trip_vehicle_id, vehicle_slot, trip_no, route_id, route_pattern_id | 차량·회차 식별 |
| boarding_trip_stop_id, alighting_trip_stop_id | 선택한 승차·하차 방문 |
| boarding_stop_sequence, alighting_stop_sequence | 회차 안의 순서 |
| boarding_stop, alighting_stop | 03 stops[] 항목 형식의 정적 정보 |
| boarding_visit, alighting_visit | 03 visits[] 항목 형식의 상태·ETA·대상별 근거 |
| route_segment_stop_names | 두 방문 사이 경로 순서. 미확정 경로는 확인 필요 표시 |
| origin_stop_name, origin_scheduled_departure_at | 회차 기점 참고 정보. 승차 정렬 시각과 구분 |
| priority_group, sort_at | 확인 필요는 priority_group=null, sort_at도 null 가능 |
| sort_basis_event_type | sort_at이 어느 사건의 시각인지. departed / arrived / passed 또는 null |
| is_same_stop_loop | 같은 물리 정거장으로 돌아오는 순환 탑승이면 true (2장) |
| unverified_reasons[] | 확인 필요 사유. 정상 후보는 빈 배열. 값은 아래 표 |
| scheduled_vehicle_count, tracked_vehicle_count | 예정·현재 실측 대수 |

### `unverified_reasons` 값

| 값 | 뜻 | 3장 |
|---|---|---|
| boarding_policy_unknown / alighting_policy_unknown | 승차·하차 정책 미확인 | 3 |
| arrival_observation_stale | 도착 관측이 `arrived_freshness_seconds`를 넘김 | 5 |
| stale_observation / prediction_expired / position_unverified / awaiting_departure | 실시간 근거 무효. 미래 공시값으로 정상 추천을 되살리지 않음 | 7 |
| scheduled_time_passed | 의미가 확인된 공시 시각이 지남. 참고 정렬만 | 4 |
| scheduled_event_type_unspecified | 공시 시각의 도착·출발 의미 미확정. `sort_at = null` | 4 |
| no_scheduled_time | 승차 방문에 공시 시각이 없음(경유). `sort_at = null` | 6 |

한 후보에 사유가 여럿이면 모두 싣는다. `next_known_service_date`는 추천 가능 후보가 없을 때만 계산하고 그 외에는 null이다.

### 회차 목록 모드 `trips[]`

`trip_id, trip_no, route_pattern_id, pattern_code, operation_status, scheduled_vehicle_count, origin_stop_name, origin_scheduled_departure_at, terminal_stop_name, terminal_scheduled_arrival_at, note, student_union_boarding`. 기점 공시 출발 순. `student_union_boarding`은 `10` 6장 판정이며 휴일·온양 노선은 확인 필요라 null이다. 시간표 메뉴(`md_frontend/01`)가 이 모드를 쓴다.

## 8. 프론트 상태

selectedRouteId, selectedServiceDate, originStopId, destinationStopId, candidates, unverifiedCandidates, recommendedCandidate, selectedCandidate, refreshAfterSeconds, activeRequestId.

selectedCandidate는 위 4개 식별자를 가진다. 슬롯 2개면 독립 후보이며, 같은 슬롯의 반복 승차 방문도 별도 후보다. 마커 한 개가 여러 방문에 해당해도 사용자가 순번을 입력하게 하지 않는다. 선택한 출발·도착을 서버가 방문 쌍으로 펼친다.

## 9. 함수

| 함수 | 역할 |
|---|---|
| find_boarding_candidates | 선택 노선·날짜·출발·도착의 후보 조회 |
| build_journey_visit_pairs | 동일 차량 회차의 순서가 맞는 승하차 방문 쌍 |
| classify_candidate_freshness | 신선도·승하차 정책·예측 사유 확인 |
| compute_sort_at | 승차 방문의 정보 출처를 먼저 선택하고 같은 출처 안에서 departed→arrived→passed 적용. 신선한 arrived는 도착 관측 유지 |
| loadScheduledTrips | 회차 목록 또는 양 정거장 후보 조회 |
| selectJourneyCandidate | 4개 ID의 후보 선택·회차 구독 |
| pickNextCandidate | 사용자 동작으로 다음 후보 선택 |

## 10. 검증 기준

| ID | 사례 | 기대 결과 |
|---|---|---|
| FR-BC-01 | 온양온천역 승차 | 순2 08:45→순3 08:50 |
| FR-BC-02 | 다른 기점 시각 | 승차 sort_at에 미사용 |
| FR-BC-03 | 목적지가 출발 방문보다 앞 | 해당 방문 쌍 제외 |
| FR-BC-04 | 특정 route_id 조회 | 다른 노선 후보 없음 |
| FR-BC-05 | 같은 정거장 반복 방문 | 순서에 맞는 서로 다른 4-ID 후보 |
| FR-BC-06 | 신선한 arrived | 제외하지 않음 |
| FR-BC-07 | 도착 관측이 신선도 초과 | 확인 필요, 자동 추천 없음 |
| FR-BC-08 | 하차 정책 not_allowed | 제외 |
| FR-BC-09 | 승차 또는 하차 unknown | 확인 필요 |
| FR-BC-10 | 2대 슬롯 | 독립 상태·후보 |
| FR-BC-11 | 날짜 unknown | 200+상태, 404 아님 |
| FR-BC-12 | 확인 필요 후보 있음 | 종료 단정 없음 |
| FR-BC-13 | 추천 갱신 | 사용자 선택 유지 |
| FR-BC-14 | null·동률 시각 | 결정적 정렬 |
| FR-BC-15 | 출발만 전달 | 422 |
| FR-BC-16 | 같은 물리 정거장 출발·도착 | 뒤의 별도 방문만 허용, 순환 안내 |
| FR-BC-17 | 신선한 arrived가 없고 선택한 같은 출처에 도착·출발 시각 모두 있음 | sort_at이 출발 시각, sort_basis_event_type=departed |
| FR-BC-18 | 통과만 하는 경유 정거장 | sort_basis_event_type=passed로 구분 표시 |
| FR-BC-19 | unspecified 공시 시각만 존재 | sort_at 미사용, 확인 필요 |

### v7.4 추가 검증 기준

| ID | 사례 | 기대 결과 |
|---|---|---|
| FR-BC-20 | 공시 출발 08:10, 유효 도착 예측 08:20 | sort_at=08:20, sort_basis_event_type=arrived |
| FR-BC-21 | 신선한 arrived와 미래 예상 출발 동시 존재 | group 0, 도착 관측으로 정렬, 예상 출발은 보조 표시 |
| FR-BC-22 | 실시간 근거 무효지만 미래 공시 시각 존재 | 확인 필요 유지, 공시값으로 정상 추천 복귀 없음 |
