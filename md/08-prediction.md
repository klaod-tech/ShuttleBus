# 08 · 예측

> 회차 기점의 정시 출발과 유효 관측을 기준으로 방문별 도착·출발·통과 시각을 예측한다.
> 참조: [관측](02-observation-contract.md) · [공개 상태](03-state-contract.md) · [통계](09-travel-statistics.md)

## 1. 전제와 계산 기준

모든 회차는 학교·외부 정거장 여부와 무관하게 지정 기점에서 공시 시각에 정시 출발한다는 사용자 운영 전제를 적용한다. 기점 또는 출발 시각이 미확정이면 생성·예측에 임의 값을 넣지 않는다.

중간 방문의 도착·통과·재출발에는 정시 전제를 적용하지 않는다. 학교→터미널→학교가 한 회차라면 터미널 출발로 지연을 초기화하지 않는다. 터미널→학교가 별도 회차라면 그 회차의 기점 출발 시각을 초기 기준으로 삼는다. 정시 전제는 실제 departed 이벤트가 아니다.

관측 없는 초기 근거는 기점 공시 출발, 관측 후 근거는 같은 차량의 valid observed 또는 valid interpolated다. inferred/skipped·needs_review·cancelled는 시각 근거로 쓰지 않는다.

## 2. 구간과 사건 종류

노드는 `(route_stop_id, event_type)`이다. ‘사건’은 arrived·departed·passed를 뜻한다. 날짜별 trip_stop_id는 해당 경로 버전의 route_stop_id로 연결한다.

```text
A arrived → A departed → B arrived
   정차         이동
```

A 도착 시각에 A departed→B arrived 소요시간만 더하면 정차 시간이 빠진다. A arrived→B arrived 통계 또는 A arrived→A departed 정차 구간과 A departed→B arrived 이동 구간이 필요하다. 시작·끝 사건 종류가 같은 노드에서 이어져야 한다. 도착을 출발로 이름만 바꿔 연결하지 않는다.

## 3. 소요시간 적용 시간대(time_band)

`time_bands(time_band_id, route_id, effective_day_type, band_code, start_second, end_second)`로 정의한다. 05의 적용 day_type은 weekday/saturday/sunday_holiday다. 10/05는 실제 월요일이어도 sunday_holiday로 분류한다.

각 `(route_id, effective_day_type)` 집합은 `[0,86400)`을 겹침·공백 없이 덮는다. 시간대는 `[start_second,end_second)`이며 자정에 걸친 범위는 둘로 나눈다. 서울 현지 시각을 사용한다. 자정 이후에도 회차의 적용 day_type은 유지한다.

평일 천안역은 아침 08:00~09:00, 저녁 17:30~19:30, 천안터미널은 아침 08:00~09:00, 저녁 16:30~19:30을 초기 공지 기반 구분으로 사용한다. 그 외 offpeak, 휴일은 초기 전일 밴드다. 경계 19:30은 offpeak다. 밴드는 공시 시각을 변경하는 공식이 아니라 사용할 통계를 선택하는 기준이다.

## 4. 계산식과 경로 선택

```text
T(start) = 기점 공시 출발 시각 또는 선택 관측의 occurred_at
각 edge에 대해:
    band = resolve_time_band(route_id, effective_day_type, T(edge.from))
    μ = travel_times의 선택 구간·사건 종류·band·활성 모델의 stats_model_version 평균 초
        (baseline_source = estimate 및 travel_time_invalidations에 등록된 행은 선택 대상에서 제외)
    T(edge.to) = T(edge.from) + μ
estimated_event_at = T(target)
```

첫 구간부터 마지막 구간까지 앞 종료 노드와 다음 시작 노드가 일치해야 한다. 방문 순서는 증가하며 동일 방문에서는 arrived→departed만 연결할 수 있다. 기점→종점 전체 구간과 그 안의 하위 구간을 동시에 더하지 않는다. 직접 전체 구간 통계가 있으면 중간 시각이 없어도 해당 끝점 예측은 가능하지만 중간 지점에 시간을 균등 분배하지 않는다.

활성 모델은 `prediction_models(path_model_version, stats_model_version, status, activated_at, auto_promotion_blocked)`과 `prediction_path_edges(path_model_version, route_version_id, from_node, target_node, edge_order, edge_from, edge_to)`로 사용할 경로를 하나로 고정한다. 새 모델의 필요한 경로·밴드·통계를 검사한 뒤 활성화한다. 단순히 부분 갱신된 최신 행들을 섞지 않는다. 경로가 없거나 적용 시간대의 구간값이 없으면 missing_baseline이다.

