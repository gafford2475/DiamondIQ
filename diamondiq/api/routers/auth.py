from __future__ import annotations

import hmac
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ... import auth
from ... import models as m
from ...config import settings
from ..deps import SessionDep

router = APIRouter(prefix="/auth", tags=["accounts"])


class SetupIn(BaseModel):
    setup_code: str
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str = Field(min_length=1)
    password: str


class LoginIn(BaseModel):
    email: str
    password: str


class UserIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str = Field(min_length=1)
    role: Literal["admin", "scout", "viewer"] = "scout"
    password: str


class UserUpdate(BaseModel):
    name: str | None = None
    role: Literal["admin", "scout", "viewer"] | None = None
    is_active: bool | None = None
    password: str | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


def _user_out(u: m.User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "is_active": u.is_active,
            "created_at": u.created_at, "last_login_at": u.last_login_at}


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(auth.COOKIE, token, max_age=settings.session_days * 86400, httponly=True,
                        secure=settings.secure_cookies, samesite="lax", path="/")


@router.get("/status")
def status(session: Session = SessionDep):
    """Public: whether this server still needs its first account (drives the setup screen)."""
    return {"needs_setup": not session.scalar(select(func.count(m.User.id)))}


@router.post("/setup", status_code=201)
def first_admin(body: SetupIn, request: Request, response: Response, session: Session = SessionDep):
    """Create the first admin account. Only works while the server has no users, with the code from the server log."""
    if session.scalar(select(func.count(m.User.id))):
        raise HTTPException(409, "This server is already set up. Sign in instead.")
    code = auth.SETUP_CODE or auth.prepare_setup(session)
    if not hmac.compare_digest(body.setup_code.strip().upper(), code or ""):
        raise HTTPException(403, "Wrong setup code. It is printed in the server's log when it starts.")
    user = auth.create_user(session, body.email, body.name, body.password, role="admin")
    auth.SETUP_CODE = None
    _set_cookie(response, auth.start_session(session, user, request.headers.get("user-agent")))
    return _user_out(user)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, session: Session = SessionDep):
    email = body.email.strip().lower()
    ip = request.client.host if request.client else "?"
    auth.throttle.check(f"email:{email}", f"ip:{ip}")
    user = session.scalar(select(m.User).where(m.User.email == email))
    if not user or not user.is_active or not auth.verify_password(body.password, user.password_hash):
        auth.throttle.fail(f"email:{email}", f"ip:{ip}")
        raise HTTPException(401, "Wrong email or password.")
    auth.throttle.clear(f"email:{email}")
    token = auth.start_session(session, user, request.headers.get("user-agent"))
    _set_cookie(response, token)
    # The token is also returned so scripts can use it as a Bearer token.
    return {"user": _user_out(user), "token": token}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, session: Session = SessionDep):
    auth.end_session(session, auth.request_token(request))
    response.delete_cookie(auth.COOKIE, path="/")


@router.get("/me")
def me(user: m.User = Depends(auth.current_user)):
    return _user_out(user)


@router.post("/me/password", status_code=204)
def change_password(body: PasswordChange, request: Request, response: Response, user: m.User = Depends(auth.current_user),
                    session: Session = SessionDep):
    if not auth.verify_password(body.current_password, user.password_hash):
        raise HTTPException(401, "Current password is wrong.")
    auth.check_password_rules(body.new_password)
    user = session.merge(user)
    user.password_hash = auth.hash_password(body.new_password)
    session.commit()
    # Sign out everywhere else, keep this browser signed in.
    auth.end_all_sessions(session, user.id)
    _set_cookie(response, auth.start_session(session, user, request.headers.get("user-agent")))


@router.get("/users")
def list_users(_: m.User = Depends(auth.require_admin), session: Session = SessionDep):
    return [_user_out(u) for u in session.scalars(select(m.User).order_by(m.User.name))]


@router.post("/users", status_code=201)
def add_user(body: UserIn, _: m.User = Depends(auth.require_admin), session: Session = SessionDep):
    return _user_out(auth.create_user(session, body.email, body.name, body.password, body.role))


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, admin: m.User = Depends(auth.require_admin), session: Session = SessionDep):
    user = session.get(m.User, user_id)
    if not user:
        raise HTTPException(404, "user not found")
    if user.id == admin.id and (body.role not in (None, "admin") or body.is_active is False):
        raise HTTPException(422, "You can't remove your own admin access.")
    if body.name is not None:
        user.name = body.name
    if body.role is not None:
        user.role = body.role
    if body.password:
        auth.check_password_rules(body.password)
        user.password_hash = auth.hash_password(body.password)
    if body.is_active is not None:
        user.is_active = body.is_active
    session.commit()
    if body.password or body.is_active is False:
        auth.end_all_sessions(session, user.id)
    return _user_out(user)
