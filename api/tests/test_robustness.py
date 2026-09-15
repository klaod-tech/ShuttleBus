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
