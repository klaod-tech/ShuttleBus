"""프론트엔드 담당자가 붙을 수 있게 하는 백엔드 조건 (2026-09-18).

CORS 허용, 계정 부트스트랩, 정거장 좌표 등록. 화면 코드는 이 저장소에 없다.
"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.accounts import bootstrap, check_password
from app.main import install_cors
from app.models.observation import StaffAccount
from app.models.reference import Stop
from app.seed import route_id, seed, stop_id
from app.stops import check_coordinates, set_location
from tests.test_collection import accounts  # noqa: F401
from tests.test_operations import Admin

CAMPUS = "아산캠퍼스"


# ---------- CORS ----------


def _cors_app(origins):
    app = FastAPI()
    install_cors(app, origins)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return TestClient(app)


def test_cors_allows_configured_origin_only():
    client = _cors_app(["http://localhost:3000"])
    allowed = client.get("/ping", headers={"Origin": "http://localhost:3000"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:3000"
    other = client.get("/ping", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers

    preflight = client.options(
        "/ping",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,idempotency-key",
        },
    )
    assert preflight.status_code == 200
    assert "idempotency-key" in preflight.headers.get("access-control-allow-headers", "").lower()


def test_no_cors_header_when_unset():
    client = _cors_app([])
    res = client.get("/ping", headers={"Origin": "http://localhost:3000"})
    assert "access-control-allow-origin" not in res.headers


# ---------- 계정 부트스트랩 ----------


def test_bootstrap_is_idempotent_and_requires_password(db, monkeypatch):
    monkeypatch.delenv("ADMIN_BOOTSTRAP_PASSWORD", raising=False)
    monkeypatch.setenv("ADMIN_BOOTSTRAP_ID", "boss")
    with pytest.raises(SystemExit):
        bootstrap(db)

    monkeypatch.setenv("ADMIN_BOOTSTRAP_PASSWORD", "first-password-value")
    assert "최초 관리자 생성" in bootstrap(db)
    db.flush()
    created = db.scalar(select(StaffAccount).where(StaffAccount.username == "boss"))
    assert created.role == "admin"
    before = created.password_hash

    # 두 번째 실행은 아무것도 하지 않는다 — 환경변수 값으로 비밀번호를 되돌리지 않는다
    monkeypatch.setenv("ADMIN_BOOTSTRAP_PASSWORD", "different-password")
    assert "건너뜀" in bootstrap(db)
    db.flush()
    assert db.scalar(select(StaffAccount).where(StaffAccount.username == "boss")).password_hash == before


def test_bootstrap_password_policy(monkeypatch):
    assert check_password("1234", "production") is not None
    assert check_password("1234", "development") is None


# ---------- 정거장 좌표 ----------


def test_coordinate_range_check():
    assert check_coordinates(36.7998, 127.0745) is None
    assert check_coordinates(127.0745, 36.7998) is not None  # 위경도를 뒤집어 넣은 경우
    assert check_coordinates(0.0, 0.0) is not None


def test_admin_can_register_stop_location(client, db, accounts, set_now):  # noqa: F811
    set_now(2026, 9, 18, 9, 0)
    boss = Admin(client)
    target = str(stop_id(CAMPUS))
    listed = client.get("/api/v1/admin/stops", headers=boss.headers).json()["stops"]
    assert len(listed) == 22 and all(s["latitude"] is None for s in listed)

    res = boss.post(f"/api/v1/admin/stops/{target}/location", {"latitude": 36.7998, "longitude": 127.0745, "geofence_radius_m": 60})
    assert res.status_code == 200, res.text
    assert res.json()["verification_status"] == "verified"

    flipped = boss.post(f"/api/v1/admin/stops/{target}/location", {"latitude": 127.0745, "longitude": 36.7998})
    assert flipped.status_code == 422

    missing = boss.post(f"/api/v1/admin/stops/{uuid.uuid4()}/location", {"latitude": 36.8, "longitude": 127.07})
    assert missing.status_code == 404

    # 학생 화면이 읽는 경로에도 좌표가 나온다
    route_stops = client.get(
        f"/api/v1/routes/{route_id('cheonan_asan')}/stops", params={"service_date": "2026-09-18"}
    ).json()
    campus = next(s for p in route_stops["patterns"] for s in p["stops"] if s["stop_name"] == CAMPUS)
    assert campus["latitude"] == 36.7998


def test_reseed_keeps_registered_coordinates(db):
    """원문 재적재가 현장에서 등록한 좌표를 지우지 않는다 (2026-09-18 발견)."""
    stop = db.get(Stop, stop_id(CAMPUS))
    set_location(db, stop, 36.7998, 127.0745, "verified", 60)
    db.flush()
    seed(db)
    db.flush()
    again = db.get(Stop, stop_id(CAMPUS))
    assert (again.latitude, again.longitude, again.verification_status, again.geofence_radius_m) == (36.7998, 127.0745, "verified", 60)
