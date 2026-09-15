from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 로컬 기본값은 .tools의 휴대용 PostgreSQL. Compose에서는 DATABASE_URL로 덮어쓴다.
    database_url: str = "postgresql+psycopg://postgres@localhost:55432/shuttlebus"


settings = Settings()
