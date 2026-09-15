"""회차 보충 생성 배치 (05 5장). 서비스 시작 시·매일 실행한다. 멱등이라 실패한 날을 다음 실행이 메운다.

실행: python -m app.jobs ensure-trips [--days 14]
      python -m app.jobs mark-sessions-for-review   (13 2장, 주기 실행)
"""

import argparse
from datetime import timedelta

from sqlalchemy import select

from app.calendar.service import ensure_scheduled_trips
from app.clock import get_now
from app.db import SessionLocal
from app.models.reference import Route
from app.operations.service import mark_sessions_for_review
from app.timeutil import today_seoul


def ensure_trips(days: int) -> None:
    start = today_seoul()
    end = start + timedelta(days=days)
    with SessionLocal() as session:
        for route in session.scalars(select(Route).where(Route.is_active)):
            report = ensure_scheduled_trips(session, route.route_id, start, end)
            session.commit()
            print(f"{route.name}: {start}~{end} 신규 회차 {report.created_trips}")
            for err in report.data_errors or []:
                print(f"  자료 오류: {err}")


def mark_review() -> None:
    with SessionLocal() as session:
        marked = mark_sessions_for_review(session, get_now())
        session.commit()
        # 구간 소요시간(P5)이나 session_review_grace_seconds가 없으면 판정 근거가 없어 0건이다
        print(f"검토 대상으로 표시한 수집 세션 {len(marked)}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.jobs")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ensure-trips", help="오늘부터 N일 뒤까지 회차·차량 슬롯 생성")
    p.add_argument("--days", type=int, default=14)
    sub.add_parser("mark-sessions-for-review", help="기한이 지난 수집 세션을 검토 대상으로 표시")
    args = parser.parse_args()
    if args.command == "ensure-trips":
        ensure_trips(args.days)
    elif args.command == "mark-sessions-for-review":
        mark_review()


if __name__ == "__main__":
    main()
