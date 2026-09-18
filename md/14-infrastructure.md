# 14 · 인프라

> Docker와 Kubernetes를 단계적으로 적용한다. **개인 규모에 과하다는 것을 알고 선택한 학습 목표다.**
> 참조: [개요](00-overview.md)

기능 규칙은 해당 소유 문서를 참조하고 여기서는 배포 구성·설정·운영 실습을 정의한다. 기능별 파일 분리와 물리적 서비스 분리를 동일시하지 않는다.

**현재 구현 기준 (2026-09-18):** 아래 단계별 구성은 초기 설계다. 현재는 postgres·redis·api와 초기화 작업으로 구성되며 Socket.IO는 Python API 프로세스에 포함된다. 별도 Node.js realtime 서비스와 web은 아직 없다. 실제 연동은 [12 구현 메모](12-realtime-delivery.md)와 루트 docker-compose.yml을 따른다.

---

## 1. 왜 K8s인가

이 서비스는 노선 하나에 사용자 수백 명이다. Docker Compose로 충분하고, K8s는 관리 부담만 늘린다.

**그럼에도 쓰는 이유는 실무에서 쓰는 방식을 그대로 경험하기 위해서다.** 이 문서는 그 학습 항목을 정리한 것이며, 서비스 요구사항이 아니다.

정직하게 적어두면 나중에 "왜 이렇게 복잡하게 만들었나"를 다시 묻지 않게 된다.

## 2. 단계

### 1단계 — Docker Compose

한 백엔드로 시작한다. 서비스를 나누지 않는다.

| 컨테이너 | 역할 |
|---|---|
| `api` | FastAPI. 모든 API를 한 프로세스에서 |
| `web` | Next.js. 학생 화면과 입력자 화면 |
| `postgres` | 기준 데이터 |

입력 → 저장 → 예측 → 화면 갱신의 흐름을 여기서 먼저 검증한다. **Redis도 아직 없다.** 상태를 DB에서 직접 읽는다.

### 2단계 — Redis와 실시간

| 추가 | 역할 |
|---|---|
| `redis` | 상태 캐시 |
| `realtime` | Node.js + Socket.IO |

캐시 복원(`12` 5장)을 여기서 구현하고 시험한다. **Redis를 지워도 DB에서 복구되는지**가 이 단계의 합격 조건이다.

### 3단계 — 서비스 분리

기능 문서의 경계를 따라 나눈다.

| 서비스 | 대응 문서 |
|---|---|
| Schedule | `05` |
| Collection | `06` |
| Prediction | `08` |
| Statistics | `09` |
| Query | `10`, `11` |
| Realtime | `12` |
| Admin | `13` |

**분리는 마지막이다.** 경계가 문서로 확정된 뒤에 나눠야 나중에 되돌리지 않는다.

### 4단계 — Kubernetes

minikube에 올린다. **학습·시험 환경이며 실제 공개 운영 환경은 별도로 결정한다.**

## 3. K8s 리소스 매핑

| 리소스 | 적용 대상 | 학습 포인트 |
|---|---|---|
| `Deployment` | 모든 무상태 서비스 | 롤링 업데이트, 롤백 |
| `StatefulSet` | PostgreSQL | Pod 재시작 시 데이터 유지 |
| `PersistentVolume` | PostgreSQL 데이터 | 영속성 |
| `Service` (ClusterIP) | 서비스 간 통신 | 이름 기반 디스커버리 |
| `Ingress` | 외부 진입점 | 라우팅, HTTPS |
| `ConfigMap` | 시간대 설정, 여유 시간값 | 코드와 설정 분리 |
| `Secret` | DB 비밀번호, JWT 시크릿 | 저장소에서 제외 |
| `CronJob` | 회차 생성(`05`), 운행일 마감(`07`), 통계 갱신·모델 승격(`09`·`08`), 검토 판정(`13`) | 배치. 순서는 아래 |
| `Liveness Probe` | Socket.IO 서버 | 자동 재시작 |
| `Readiness Probe` | 캐시 복원 중 서비스 | 트래픽 차단 |
| `HorizontalPodAutoscaler` | Query 서비스 | 등교 시간대 스케일 — **실효성은 낮고 학습용** |

