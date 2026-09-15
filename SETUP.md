# 개발 환경 설치

[구현 순서](md/ROADMAP.md)를 따라 개발하는 데 필요한 도구 목록과 설치 방법이다.

## 한 번에 설치

```text
setup.cmd 더블클릭
```

또는 PowerShell에서:

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1          # 설치
powershell -ExecutionPolicy Bypass -File setup.ps1 -Check   # 점검만
```

- 이미 설치된 것은 건너뛴다. 여러 번 실행해도 된다.
- 설치할 것이 있으면 관리자 권한을 요청한다. 권한 창에서 **예**를 누른다.
- WSL2·Docker Desktop을 새로 설치했으면 **재시작 → Docker Desktop 한 번 실행 → `-Check`로 확인**한다.

## 설치하는 도구

| 도구 | winget ID | 쓰는 곳 | 로드맵 |
|---|---|---|---|
| Git | `Git.Git` | 저장소 | P0 |
| Node.js LTS | `OpenJS.NodeJS.LTS` | `web`(Next.js), `realtime`(Socket.IO) | P0, P4 |
| Python 3.13 | `Python.Python.3.13` | `api`(FastAPI) | P0 |
| WSL2 | `wsl --install` | Docker Desktop의 실행 기반 | P0 |
| Docker Desktop | `Docker.DockerDesktop` | Compose로 postgres·api·web, 이후 redis·realtime | P0, P4 |

**PostgreSQL과 Redis는 따로 설치하지 않는다.** Docker 컨테이너로 띄운다 (`14` 2장).

Kubernetes 실습(P8)용 minikube·kubectl은 그 단계에서 추가한다. 지금 설치하지 않는다.

## 이 컴퓨터의 상태 (2026-09-14 점검)

| 도구 | 상태 |
|---|---|
| Git | 2.55.0 설치됨 |
| Node.js / npm | 24.18.0 / 11.16.0 설치됨 |
| Python / pip | 3.13.14 / 26.1.2 설치됨 |
| WSL2 | 설치됨 (2026-09-15) |
| Docker Desktop | 설치됨 — Docker 29.8.0, Compose v5.5.1 (2026-09-15) |

## 프로젝트 패키지

설치 스크립트는 아래 파일이 존재하면 해당 패키지를 설치한다. 2026-09-15 확인 시 api/requirements.txt는 존재하고, web/package.json과 realtime/package.json은 아직 없다. 백엔드 패키지 설치 여부는 이번 프론트 점검에서 확인하지 않았다.

| 파일 | 설치 방식 |
|---|---|
| `api/requirements.txt` | `api/.venv` 가상환경을 만들고 `pip install -r` |
| `web/package.json` | `npm install` |
| `realtime/package.json` | `npm install` |

패키지를 추가할 때는 위 파일에 적는다. 그러면 다른 컴퓨터에서도 `setup.cmd` 한 번으로 같은 환경이 된다.

## 프론트엔드 사전 준비 (2026-09-15 실제 점검)

[화면 구상](md_frontend/README.md)과 설치 스크립트를 읽고 프론트엔드 범위만 점검했다. 현재 필요한 공통 도구는 이미 설치되어 있어 신규 설치는 수행하지 않았다.

| 항목 | 확인 결과 | 처리 |
|---|---|---|
| Node.js | v24.18.0, 실행 경로 C:\Program Files\nodejs\node.exe | 재설치 불필요 |
| npm | 11.16.0, 버전 명령 실행 성공 | 재설치 불필요 |
| Node 실행 | 기본 스크립트 실행과 fetch 함수 존재 확인 | 런타임 기본 점검 통과. 외부 통신·앱 실행 검증은 아님 |
| 프론트 프로젝트 | web/package.json 없음 | 설치할 의존성 목록 없음 |
| 실시간 프로젝트 | realtime/package.json 없음 | 해당 단계에서 준비 |

### 구현 시작 시 설치할 항목

- Next.js·React·TypeScript 및 필요한 개발 패키지는 web 프로젝트를 만들 때 호환 버전을 확인하고 프로젝트 안에 설치한다. 지금 전역으로 미리 설치하지 않는다.
- UI·아이콘·상태 관리 라이브러리는 피그마 도안과 실제 필요가 정해진 뒤 선택한다. 초안만으로 여러 라이브러리를 설치하지 않는다.
- Socket.IO 클라이언트는 실시간 연동 단계에서 필요 여부와 서버 계약을 확인한 뒤 설치한다.
- 카카오 지도는 기존 설계의 JavaScript SDK 로드 방식으로 연동한다. 별도 지도 래퍼 패키지는 아직 선택하지 않았다. 지도 키와 개발·배포 도메인 등록은 연동 전 준비 항목이다.
- 패키지 설치 시 web/package.json과 잠금 파일을 함께 관리한다. 실제 화면 실행·빌드·서버 연동 검증은 구현 후 별도로 수행한다.

### 이번 작업 범위

실제 UI 구현은 백엔드·서버 준비 후 진행한다는 기존 방침을 유지한다. 사전 도구 점검은 수행했지만 web 폴더나 임시 앱을 만들지 않았다. 전체 setup.cmd는 API 패키지·WSL·Docker까지 설치할 수 있어 이번 프론트 점검에서는 실행하지 않았다. 위의 2026-09-14 전체 환경 표는 과거 점검 기록이며 WSL·Docker의 현재 상태를 이번에 재확인한 것은 아니다.
