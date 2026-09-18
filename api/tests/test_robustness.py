"""코드 검토에서 드러난 경계 입력 (2026-09-15). 모두 500이 아니라 정해진 오류 봉투로 답해야 한다."""

import jwt
import pytest

from app.config import settings
from app.seed import route_id, stop_id
from tests.test_collection import Collector, accounts, at, trip1, trip_state, trusted_settings  # noqa: F401

ROUTE = str(route_id("cheonan_asan"))


@pytest.mark.parametrize(
    "path,params",
    [
        ("/api/v1/scheduled-trips", {"service_date": "9999-12-31", "origin_stop_id": str(stop_id("아산캠퍼스")), "destination_stop_id": str(stop_id("천안아산역"))}),
        ("/api/v1/scheduled-trips", {"service_date": "0001-01-01"}),
        ("/api/v1/service-calendar", {"from_date": "9999-12-01", "to_date": "9999-12-31"}),
        ("/api/v1/routes/{route}/stops", {"service_date": "9999-12-31"}),
    ],
)
def test_out_of_range_service_date_is_422(client, set_now, path, params):
    set_now(2026, 9, 14, 8, 0)
    res = client.get(path.format(route=ROUTE), params={"route_id": ROUTE, **params})
    assert res.status_code == 422 and res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_candidates_near_period_end_do_not_overflow(client, set_now):
    set_now(2026, 9, 14, 8, 0)
    res = client.get(
        "/api/v1/scheduled-trips",
        params={"route_id": ROUTE, "service_date": "2100-12-31", "origin_stop_id": str(stop_id("아산캠퍼스")), "destination_stop_id": str(stop_id("천안아산역"))},
    )
    assert res.status_code == 200 and res.json()["schedule_status"] == "out_of_period"


@pytest.mark.parametrize("claims", [{"sub": "not-a-uuid", "exp": 4102444800}, {"exp": 4102444800}, {"sub": "x", "exp": "soon"}])
def test_malformed_token_claims_are_401(client, accounts, claims):  # noqa: F811
    token = jwt.encode(claims, settings.jwt_secret, algorithm="HS256")
    res = client.get("/api/v1/collection-sessions/00000000-0000-0000-0000-000000000000", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401 and res.json()["error"]["code"] == "AUTH_REQUIRED"


def test_unknown_user_login_is_401(client, accounts):  # noqa: F811
    res = client.post("/api/v1/auth/login", json={"username": "nobody", "password": "password123"})
    assert res.status_code == 401


def test_future_occurred_at_goes_to_review(client, trip1, set_now, trusted_settings):  # noqa: F811
    """열린 세션의 수집 기간 끝은 수신 시각(+시계 허용 오차)이다 (02 6장). 미래 기록이 공개 상태를 앞질러 바꾸지 않는다."""
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    set_now(2026, 9, 14, 8, 5)
    future, _ = kim.observe(trip1["stops"][0], "departed", at(65), clock=clock, advance_clock=False)
    event = future.json()["event"]
    assert event["validation_status"] == "needs_review" and "outside_collection_period" in event["review_reason"]
    assert trip_state(client, 1)["vehicles"][0]["information_status"] == "timetable_only"

    within_tolerance, _ = kim.observe(trip1["stops"][0], "departed", at(5).replace(second=3), clock=clock, advance_clock=False)
    assert within_tolerance.json()["event"]["validation_status"] == "valid"


def test_client_sequence_beyond_integer_is_422(client, trip1, set_now, trusted_settings):  # noqa: F811
    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    set_now(2026, 9, 14, 8, 5)
    res, _ = kim.observe(trip1["stops"][0], "departed", at(5), sequence=2**40)
    assert res.status_code == 422 and res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_future_event_cannot_be_approved_until_its_time(client, trip1, set_now, trusted_settings):  # noqa: F811
    from tests.test_operations import Admin

    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    clock = kim.clock(set_now, at(4))
    set_now(2026, 9, 14, 8, 5)
    future, _ = kim.observe(trip1["stops"][0], "departed", at(20), clock=clock, advance_clock=False)
    event_id = future.json()["event"]["event_id"]
    boss = Admin(client)
    early = boss.review(event_id, "approve", kim, 1)
    assert early.status_code == 409 and early.json()["error"]["code"] == "REVIEW_CONFLICT"
    set_now(2026, 9, 14, 8, 21)
    assert boss.review(event_id, "approve", kim, 1).status_code == 200


def test_admin_can_end_orphaned_session_then_new_collection_starts(client, trip1, set_now, trusted_settings):  # noqa: F811
    """입력자 기기 분실로 writer_instance_id를 잃으면 SESSION_OWNERSHIP_CONFLICT가 계속된다. 관리자 종료로 풀린다."""
    from tests.test_operations import Admin

    kim = Collector(client, "kim")
    kim.start(trip1["vehicle"])
    set_now(2026, 9, 14, 8, 10)
    lost = Collector(client, "kim").start(trip1["vehicle"])  # 새 기기: 보관한 writer_instance_id 없음
    assert lost.status_code == 409 and lost.json()["error"]["code"] == "SESSION_OWNERSHIP_CONFLICT"

    boss = Admin(client)
    sid = kim.session["collection_session_id"]
    ended = boss.post(f"/api/v1/collection-sessions/{sid}/end", {"ended_at": at(10).isoformat(), "expected_input_version": kim.reload()["input_version"]})
    assert ended.status_code == 200 and ended.json()["collection_status"] == "ended"
    lee = Collector(client, "lee")
    other = lee.post(f"/api/v1/collection-sessions/{sid}/end", {"ended_at": at(10).isoformat(), "expected_input_version": 1})
    assert other.status_code == 409  # 입력자는 여전히 남의 세션을 종료할 수 없다
    assert Collector(client, "kim").start(trip1["vehicle"]).status_code == 201


def test_notices_unknown_route_is_404(client):
    res = client.get("/api/v1/notices", params={"route_id": "00000000-0000-0000-0000-000000000000"})
    assert res.status_code == 404


def test_dev_short_password_allowed_but_production_refuses():
    """개발용 임시 계정(admin/admin, user/1234)은 허용, 운영에서는 8자 미만을 거부한다."""
    from app.accounts import check_password

    assert check_password("admin", "development") is None
    assert check_password("1234", "development") is None
    assert check_password("123", "development") is not None
    assert check_password("admin", "production") is not None
    assert check_password("a-long-enough-secret", "production") is None
