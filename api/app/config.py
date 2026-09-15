from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 로컬 기본값은 .tools의 휴대용 PostgreSQL. Compose에서는 DATABASE_URL로 덮어쓴다.
    database_url: str = "postgresql+psycopg://postgres@localhost:55432/shuttlebus"

    # 서명 비밀값 (01 7장, 서버 전용). 운영에서는 반드시 JWT_SECRET으로 덮어쓴다
    jwt_secret: str = "dev-only-insecure-secret-change-me"
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


settings = Settings()
