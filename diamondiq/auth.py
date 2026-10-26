"""Accounts, password hashing and sign-in sessions.

Passwords are hashed with scrypt (standard library, salted, memory-hard).
Sessions are random tokens; the browser holds the token in an HttpOnly
cookie and the database stores only its SHA-256, so a leaked database does
not leak usable sessions. Scripts and integrations can send the same token as
``Authorization: Bearer <token>``.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import secrets
import time
from collections import defaultdict

from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models as m
from .config import settings
from .db import get_session

COOKIE = "diq_session"
ROLES = ("admin", "scout", "viewer")
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}
MIN_PASSWORD = 10


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT, dklen=32)
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


def check_password_rules(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise HTTPException(422, f"Password must be at least {MIN_PASSWORD} characters.")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _aware(t: dt.datetime) -> dt.datetime:
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)  # SQLite returns naive datetimes


def create_user(session: Session, email: str, name: str, password: str, role: str = "scout") -> m.User:
    if role not in ROLES:
        raise HTTPException(422, f"role must be one of {ROLES}")
    check_password_rules(password)
    email = email.strip().lower()
    if session.scalar(select(m.User).where(m.User.email == email)):
        raise HTTPException(409, "A user with that email already exists.")
    user = m.User(email=email, name=name.strip(), role=role, password_hash=hash_password(password))
    session.add(user)
    session.commit()
    return user


def start_session(session: Session, user: m.User, user_agent: str | None = None) -> str:
    token = secrets.token_urlsafe(32)
    session.add(m.AuthSession(token_hash=_token_hash(token), user_id=user.id, user_agent=(user_agent or "")[:300],
                              expires_at=_now() + dt.timedelta(days=settings.session_days)))
    user.last_login_at = _now()
    session.commit()
    return token


def end_session(session: Session, token: str | None) -> None:
    if token:
        row = session.scalar(select(m.AuthSession).where(m.AuthSession.token_hash == _token_hash(token)))
        if row:
            session.delete(row)
            session.commit()


def end_all_sessions(session: Session, user_id: int) -> None:
    for row in session.scalars(select(m.AuthSession).where(m.AuthSession.user_id == user_id)):
        session.delete(row)
    session.commit()


def request_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get(COOKIE)


def current_user(request: Request, session: Session = Depends(get_session)) -> m.User:
    token = request_token(request)
    if not token:
        raise HTTPException(401, "Sign in required.")
    row = session.scalar(select(m.AuthSession).where(m.AuthSession.token_hash == _token_hash(token)))
    if not row or _aware(row.expires_at) < _now() or not row.user.is_active:
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    return row.user


def require_access(request: Request, user: m.User = Depends(current_user)) -> m.User:
    """Everyone signed in can read; viewers cannot change anything."""
    if request.method not in ("GET", "HEAD", "OPTIONS") and user.role == "viewer":
        raise HTTPException(403, "Your account is read-only.")
    return user


def require_admin(user: m.User = Depends(current_user)) -> m.User:
    if user.role != "admin":
        raise HTTPException(403, "Admins only.")
    return user


class LoginThrottle:
    """Slow down password guessing: after 5 failures for an email or IP within 15 minutes, refuse for a while."""

    def __init__(self, limit: int = 5, window: float = 900):
        self.limit, self.window = limit, window
        self.failures: dict[str, list[float]] = defaultdict(list)

    def _recent(self, key: str) -> list[float]:
        cutoff = time.monotonic() - self.window
        self.failures[key] = [t for t in self.failures[key] if t > cutoff]
        return self.failures[key]

    def check(self, *keys: str) -> None:
        if any(len(self._recent(k)) >= self.limit for k in keys):
            raise HTTPException(429, "Too many failed sign-in attempts. Try again in 15 minutes.")

    def fail(self, *keys: str) -> None:
        for k in keys:
            self.failures[k].append(time.monotonic())

    def clear(self, *keys: str) -> None:
        for k in keys:
            self.failures.pop(k, None)


throttle = LoginThrottle()


# One-time code required to create the first admin through the web setup screen.
# Printed to the server log at startup, so only whoever runs the server can claim it.
SETUP_CODE: str | None = None


def prepare_setup(session: Session) -> str | None:
    global SETUP_CODE
    if session.scalar(select(func.count(m.User.id))):
        SETUP_CODE = None
        return None
    SETUP_CODE = SETUP_CODE or "-".join(secrets.token_hex(2).upper() for _ in range(3))
    print(f"\n  DiamondIQ setup: no accounts exist yet. Open the app and use setup code  {SETUP_CODE}\n", flush=True)
    return SETUP_CODE


def bootstrap_admin(session: Session) -> m.User | None:
    """Create the first admin from DIAMONDIQ_ADMIN_EMAIL / DIAMONDIQ_ADMIN_PASSWORD if there are no users."""
    if not settings.admin_email or not settings.admin_password:
        return None
    if session.scalar(select(func.count(m.User.id))):
        return None
    return create_user(session, settings.admin_email, "Admin", settings.admin_password, role="admin")
