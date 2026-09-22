from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


DEV_JWT_SECRET = "dev-only-insecure-secret-change-me"
# .env.example의 자리표시 값도 운영에서 거부한다
PLACEHOLDER_JWT_SECRETS = {DEV_JWT_SECRET, "change-me-to-a-long-random-string"}


class Settings(BaseSettings):
    # 로컬 실행(cd api)도 Compose와 같은 루트 설정을 읽는다.
    # api/.env가 있으면 로컬 재정의를 허용하고 실제 환경변수가 최우선이다.
    model_config = SettingsConfigDict(
        env_file=(Path(__file__).resolve().parents[2] / ".env", Path(__file__).resolve().parents[1] / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 로컬 기본값은 .tools의 휴대용 PostgreSQL. Compose에서는 DATABASE_URL로 덮어쓴다.
    database_url: str = "postgresql+psycopg://postgres@localhost:55432/shuttlebus"

    # 서명 비밀값 (01 7장, 서버 전용). 운영에서는 반드시 JWT_SECRET으로 덮어쓴다
    jwt_secret: str = DEV_JWT_SECRET
    access_token_ttl_seconds: int = 86400  # 확정 (01 5장)

    # 08 6장 — 시험값
    observation_grace_seconds: int = 2400
    # 06 3장 — 시험값
    max_skip_stops: int = 3

    # 11 3·5장 — 시험값. 14 4장이 ConfigMap으로 두는 값이라 모듈 상수가 아니라 설정이다 (2026-09-18)
    arrived_freshness_seconds: int = 180
    refresh_after_seconds: int = 30

    # 02 6·12장 — 시험값 (2026-09-15 사용자 승인). 실측 후 교체.
    # 환경변수로 비우면(None) 문서의 보수적 처리(검토 대기 보관)를 따른다
    realtime_input_window_seconds: int | None = 120
    clock_skew_tolerance_seconds: float | None = 5.0
    pending_input_retention_hours: float | None = 24.0
    clock_check_valid_seconds: int | None = 6 * 3600

    # 13 10장 — 실측 후 확정. None이면 검토 대상 판정을 하지 않는다
    session_review_grace_seconds: int | None = None

    # 경로 조사 적재 시험값 (PLAN-route-data.md ②, 2026-09-22에 모듈 상수에서 이동).
    # 실측 후 07의 max_route_deviation_m 등으로 대체한다. 지구 반경 같은 물리 상수는 코드에 둔다
    survey_tolerance_m: float = 5.0
    survey_max_speed_mps: float = 40.0
    survey_max_deviation_m: float = 30.0
    survey_stop_match_radius_m: float = 150.0
    survey_dwell_speed_mps: float = 1.0
    # 검증 트랙이 경로를 만든 그 기록인지 판정하는 시각 겹침 비율. 겹침률만으로 독립 기록을 보장하지는
    # 못한다 — 출처 트랙 ID 열을 두는 편이 정확하고, 그것은 스키마 승인 사항이다 (REVIEW-2026-09-22 P2)
    survey_same_recording_overlap: float = 0.9

    # 로그인 시도 제한 (IMPROVEMENTS 한계 1, 2026-09-18). 연속 실패가 상한에 닿으면 잠금 시간 동안 거절한다
    login_max_failures: int = 5
    login_lockout_seconds: int = 900

    # 01 4장 — 요청 접수증 보존 기간 (2026-09-18 결정). 재전송 대비용이라 길게 둘 이유가 없다
    idempotency_retention_days: int = 7

    # 12 실시간 전송. REDIS_URL이 없으면 캐시 없이 DB 스냅샷을 읽고 Socket.IO는 단일 프로세스로 돈다
    redis_url: str | None = None
    realtime_workers: bool = True  # outbox 전송·상태 만료 확정 작업을 이 프로세스에서 돌릴지
    outbox_poll_seconds: float = 0.3  # NFR-01 2초 안 전달을 위한 전송 주기
    state_refresh_seconds: float = 30.0  # 시간 경과로 바뀐 상태를 확정하는 주기 (11 refresh_after_seconds와 맞춤)
    # NoDecode: 환경변수 값을 JSON으로 먼저 해석하지 않게 하고 아래 변환기로 쉼표를 나눈다
    socket_cors_origins: Annotated[list[str], NoDecode] = []  # 비우면 cors_origins를 따른다

    # 브라우저 화면의 출처. 비우면 같은 출처만 허용한다. '*'는 쓰지 않는다 (md_frontend/must_do.md S2)
    cors_origins: Annotated[list[str], NoDecode] = []

    # development / production. production이면 기동 시 비밀값을 검사한다
    app_env: str = "development"

    @field_validator("cors_origins", "socket_cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value):
        """CORS_ORIGINS=http://localhost:3000,http://192.168.0.5:3000 처럼 쉼표로 적을 수 있게 한다."""
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    def check_production_secrets(self) -> None:
        if self.app_env == "production" and (self.jwt_secret in PLACEHOLDER_JWT_SECRETS or len(self.jwt_secret) < 32):
            raise RuntimeError("APP_ENV=production에서는 32자 이상의 JWT_SECRET을 설정해야 합니다.")


settings = Settings()