### 야간 배치 순서

```text
운행 종료
  ↓
1. 운행일 마감     service_day_closed로 열린 GPS 세션을 닫는다 (`07` 1장)
  ↓
2. 통계 재계산     종료된 세션의 완결 구간을 집계 (`09` 4장)
  ↓
3. 모델 승격 검사   게이트 통과 시 활성화 (`08` 4장)
```

**1을 2보다 먼저 돌린다.** `09` 4장은 종료된 세션만 집계한다. `terminal_boundary_min_points`가 미정인 동안 `terminal_departed`가 적용되지 않으므로(`07` 1장) 하루 마지막 회차 세션은 `service_day_closed`로만 닫힌다. 순서가 뒤바뀌면 그 세션의 표본이 하루씩 밀린다. 값을 정하면 저절로 해소되지만 순서 자체를 의존하지 않게 고정해 둔다.

3은 2가 완료된 뒤에만 돈다. 부분 갱신된 스냅샷을 검사하면 커버리지 게이트가 잘못 실패한다 (`08` 4장).

## 4. 설정과 비밀값

| 이름 | 종류 | 소유 문서 |
|---|---|---|
| `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET` | Secret | `01` |
| `ACCESS_TOKEN_TTL_SECONDS` | ConfigMap | `01` |
| `observation_grace_seconds` | ConfigMap | `08` |
| `auto_promote_enabled`, `auto_promotion_blocked` | **DB 런타임 설정** (초기값만 ConfigMap) | `08`·`14` |
| `arrived_freshness_seconds`, `refresh_after_seconds` | ConfigMap | `11` |
| `clock_skew_tolerance_seconds`, `pending_input_retention_hours` | ConfigMap | `02` |
| `session_review_grace_seconds` | ConfigMap | `13` |
| `max_skip_stops` | ConfigMap | `06` |
| GPS 관련 전체 (`07` 6장 표) | ConfigMap | `07` |
| `NEXT_PUBLIC_KAKAO_MAP_JS_KEY`, `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_SOCKET_URL` | 브라우저 공개 | `10` |

**서버 비밀값을 `NEXT_PUBLIC_` 변수에 넣지 않는다.** 브라우저용 카카오 키는 어차피 보이는 값이므로 도메인 등록으로 제한한다.

## 5. Probe와 가용성

### Readiness

캐시 복원 중에는 트래픽을 받지 않는다. 다만 **한 서비스의 Readiness가 다른 서비스까지 차단한다고 가정하지 않는다** (`12` 5장). 조회 경로가 자기 상태를 스스로 판단해 `503 CACHE_REBUILDING`을 반환할 수 있어야 한다.

### Liveness

Socket.IO 서버는 연결이 살아 있어도 이벤트 처리가 멈출 수 있다. **작업자 heartbeat와 처리 루프 응답**을 확인한다. 처리할 outbox가 없는 정상 대기는 장애가 아니다. 외부 DB·Redis 장애와 프로세스 정지를 구분하고 외부 장애만으로 무한 재시작하지 않는다. 대기 항목이 있는데 진행하지 않는 상황은 적체 지표·경고로 별도 감시한다.

### 가용성 목표

**Probe와 StatefulSet 설정만으로 가용성 목표를 통과했다고 판단하지 않는다** (`00` 5장). 외부에서 실제 요청을 보내 성공 여부로 측정한다.

## 6. 백업과 복구

세 가지를 구분해 시험한다.

| 시나리오 | 확인할 것 |
|---|---|
| Redis만 초기화 | 서비스 재시작 없이 DB에서 복원되는가 (`12`) |
| Pod 재시작 | PersistentVolume으로 데이터가 유지되는가 |
| DB 백업 복원 | 별도 백업에서 되살릴 수 있는가 |

**StatefulSet과 PV는 백업이 아니다.** Pod가 죽어도 데이터가 남는 것과, 데이터가 손상됐을 때 되살리는 것은 다른 문제다. 백업 복원을 별도로 실습한다.

