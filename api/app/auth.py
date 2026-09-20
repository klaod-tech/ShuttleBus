"""입력자·관리자 인증 (01 5장, 06 7장). Bearer JWT, 수명 24시간, refresh 없음."""

import base64
import hashlib
import hmac
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt
from fastapi import Depends, Header
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.clock import get_now
from app.config import settings
from app.db import get_session
from app.errors import AppError
from app.models.observation import StaffAccount

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return "scrypt${}${}${}${}${}".format(
        SCRYPT_N, SCRYPT_R, SCRYPT_P, base64.b64encode(salt).decode(), base64.b64encode(digest).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), n=int(n), r=int(r), p=int(p))
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


@dataclass(frozen=True)
class Principal:
    account_id: uuid.UUID
    username: str
    role: str


def issue_token(account: StaffAccount, now: datetime) -> tuple[str, int]:
    ttl = settings.access_token_ttl_seconds
    payload = {
        "sub": str(account.account_id),
        "username": account.username,
        "role": account.role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256"), ttl


_DUMMY_HASH = hash_password("dummy-password-for-timing")


class AccountLocked(Exception):
    def __init__(self, until: datetime):
        self.until = until


def _touch_login_counters(session: Session, account: StaffAccount, **values) -> None:
    # updated_at은 '계정 관리' 이력이다. 로그인 실패 카운터 갱신이 그 시각을 움직이지 않게 명시적으로 유지한다
    session.execute(
        update(StaffAccount)
        .where(StaffAccount.account_id == account.account_id)
        .values(updated_at=StaffAccount.updated_at, **values)
    )
    # 같은 세션이 다음 요청도 처리할 수 있다(시험). 메모리의 값이 DB와 어긋나지 않게 다시 읽게 한다
    session.expire(account, ["failed_login_count", "locked_until"])


def authenticate(session: Session, username: str, password: str, now: datetime | None = None) -> StaffAccount | None:
    """아이디·비밀번호 확인. 잠긴 계정은 AccountLocked, 실패는 None.

    연속 실패가 login_max_failures에 닿으면 login_lockout_seconds 동안 잠근다 (IMPROVEMENTS 한계 1).
    잠긴 동안에는 맞는 비밀번호도 받지 않는다 — 대입 공격이 잠금 직전에 맞힌 값을 확인하지 못하게.
    """
    now = now or get_now()
    account = session.scalar(select(StaffAccount).where(StaffAccount.username == username))
    # 없는 계정도 같은 해시 비용을 치러 응답 시간으로 계정 존재를 알 수 없게 한다
    valid = verify_password(password, account.password_hash if account is not None else _DUMMY_HASH)
    if account is None or not account.is_active:
        return None
    if account.locked_until is not None and account.locked_until > now:
        raise AccountLocked(account.locked_until)
    if not valid:
        failures = account.failed_login_count + 1
        if failures >= settings.login_max_failures:
            _touch_login_counters(session, account, failed_login_count=0, locked_until=now + timedelta(seconds=settings.login_lockout_seconds))
        else:
            _touch_login_counters(session, account, failed_login_count=failures)
        session.commit()
        return None
    if account.failed_login_count or account.locked_until is not None:
        _touch_login_counters(session, account, failed_login_count=0, locked_until=None)
        session.commit()
    return account


def revoke_tokens(session: Session, account: StaffAccount, now: datetime) -> None:
    """지금까지 발급된 토큰을 전부 무효로 만든다 (IMPROVEMENTS 한계 2). 비밀번호 재설정·강제 로그아웃에서 부른다."""
    account.token_not_before = now


def current_principal(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_now),
) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(401, "AUTH_REQUIRED", "로그인이 필요합니다.")
    token = authorization.split(" ", 1)[1]
    try:
        # 시험에서 시각을 고정할 수 있도록 exp는 서버 시각 의존성으로 직접 검사한다
        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], options={"verify_exp": False})
    except jwt.PyJWTError:
        raise AppError(401, "AUTH_REQUIRED", "로그인 정보가 올바르지 않습니다. 다시 로그인해 주세요.") from None
    if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] <= now.timestamp():
        raise AppError(401, "AUTH_REQUIRED", "로그인이 만료되었습니다. 다시 로그인해 주세요. 전송 대기 기록은 유지됩니다.")
    try:
        account_id = uuid.UUID(str(claims["sub"]))
    except (KeyError, ValueError):
        raise AppError(401, "AUTH_REQUIRED", "로그인 정보가 올바르지 않습니다. 다시 로그인해 주세요.") from None
    account = session.get(StaffAccount, account_id)
    if account is None or not account.is_active:
        raise AppError(401, "AUTH_REQUIRED", "사용할 수 없는 계정입니다.")
    issued_at = claims.get("iat")
    if account.token_not_before is not None and (
        not isinstance(issued_at, (int, float)) or issued_at < int(account.token_not_before.timestamp())
    ):
        raise AppError(401, "AUTH_REQUIRED", "비밀번호가 바뀌어 다시 로그인해야 합니다. 전송 대기 기록은 유지됩니다.")
    return Principal(account.account_id, account.username, account.role)


def require_role(*roles: str):
    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if principal.role not in roles:
            raise AppError(403, "FORBIDDEN", "이 작업을 할 권한이 없습니다.")
        return principal

    return dependency