### 두 버전을 구분한다

| 버전 | 무엇이 바뀌면 올리나 | 소유 |
|---|---|---|
| `path_model_version` | 사건 연결 경로 구성이 바뀜 | 08 |
| `stats_model_version` | 계산 방식·표본 구성·통계값이 바뀜 (`travel_times` 스냅샷) | 09 |

**하나의 이름으로 둘을 세지 않는다.** 통계 재계산으로 올라간 버전을 경로 모델 버전으로 조회하면 일치하는 `travel_times` 행이 사라져 전 구간이 missing_baseline이 된다.

활성 `prediction_models` 행이 **자기 안에 두 버전을 모두 못 박는다.** 08은 이 행만 읽으면 되고 09의 현재 상태를 조회하지 않는다. 09는 여전히 예측을 모른다 (`09` 서두).

`status`는 `draft` / `validating` / `active` / `retired`다. `active`는 동시에 하나이며 부분 유일 인덱스로 강제한다. 검사에 통과하지 않은 모델을 `active`로 올리지 않는다. 완전한 통계 스냅샷을 검증한 뒤 이전 모델의 retired 전환과 새 모델의 active 전환을 한 트랜잭션으로 확정한다. 계산 한 번은 선택한 두 버전을 끝까지 유지하고, 활성화 후 영향 회차는 8장의 정상 갱신 경로로 재계산한다.

### 승격 — 누가 언제 활성화하나

새 통계 스냅샷이 생겨도 활성화되기 전에는 공개 예측에 반영되지 않는다 (`09` 4장). **승격 주체가 없으면 표본이 매일 쌓여도 화면 값은 첫 스냅샷에 고정된다.** 표본 추가·취소만으로도 새 버전이 발급되므로 사람이 매번 누르는 방식은 유지되지 않는다.

통계만 바뀐 경우는 **자동 승격한다.** 세 조건을 모두 만족할 때만이다.

| 게이트 | 내용 |
|---|---|
| 경로 불변 | `path_model_version`이 현재 활성 모델과 같다 |
| 스냅샷 완전 | `09` 9장의 완전 스냅샷 조건을 통과했다 |
| **커버리지 비퇴행** | 새 스냅샷에서 실제로 고를 수 있는 `(구간, 사건 종류 쌍, 밴드)` 집합이 현재 활성 스냅샷의 집합을 **모두 포함한다** |

세 번째가 핵심이다. `09` 9장은 표본이 모두 취소된 구간을 새 버전에서 제외하므로, 오입력 몇 건을 취소하면 구간이 사라질 수 있다. 그대로 승격하면 **어제까지 제공하던 ETA가 오늘 missing_baseline이 된다.**

두 가지를 정확히 해둔다. 표본 취소·무효화는 아래의 즉시 사용 차단 규칙을 먼저 적용하며, 커버리지 유지 때문에 무효 통계를 계속 사용하지 않는다.

- 비교 대상은 **`baseline_source = estimate`를 제외한 뒤의 집합**이다. 아래 선택 규칙이 estimate를 고르지 않으므로, 포함해서 세면 실제로는 ETA가 불가능한 구간을 '커버됨'으로 집계해 게이트가 무력해진다.
- **개수가 아니라 포함 관계**로 판정한다. 한 구간이 빠지고 다른 구간이 들어오면 개수는 같지만 빠진 쪽의 ETA가 사라진다.

하나라도 걸리면 승격하지 않고 `13` 8장의 보류 목록에 올린다.

### 후보 모델은 누가 만드나

게이트는 평가할 후보 행이 있다는 것을 전제한다. **통계 배치가 새 스냅샷을 확정하면 08이 이어서 후보 행을 만든다** — `path_model_version`은 현재 활성값을 그대로 쓰고 `stats_model_version`만 새 값으로 채운 `draft` 행이다. 그 행에 게이트를 적용하고 통과하면 `active`로 올린다.

09는 스냅샷만 만들고 활성화를 판단하지 않으므로(`09` 9장), 이 생성 주체를 정하지 않으면 아무도 후보를 만들지 않는다.

