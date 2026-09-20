"""로그인 시도 제한·토큰 즉시 차단 (IMPROVEMENTS 한계 1·2, 2026-09-18)."""

from sqlalchemy import select

from app.accounts import upsert
from app.config import settings
from app.models.observation import StaffAccount
from tests.test_collection import accounts  # noqa: F401


def login(client, username, password):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def test_lockout_after_repeated_failures_then_release(client, db, accounts, set_now, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "login_max_failures", 3)
    monkeypatch.setattr(settings, "login_lockout_seconds", 600)
    set_now(2026, 9, 14, 7, 0)
    for _ in range(2):
        assert login(client, "kim", "wrong").status_code == 401
    # 세 번째 실패에서 잠긴다
    assert login(client, "kim", "wrong").status_code == 401
    locked = login(client, "kim", "password123")
    assert locked.status_code == 429, locked.text
    body = locked.json()["error"]
    assert body["code"] == "LOGIN_LOCKED" and body["retryable"] is True
    # updated_at은 계정 관리 이력이라 실패 카운터 갱신이 움직이지 않는다
    row = db.scalar(select(StaffAccount).where(StaffAccount.username == "kim"))
    assert row.locked_until is not None and row.failed_login_count == 0

    # 잠금 시간이 지나면 맞는 비밀번호로 들어가고 카운터가 초기화된다
    set_now(2026, 9, 14, 7, 11)
    ok = login(client, "kim", "password123")
    assert ok.status_code == 200, ok.text
    db.expire_all()
    row = db.scalar(select(StaffAccount).where(StaffAccount.username == "kim"))
    assert row.locked_until is None and row.failed_login_count == 0


def test_failure_counter_resets_on_success(client, db, accounts, set_now, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "login_max_failures", 3)
    set_now(2026, 9, 14, 7, 0)
    assert login(client, "kim", "wrong").status_code == 401
    assert login(client, "kim", "wrong").status_code == 401
    assert login(client, "kim", "password123").status_code == 200
    # 성공으로 0이 됐으니 다시 두 번 틀려도 잠기지 않는다
    assert login(client, "kim", "wrong").status_code == 401
    assert login(client, "kim", "wrong").status_code == 401
    assert login(client, "kim", "password123").status_code == 200


def test_unknown_user_is_401_not_locked(client, accounts, set_now):  # noqa: F811
    set_now(2026, 9, 14, 7, 0)
    for _ in range(10):
        assert login(client, "nobody", "x").status_code == 401


def test_password_reset_invalidates_existing_tokens(client, db, accounts, set_now):  # noqa: F811
    set_now(2026, 9, 14, 7, 0)
    token = login(client, "kim", "password123").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/collection-sessions/00000000-0000-0000-0000-000000000000", headers=headers).status_code == 404

    set_now(2026, 9, 14, 7, 5)
    assert upsert(db, "kim", "collector", "new-password-9") == "재설정"
    db.flush()
    # 이전 토큰은 만료 전이라도 거절된다
    res = client.get("/api/v1/collection-sessions/00000000-0000-0000-0000-000000000000", headers=headers)
    assert res.status_code == 401 and "다시 로그인" in res.json()["error"]["message"]

    # 재설정 뒤 새 로그인은 정상
    set_now(2026, 9, 14, 7, 6)
    fresh = login(client, "kim", "new-password-9").json()["access_token"]
    res = client.get("/api/v1/collection-sessions/00000000-0000-0000-0000-000000000000", headers={"Authorization": f"Bearer {fresh}"})
    assert res.status_code == 404
