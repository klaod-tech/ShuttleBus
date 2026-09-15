"""시험 DB: TEST_DATABASE_URL (기본은 .tools 휴대용 PostgreSQL의 shuttlebus_test).

세션 시작 시 스키마를 비우고 마이그레이션·시드를 적용한다. 각 시험은 트랜잭션 안에서 돌고 끝나면 되돌린다.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

API_DIR = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres@localhost:55432/shuttlebus_test"
)


def alembic_config(url: str) -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    return cfg


def reset_schema(url: str) -> None:
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _no_background_workers():
    """시험 중에는 실제 DB를 보는 백그라운드 전송·만료 작업을 돌리지 않는다. 필요한 시험이 직접 호출한다."""
    from app.config import settings

    settings.realtime_workers = False
    yield


@pytest.fixture(scope="session")
def engine():
    reset_schema(TEST_DATABASE_URL)
    command.upgrade(alembic_config(TEST_DATABASE_URL), "head")
    eng = create_engine(TEST_DATABASE_URL)
    from app.seed import seed

    with Session(eng) as s:
        seed(s)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        conn.close()


@pytest.fixture
def client(db):
    from app.db import get_session
    from app.main import app

    app.dependency_overrides[get_session] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def set_now(client):
    """서버 시각 고정: set_now(2026, 9, 14, 7, 0) — 서울 기준."""
    from datetime import datetime

    from app.clock import set_fixed_now
    from app.timeutil import SEOUL

    def _set(*parts):
        moment = datetime(*parts, tzinfo=SEOUL)
        set_fixed_now(moment)
        return moment

    yield _set
    set_fixed_now(None)
