from pydantic_settings import BaseSettings, SettingsConfigDict


DEV_JWT_SECRET = "dev-only-insecure-secret-change-me"
# .env.example의 자리표시 값도 운영에서 거부한다
PLACEHOLDER_JWT_SECRETS = {DEV_JWT_SECRET, "change-me-to-a-long-random-string"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 로컬 기본값은 .tools의 휴대용 PostgreSQL. Compose에서는 DATABASE_URL로 덮어쓴다.
    database_url: str = "postgresql+psycopg://postgres@localhost:55432/shuttlebus"

    # 서명 비밀값 (01 7장, 서버 전용). 운영에서는 반드시 JWT_SECRET으로 덮어쓴다
    jwt_secret: str = DEV_JWT_SECRET
    access_token_ttl_seconds: int = 86400  # 확정 (01 5장)

    # 08 6장 — 시험값
    observation_grace_seconds: int = 2400
    # 06 3장 — 시험값
    max_skip_stops: int = 3

    # 02 6·12장 — 시험값 (2026-09-15 사용자 승인). 실측 후 교체.
    # 환경변수로 비우면(None) 문서의 보수적 처리(검토 대기 보관)를 따른다
    realtime_input_window_seconds: int | None = 120
    clock_skew_tolerance_seconds: float | None = 5.0
    pending_input_retention_hours: float | None = 24.0
    clock_check_valid_seconds: int | None = 6 * 3600

    # 13 10장 — 실측 후 확정. None이면 검토 대상 판정을 하지 않는다
    session_review_grace_seconds: int | None = None

    # 01 4장 — 요청 접수증 보존 기간 (2026-09-18 결정). 재전송 대비용이라 길게 둘 이유가 없다
    idempotency_retention_days: int = 7

    # 12 실시간 전송. REDIS_URL이 없으면 캐시 없이 DB 스냅샷을 읽고 Socket.IO는 단일 프로세스로 돈다
    redis_url: str | None = None
    realtime_workers: bool = True  # outbox 전송·상태 만료 확정 작업을 이 프로세스에서 돌릴지
    outbox_poll_seconds: float = 0.3  # NFR-01 2초 안 전달을 위한 전송 주기
    state_refresh_seconds: float = 30.0  # 시간 경과로 바뀐 상태를 확정하는 주기 (11 refresh_after_seconds와 맞춤)
    socket_cors_origins: list[str] = []  # 화면 배포 주소가 정해지면 설정 (md_frontend/must_do.md S2)

    # development / production. production이면 기동 시 비밀값을 검사한다
    app_env: str = "development"

    def check_production_secrets(self) -> None:
        if self.app_env == "production" and (self.jwt_secret in PLACEHOLDER_JWT_SECRETS or len(self.jwt_secret) < 32):
            raise RuntimeError("APP_ENV=production에서는 32자 이상의 JWT_SECRET을 설정해야 합니다.")


settings = Settings()
