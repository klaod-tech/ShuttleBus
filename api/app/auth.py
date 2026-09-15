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
from sqlalchemy import select
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


def authenticate(session: Session, username: str, password: str) -> StaffAccount | None:
    account = session.scalar(select(StaffAccount).where(StaffAccount.username == username))
    # 없는 계정도 같은 해시 비용을 치러 응답 시간으로 계정 존재를 알 수 없게 한다
    valid = verify_password(password, account.password_hash if account is not None else _DUMMY_HASH)
    if account is None or not account.is_active or not valid:
        return None
    return account


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
        raise AppError(401, "AUTH_REQUIRED", "로그인 정보가 올바르지 않습니다. 다시 로그인해 주세요.")
    if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] <= now.timestamp():
        raise AppError(401, "AUTH_REQUIRED", "로그인이 만료되었습니다. 다시 로그인해 주세요. 전송 대기 기록은 유지됩니다.")
    try:
        account_id = uuid.UUID(str(claims["sub"]))
    except (KeyError, ValueError):
        raise AppError(401, "AUTH_REQUIRED", "로그인 정보가 올바르지 않습니다. 다시 로그인해 주세요.")
    account = session.get(StaffAccount, account_id)
    if account is None or not account.is_active:
        raise AppError(401, "AUTH_REQUIRED", "사용할 수 없는 계정입니다.")
    return Principal(account.account_id, account.username, account.role)


def require_role(*roles: str):
    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if principal.role not in roles:
            raise AppError(403, "FORBIDDEN", "이 작업을 할 권한이 없습니다.")
        return principal

    return dependency