## 7. 관찰

| 항목 | 목적 |
|---|---|
| 구조화 로그 | 요청 ID, 회차 ID, 이벤트 ID를 함께 남김 |
| 상태 변경 로그 | `state_version` 증가 시점과 원인 |
| outbox 적체 | 전송 실패 누적 감지 |
| CronJob 실행 결과 | 회차 생성 누락, 통계 갱신 실패 |
| 모델 승격 결과 | 게이트 통과·보류 사유, 활성 스냅샷 교체 시점 |
| 미검출률 (Phase 2) | 특정 정거장의 반복 미검출 (`07`) |

로그에 **`occurred_at`과 `received_at`을 함께** 남긴다. 지연 문제를 사후에 재구성하려면 둘 다 필요하다.

## 8. 로컬 개발

```
1단계 구성: postgres, api, web
2단계 구성: postgres, redis, api, realtime, web

각 단계의 Compose 구성으로 기동
  → 단일 초기화 작업으로 마이그레이션 적용
  → 멱등 시드 데이터 로드 (04 기준 데이터)
  → 의존 서비스 준비 후 API·화면 시작
```

시드는 **멱등**이어야 한다. 여러 번 실행해도 중복 등록되지 않는다.

개발 환경에서도 `Asia/Seoul` 판정을 쓴다. **서버 시간대에 의존하지 않는지**를 로컬에서 먼저 확인한다 (`05` 검증 기준).

## 9. 검증 기준

| ID | 요구사항 | 확인 방법 |
|---|---|---|
| FR-IN-01 | Compose로 전체 기동 | 단일 명령 후 화면 접근 |
| FR-IN-02 | 시드가 멱등 | 두 번 실행 후 행 수 불변 |
| FR-IN-03 | Redis 초기화 후 복원 | 서비스 재시작 없이 `FLUSHALL` |
| FR-IN-04 | Pod 재시작 후 데이터 유지 | PostgreSQL Pod 삭제 |
| FR-IN-05 | DB 백업 복원 | 별도 백업에서 복구 |
| FR-IN-06 | 롤링 업데이트 중 요청 성공 | 배포 중 외부 요청 |
| FR-IN-07 | 롤백 동작 | 이전 버전으로 되돌리기 |
| FR-IN-08 | Secret이 저장소에 없음 | 리포지토리 검사 |
| FR-IN-09 | 서버 시간대 비의존 | TZ 변경 후 날짜 판정 동일 |
| FR-IN-10 | CronJob 실패 후 보충 | 실행 건너뛴 뒤 다음 실행 |
| FR-IN-11 | 동시 접속 100명 | 명시한 시험 환경에서 |
| FR-IN-12 | 외부 요청 기준 가용성 측정 | Probe 상태가 아닌 실제 요청 |
| FR-IN-13 | 승격이 운행 시간대에 돌지 않음 | 배치 실행 시각이 운행 종료 이후 |
| FR-IN-14 | 야간 배치 순서 | 마감 → 재계산 → 승격, 마지막 회차 표본이 당일 집계 |
| FR-IN-15 | `auto_promote_enabled` 변경 | DB 런타임 설정에서 읽고 재배포로 되살아나지 않음 |

## 10. 단계별 검증 범위

1단계는 DB 기반 입력·조회 흐름을 검증하고 실시간 전달의 최종 2초 목표는 2단계의 전송 구성까지 갖춘 뒤 평가한다. 단계별 구성 파일·프로필 이름은 구현 시 정하되 위 구성 차이를 유지한다. 모든 앱 인스턴스가 동시에 마이그레이션을 실행하지 않는다.

캐시 복원은 12의 확정 DB 스냅샷 복제 규칙을 따른다. DB 백업은 상태 스냅샷뿐 아니라 공시 원문·관측·검토·운영 결정 이력도 포함한다. GPS 추가 제한값은 07, 시계 검증·보관 값은 02를 참조하며 값을 임의로 확정하지 않는다.
