"""입력자·관리자 계정 관리. 비밀번호는 저장소·시드에 넣지 않는다 (FR-IN-08).

계정의 유일한 출처는 DB의 `staff_accounts`다. 환경변수·코드에 계정을 두지 않는다.

실행
  python -m app.accounts create --username 홍길동 --role collector   비밀번호는 프롬프트로 받는다
  python -m app.accounts list                                         계정 목록
  python -m app.accounts bootstrap                                    최초 관리자 1명만, 멱등

`bootstrap`은 사람이 프롬프트에 답할 수 없는 첫 기동(컨테이너 등)에서만 쓴다.
ADMIN_BOOTSTRAP_PASSWORD가 파일에 평문으로 남으므로 계정을 만든 뒤 값을 지운다.
두 번째 계정부터는 `create` 또는 관리자 화면으로 만든다.
"""

import argparse
import getpass
import os

from sqlalchemy import select

from app.auth import hash_password, revoke_tokens
from app.clock import get_now
from app.config import settings
from app.db import SessionLocal
from app.models.observation import StaffAccount

MIN_LENGTH = 8
DEV_MIN_LENGTH = 4


def check_password(password: str, app_env: str) -> str | None:
    """운영에서는 8자 이상만 허용한다. 개발에서는 시험용 짧은 비밀번호를 쓸 수 있게 경고만 남긴다.

    운영 계정을 개발용 비밀번호로 만들어 두는 실수를 막는 것이 목적이다.
    """
    if app_env == "production":
        return None if len(password) >= MIN_LENGTH else f"운영에서는 비밀번호가 {MIN_LENGTH}자 이상이어야 한다."
    return None if len(password) >= DEV_MIN_LENGTH else f"비밀번호가 {DEV_MIN_LENGTH}자 이상이어야 한다."


def upsert(session, username: str, role: str, password: str) -> str:
    account = session.scalar(select(StaffAccount).where(StaffAccount.username == username))
    if account is None:
        session.add(StaffAccount(username=username, role=role, password_hash=hash_password(password)))
        return "생성"
    account.role, account.password_hash, account.is_active = role, hash_password(password), True
    revoke_tokens(session, account, get_now())  # 재설정 전에 발급된 토큰은 즉시 무효 (IMPROVEMENTS 한계 2)
    account.failed_login_count, account.locked_until = 0, None
    return "재설정"


def bootstrap(session) -> str:
    """최초 관리자 1명을 만든다. 이미 같은 아이디가 있으면 아무것도 하지 않는다 (멱등).

    기존 계정의 비밀번호를 되돌리지 않는다 — 컨테이너를 다시 띄울 때마다 비밀번호가
    환경변수 값으로 돌아가면, 그 파일을 가진 사람이 계정을 영구히 지배한다.
    """
    username = os.environ.get("ADMIN_BOOTSTRAP_ID") or "admin"
    password = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD") or ""
    if not password:
        raise SystemExit("ADMIN_BOOTSTRAP_PASSWORD가 비어 있다. 값을 주거나 'create'로 프롬프트를 쓴다.")
    problem = check_password(password, settings.app_env)
    if problem:
        raise SystemExit(problem)
    if session.scalar(select(StaffAccount.account_id).where(StaffAccount.username == username)) is not None:
        return f"이미 있는 계정이라 건너뜀: {username}"
    session.add(StaffAccount(username=username, role="admin", password_hash=hash_password(password)))
    return f"최초 관리자 생성: {username} — ADMIN_BOOTSTRAP_PASSWORD를 지운다"


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.accounts")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="계정 생성 또는 비밀번호 재설정")
    create.add_argument("--username", required=True)
    create.add_argument("--role", choices=["collector", "admin"], required=True)
    sub.add_parser("list", help="계정 목록")
    revoke = sub.add_parser("revoke-tokens", help="발급된 토큰 전부 무효화 (강제 로그아웃). 비밀번호는 그대로")
    revoke.add_argument("--username", required=True)
    sub.add_parser("bootstrap", help="ADMIN_BOOTSTRAP_ID/PASSWORD로 최초 관리자 1명 생성 (멱등)")
    args = parser.parse_args()

    with SessionLocal() as session:
        if args.command == "list":
            for a in session.scalars(select(StaffAccount).order_by(StaffAccount.username)):
                print(f"{a.username}\t{a.role}\t{'활성' if a.is_active else '비활성'}\t{a.updated_at:%Y-%m-%d %H:%M}")
            return
        if args.command == "bootstrap":
            message = bootstrap(session)
            session.commit()
            print(message)
            return
        if args.command == "revoke-tokens":
            account = session.scalar(select(StaffAccount).where(StaffAccount.username == args.username))
            if account is None:
                raise SystemExit(f"계정이 없다: {args.username}")
            revoke_tokens(session, account, get_now())
            session.commit()
            print(f"토큰 무효화: {args.username} — 이전 로그인은 전부 다시 해야 한다")
            return
        password = os.environ.get("SHUTTLEBUS_PASSWORD") or getpass.getpass("비밀번호: ")
        problem = check_password(password, settings.app_env)
        if problem:
            raise SystemExit(problem)
        if len(password) < MIN_LENGTH:
            print(f"경고: 개발용 짧은 비밀번호다 ({len(password)}자). 외부 공개 전에 재설정한다.")
        action = upsert(session, args.username, args.role, password)
        session.commit()
        print(f"계정 {action}: {args.username} ({args.role})")


if __name__ == "__main__":
    main()
