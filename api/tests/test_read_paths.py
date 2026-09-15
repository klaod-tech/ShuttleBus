"""학생 조회(주기 폴링)는 준비된 날짜에서 DB에 쓰지 않는다 (2026-09-15 검토: 요청마다 INSERT 42건이던 문제)."""

from sqlalchemy import event

from app.seed import route_id, stop_id
from tests.test_collection import trip_state  # noqa: F401

ROUTE = str(route_id("cheonan_asan"))


def count_sql(db, fn):
    stmts = []

    def before(conn, cursor, statement, params, context, executemany):
        stmts.append(statement.split()[0].upper())

    bind = db.connection()
    event.listen(bind.engine, "before_cursor_execute", before)
    try:
        fn()
    finally:
        event.remove(bind.engine, "before_cursor_execute", before)
    return stmts


def test_warm_student_reads_do_not_write(client, db, set_now):
    set_now(2026, 9, 14, 8, 0)
    params = {"route_id": ROUTE, "service_date": "2026-09-14", "origin_stop_id": str(stop_id("아산캠퍼스")), "destination_stop_id": str(stop_id("천안아산역"))}
    client.get("/api/v1/scheduled-trips", params=params)  # 회차 생성 포함 첫 요청
    trip_state(client, 1)  # 첫 상태 스냅샷 확정
    for label, fn in [
        ("candidates (warm)", lambda: client.get("/api/v1/scheduled-trips", params=params)),
        ("trip list (warm)", lambda: client.get("/api/v1/scheduled-trips", params={"route_id": ROUTE, "service_date": "2026-09-14"})),
        ("trip state (warm)", lambda: trip_state(client, 1)),
    ]:
        stmts = count_sql(db, fn)
        writes = [s for s in stmts if s in ("INSERT", "UPDATE", "DELETE")]
        assert writes == [], (label, writes)
        assert len(stmts) < 45, (label, len(stmts))


def test_counter_sees_writes(client, db, set_now):
    """위 시험이 실제로 쓰기를 잡아내는지 확인한다 (측정기가 조용히 0을 내는 실수 방지)."""
    set_now(2026, 9, 14, 8, 0)
    stmts = count_sql(db, lambda: trip_state(client, 1))  # 첫 조회는 회차·스냅샷을 만든다
    assert any(s == "INSERT" for s in stmts)
