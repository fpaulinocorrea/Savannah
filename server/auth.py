"""One owner, one password. Each signed-in device gets a cookie."""

import asyncio
import hashlib
import hmac
import secrets
from datetime import timedelta, timezone

from fastapi import Cookie, Depends, HTTPException, Request
from sqlmodel import Session

from . import config
from .db import LoginSession, engine, get_setting, set_setting, utcnow

COOKIE = "savannah_session"
MIN_PASSWORD = 8


def get_db():
    with Session(engine) as session:
        yield session


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
    return hmac.compare_digest(digest.hex(), digest_hex)


def is_set_up(db: Session) -> bool:
    return get_setting(db, "password_hash") is not None


def start_session(db: Session, request: Request) -> str:
    token = secrets.token_urlsafe(32)
    db.add(LoginSession(token=token, device=request.headers.get("user-agent", "")[:200]))
    db.commit()
    return token


def session_is_valid(db: Session, token: str | None) -> bool:
    if not token:
        return False
    row = db.get(LoginSession, token)
    if not row:
        return False
    created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=timezone.utc)
    if utcnow() - created > timedelta(days=config.SESSION_DAYS):
        db.delete(row)
        db.commit()
        return False
    return True


def require_login(
    db: Session = Depends(get_db),
    savannah_session: str | None = Cookie(default=None),
) -> Session:
    if not session_is_valid(db, savannah_session):
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return db


async def slow_down() -> None:
    """Pause after a wrong password so guessing is slow."""
    await asyncio.sleep(1.0)


def save_password(db: Session, password: str) -> None:
    set_setting(db, "password_hash", hash_password(password))