하루에 스냅샷이 여럿 쌓이면 최신 완전 스냅샷 하나를 검사한다. 자동 재적용이 차단된 스냅샷이면 보류하고 오래된 중간 버전을 자동 선택하지 않는다. 같은 (path_model_version, stats_model_version) 후보는 멱등 생성한다.

`path_model_version`이 바뀐 모델은 자동 승격 대상이 아니다. 경로 구성 변경은 운영자의 의도적 작업이므로 명시적 활성화를 요구한다.

일반 통계 개선의 자동 승격은 재계산 배치의 마지막 단계이며 **운행 종료 후에 돈다** (`14` 3장). 운행 시간대에 승격하면 진행 중인 회차의 ETA가 재계산되어(8장) 학생 화면의 값이 지연과 무관하게 점프한다.

`auto_promote_enabled`가 거짓이면 모든 승격을 보류 목록으로 보낸다. 의심스러운 기간에 자동 경로를 끄고 수동으로 되돌리는 스위치다.

### 되돌리기

이전 스냅샷과 모델 행은 보존된다. 다만 롤백 대상도 현재의 표본 무효화·자료 완전성 검사를 다시 통과해야 한다. 통과한 이전 모델을 active로 전환한다. 재계산이나 통계 복원이 필요 없다. 전환은 이전 행의 retired 해제와 현재 행의 retired 전환을 한 트랜잭션으로 처리하고, 영향 회차는 8장의 정상 갱신 경로로 재계산한다.

승격·롤백과 차단 해제는 아래의 model_decisions에 이전·대상 모델, 결정자·시각·사유·게이트 결과를 추가 기록한다. 기존 이력을 덮지 않는다. 자동으로 바뀌더라도 **"언제부터 왜 예측이 달라졌는가"를 추적할 수 있어야 한다.**

`travel_times`에서 값을 고를 때 **`baseline_source = estimate` 행은 제외한다.** 균등 분배 추정을 공개 예측에 쓰지 않기 위한 규칙이며(`09` 3장), 금지를 실제로 강제하는 곳은 이 선택 단계다. 제외 후 남는 행이 없으면 missing_baseline이다.

기준 후보는 대상보다 앞선 진행 위치의 유효 관측을 방문 순서 내림차순, 같은 방문의 사건 전이 순서, occurred_at 내림차순, event_id 순으로 검토한다. 동일 방문 arrived 관측으로 departed를 예측하는 경우는 허용한다. 타깃까지 사건이 연결되는 경로가 있는 최신 근거를 선택하고 사용한 basis_event_id를 기록한다. 지연 보충 기록의 수신 순서로 현재 진행을 뒤로 옮기지 않는다.

새로운 유효 관측이 있으면 기점 시간표로 돌아가 지연을 없애지 않는다. 최신 근거에서 필요한 경로가 없으면 missing_baseline이며, 더 오래된 연결 가능한 관측을 선택하려면 최신 관측의 사건·시간과 모순되지 않는지도 검증한다. 최신 관측과 충돌하거나 이미 뒤처진 추정이면 제공하지 않는다.

## 5. 숫자 예시와 목표 사건

가상 예시: A departed→B passed 6분, B passed→C passed 4분, C passed→D arrived 5분.

| 근거 | C 예측 | D 예측 |
|---|---|---|
| A 08:00 정시 출발 | 08:10 통과 | 08:15 도착 |
| B 실제 08:09 통과 | 08:13 통과 | 08:18 도착 |
| C 실제 08:12 통과 | 이미 관측됨 | 08:17 도착 |

초기 지연을 구간마다 반복해 더하지 않는다. 목표 사건은 기점 departed, 종점 arrived, 중간은 선택 경로의 끝 사건이다. 통과 통계를 도착 정확도로 발표하지 않는다. 예측 가능한 사건이 없으면 target_event_type은 null이다.

## 6. 예측을 제공하지 않는 조건

| 조건 | unavailable_reason |
|---|---|
| 회차·차량 취소 | trip_cancelled |
| 차량 완료 | trip_completed |
| 목표 방문 이미 출발·통과 | already_passed |
| 목표 사건 자체가 이미 유효 관측으로 확인됨 | event_confirmed |
| 위치 근거를 재검증해야 함 | position_unverified |
| 유효 관측 없음·기점 기준 없음 | no_observation |
| 사건 연결 경로·사용 가능한 구간 통계 없음(무효화 차단 포함) | missing_baseline |
| 근거의 신선도 유효기간 초과 | stale_observation |
| 계속 정차 중인데 출발을 알 수 없음 | awaiting_departure |
| 예상 시각이 지남·실제 사건 미확인 | prediction_expired |

