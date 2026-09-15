"""입력자·관리자 계정 관리. 비밀번호는 저장소·시드에 넣지 않는다 (FR-IN-08).

실행: python -m app.accounts create --username 홍길동 --role collector
      (비밀번호는 입력 프롬프트로 받는다. 자동화에서는 SHUTTLEBUS_PASSWORD 환경변수)
"""

import argparse
import getpass
import os

from sqlalchemy import select

from app.auth import hash_password
from app.db import SessionLocal
from app.models.observation import StaffAccount


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.accounts")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="계정 생성 또는 비밀번호 재설정")
    create.add_argument("--username", required=True)
    create.add_argument("--role", choices=["collector", "admin"], required=True)
    sub.add_parser("list", help="계정 목록")
    args = parser.parse_args()

    with SessionLocal() as session:
        if args.command == "list":
            for a in session.scalars(select(StaffAccount).order_by(StaffAccount.username)):
                print(f"{a.username}\t{a.role}\t{'활성' if a.is_active else '비활성'}")
            return
        password = os.environ.get("SHUTTLEBUS_PASSWORD") or getpass.getpass("비밀번호: ")
        if len(password) < 8:
            raise SystemExit("비밀번호는 8자 이상이어야 한다.")
        account = session.scalar(select(StaffAccount).where(StaffAccount.username == args.username))
        if account is None:
            account = StaffAccount(username=args.username, role=args.role, password_hash=hash_password(password))
            session.add(account)
            action = "생성"
        else:
            account.role, account.password_hash, account.is_active = args.role, hash_password(password), True
            action = "재설정"
        session.commit()
        print(f"계정 {action}: {args.username} ({args.role})")


if __name__ == "__main__":
    main()