**위 표는 우선순위 내림차순이다.** 여러 조건이 동시에 성립하면 먼저 걸리는 사유 하나를 반환한다. `unavailable_reason`이 단수 필드이므로 순서를 정하지 않으면 구현마다 다른 값이 나온다.

모든 경우 estimated_event_at=null과 사유를 반환하고 공시 시각은 유지한다. 화면 문구는 03을 적용한다.

근거 신선도는 마지막 사용 관측과 `observation_grace_seconds`로 판정한다. **2400초는 시험값이며 최종 운영값이 아니다.** 이 값은 마지막 사용 관측의 나이를 재며 GPS 좌표의 나이와 구분한다. 04에는 천안터미널 편도 40분 공시 구간이 있으므로 2400초는 그 시간과 같고 추가 교통 지연·관측 누락에 대한 여유가 없다. 정상 운행 중에도 마지막 사용 관측이 만료될 수 있다. 구간별 관측 간격과 지연 분포를 실측한 뒤 최종값을 정하며 현재 숫자를 임의로 늘리지 않는다.

값이 설정되지 않은 상태에서는 실시간 예측을 유효하다고 확정하지 않고 확인 필요로 처리한다. 공개 ETA의 유효기간과 지연 입력 허용기간은 별개이며, GPS 좌표의 만료(`gps_stale_after_seconds`, `07` 6장)와도 별개다. **세 값을 서로 대신 쓰지 않는다.**

계속 정차 중이라는 새 증거가 있거나 도착 후 정차 포함 예측이 이미 지났다면, departed 관측 없이 예상 출발을 현재 시각으로 밀어내지 않는다. 초기 모델은 awaiting_departure로 보류한다. 잔여 정차시간 확률 모델은 후속이며 단순 평균에서 경과 시간을 빼 0으로 자르는 방식은 쓰지 않는다.

GPS 복구·노선상 누락 방문 재판별 조건은 개선사항 1순위의 자료 등록 대기다. 자료 확보 방법은 사용자 직접 확인으로 확정되었다. 검증되지 않은 복구 좌표로 예측 근거를 자동 생성하지 않는다. 이미 유효성이 확보된 수동 기록 기반 계산은 이 확인과 독립적으로 적용할 수 있다.

## 7. 공시 시각과 예측 이력

공시 시각은 통계로 덮어쓰지 않는다. 관측 없는 예측도 구간 통계에 따라 중간 공시 시각과 다를 수 있으므로 ‘시간표 기반 예측’과 ‘공시 시간표’를 구분한다. 평일 천안역 순1 학교 기점은 07:40, 천안역 공시값은 08:15로 보존한다.

`eta_predictions(prediction_id, trip_vehicle_id, trip_stop_id, predicted_at, estimated_event_at, target_event_type, prediction_basis, basis_event_id, basis_observed_at, path_model_version, stats_model_version, state_version, unavailable_reason)`를 영속 이력으로 둔다. 대상별 basis_observation은 저장하지 않고 응답 생성 시 `basis_event_id`로 구성한다. `basis_observed_at`은 계산 당시 값의 스냅샷이므로 근거가 나중에 취소되어도 남는다. 관측 취소 후 과거 예측 이력을 삭제하지 않고 근거 취소를 별도 표시한다.

## 8. 계산·갱신 시점

회차 생성, 유효 관측·취소·검토 결정, 근거·예측 만료, 활성 통계 모델 변경, 운행 완료·취소 시 계산한다. 회차 잠금 아래 상태·예측·state_version·outbox를 한 트랜잭션으로 확정한다. 같은 요청 재전송은 새 이력을 만들지 않는다. 캐시 복원은 확정 상태 복사만 수행한다.

## 9. 함수

| 함수 | 역할 |
|---|---|
| find_prediction_basis(trip_vehicle_id, target_node) | 유효하고 사건 종류가 연결되는 대상별 근거 선택 |
| resolve_prediction_path(route_version_id, basis_node, target_node, path_model_version) | 모델에 지정된 중복 없는 경로 |
| resolve_time_band(route_id, effective_day_type, entry_at) | 구간 진입 시각의 시간대 선택 |
| calculate_predictions(trip_vehicle_id) | 방문별 계산·사유 구성 |
| sum_segment_times(basis_at, edges, effective_day_type, stats_model_version) | 구간별 진입 시각을 갱신하며 합산. estimate 제외 |
| get_scheduled_stop_times(trip_stop_id) | 공시 원문 시각 |
| expire_predictions(now) | 만료를 정상 버전 변경으로 확정 |
| evaluate_promotion_gates(candidate_model) | 경로 불변·스냅샷 완전·커버리지 비퇴행 검사 |
| promote_prediction_model(candidate_model) | 게이트 통과 시 활성 전환. 실패는 보류 목록 |
| rollback_prediction_model(target_model) | 이전 활성 모델로 복구. 재계산 없이 전환 |

## 10. 검증 기준

| ID | 사례 | 기대 결과 |
|---|---|---|
| FR-PR-01 | 학교 또는 외부 기점 | 공시 정시 출발 기준, 가짜 실측 없음 |
| FR-PR-02 | B 08:09, C 08:12 가상 예시 | D 08:18→08:17 갱신 |
| FR-PR-03 | arrived 기준·departed 시작 통계만 존재 | 정차 누락 계산 금지 |
| FR-PR-04 | inferred 관측 | 시각 근거로 사용 금지 |
| FR-PR-05 | 천안역 순1 | 공시 07:40·08:15 보존 |
| FR-PR-06 | 구간이 시간대 경계를 넘음 | 매 구간 진입 시각으로 밴드 선택 |
| FR-PR-07 | 19:30 / 10/05 | offpeak / sunday_holiday 각각 올바른 그룹 |
| FR-PR-08 | 중간 관측 뒤 외부역 공시 출발 시각 도래 | 같은 회차 지연을 0으로 초기화하지 않음 |
| FR-PR-09 | 통계 없음·만료 | null과 사유, 0분 반복 없음 |
| FR-PR-10 | 캐시 복원 | 새 예측 이력·버전 생성 없음 |
| FR-PR-11 | 근거 취소 | 상태 재계산, 과거 이력 보존 |
| FR-PR-12 | 모델 일부 데이터만 준비 | 활성화 금지·혼합 버전 계산 없음 |
| FR-PR-13 | 통계 계산 방식만 변경 | `stats_model_version`만 증가, 활성 경로 모델은 불변 |
| FR-PR-14 | 해당 구간에 estimate 행만 존재 | 선택 제외 후 missing_baseline, 공개 ETA 없음 |
| FR-PR-15 | `active` 모델 중복 활성화 시도 | 부분 유일 인덱스로 거절 |

### 추가 검증 기준 — 근거와 스냅샷

| ID | 사례 | 기대 결과 |
|---|---|---|
| FR-PR-16 | 표본만 변경한 새 통계 버전 생성 | 활성화 전 기존 값 유지, 검증·활성화 후 정상 상태 갱신 |
| FR-PR-17 | 유효 관측과 기점 공시 출발 모두 없음 | prediction_basis와 basis_event_id, basis_observed_at은 null, no_observation |
| FR-PR-18 | 40분 구간에서 추가 지연으로 근거 나이 2400초 초과 | stale_observation으로 보류, 통과·운행 완료 자동 생성 없음 |
| FR-PR-19 | 표본만 늘어난 새 스냅샷 | 자동 승격, 다음 계산부터 새 평균 사용 |
| FR-PR-20 | 취소로 한 구간이 새 스냅샷에서 사라짐 | 기존의 해당 통계 즉시 사용 차단, 해당 ETA 보류, 모델 승격 보류 목록 등재 |
| FR-PR-21 | `path_model_version`이 다른 후보 | 자동 승격 없음, 명시적 활성화 요구 |
| FR-PR-22 | `auto_promote_enabled = false` | 게이트 통과해도 보류 목록으로만 |
| FR-PR-23 | 승격 후 롤백 | 대상 유효성 재검사 후 전환, 철회 통계 자동 재적용 차단·자동 승격 중지 |

prediction_basis는 03의 선택 근거 규칙을 따른다. 기점 공시 출발을 근거로 선택한 경우에만 scheduled_departure이며, 관측 객체가 없다는 이유만으로 이 값을 채우지 않는다. 근거를 선택하지 못하면 null이다. 과거 예측 근거를 유지하는 경우에도 현재 ETA의 유효성은 unavailable_reason으로 별도 판단한다.

## 11. 통계 무효화와 모델 재적용 방지

### 취소된 표본의 통계는 즉시 사용 중단

09의 travel_time_invalidations에 등록된 (stats_model_version, 구간 키)는 활성 모델이 참조하더라도 선택하지 않는다. 구간 키는 travel_times PK에서 stats_model_version을 제외한 열 전부다. 차단된 구간이 계산 경로에 있으면 estimated_event_at=null, unavailable_reason=missing_baseline이다. 전역 information_status를 GPS 장애로 바꾸지 않는다. 다른 유효 구간의 예측은 유지한다.

표본 하나가 취소·기각되어도 해당 표본을 사용한 모든 스냅샷의 행을 차단한다. 평균이 우연히 같거나 표본이 일부 남았다는 이유로 기존 평균을 사용하지 않는다. 완전한 새 스냅샷을 유효 표본으로 만든 뒤 검사한다. 정정 결과로 커버리지가 줄면 자동 승격은 보류하지만 무효 통계 차단은 유지한다. 운영자는 손실 구간을 확인하고 완전한 정정 스냅샷의 커버리지 감소만 명시적으로 승인할 수 있다. 불완전·무효 자료 검사는 수동 승인으로 우회하지 못한다.

통계 사용 차단과 영향 회차의 예측·state_version·outbox 갱신은 표본 취소 결정과 함께 확정한다. MVP는 통계 갱신 잠금 후 영향 회차를 ID순으로 잠가 한 트랜잭션에서 처리한다. 일반 모델 활성화도 같은 잠금 순서를 따른다. 영향 회차에는 원본 관측의 회차뿐 아니라 같은 통계로 미래 ETA를 제공하는 회차도 포함한다. 진행 중 운행이라도 차단은 야간 배치를 기다리지 않는다. 예전 캐시·DB 스냅샷을 최신 상태로 반환하지 않으며 캐시 버전이 뒤처지면 새 DB 확정 상태를 사용한다. 과거 예측 이력은 삭제하지 않는다.

### 롤백과 재검토

prediction_models에 auto_promotion_blocked(boolean, 기본 false)를 추가한다. 롤백은 철회한 모델과 같은 stats_model_version을 참조하는 모든 모델을 차단하고 auto_promote_enabled=false로 전환한다. 새 후보도 동일 통계 버전의 차단 이력을 상속하므로 새 행 생성으로 우회할 수 없다. auto_promote_enabled는 모든 실행자가 공유하는 런타임 설정 원본에서 변경하고 배치 시작·활성화 직전에 재확인한다.

차단 해제는 운영자가 원인·재검증 결과를 기록하고 명시적으로 요청할 때만 허용한다. 표본 무효화 차단은 이 요청으로 지울 수 없다. 새 통계 버전도 전역 자동 승격 재개를 명시하기 전에는 자동 적용하지 않는다. 롤백·차단·해제·자동 승격 재개는 공통 통계 갱신 잠금(모델 전환 잠금) 아래 처리한다. 재요청은 기존 결과를 반환하고, 결정 후 설정 전파가 실패하면 자동 승격을 중지 상태로 유지한다.

model_decisions(decision_id, from_path_model_version, from_stats_model_version, to_path_model_version, to_stats_model_version, action, actor_id nullable, decided_at, reason, gate_results, idempotency_key)로 결정 이력을 추가 보존한다. action은 promote / rollback / block / unblock / resume_auto이며 자동 배치의 actor_id는 null이다. 모델별 현재 상태와 결정 이력은 같은 트랜잭션에서 반영한다. 일반 스위치 설정은 14를 따른다.

| ID | 사례 | 기대 결과 |
|---|---|---|
| FR-PR-24 | 활성 통계에 포함된 표본 일부 취소 | 해당 행 즉시 선택 제외, 영향 ETA 보류, 나머지 유지 |
| FR-PR-25 | 취소 직후 오래된 캐시 조회 | 차단 전 ETA를 최신 상태로 반환하지 않음 |
| FR-PR-26 | 롤백 다음 배치·같은 통계 새 후보 생성 | 자동 재적용 없음, 차단 상속 |
| FR-PR-27 | 차단 해제만 요청, 자동 재개 미요청 | 자동 승격 계속 중지 |
| FR-PR-28 | 무효화된 표본 포함 모델로 롤백 | 차단 통계 재사용 없음 |
