"""
Local account endpoints.

Next.js calls these server-side from its NextAuth ``authorize`` callback; they
are the only public routes on the API besides the health check. Passwords are
stored as salted PBKDF2-SHA256 hashes, never in plain text.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import DatasetMeta, User
from security import (
    MIN_PASSWORD_LENGTH,
    canonical_email,
    hash_password,
    is_valid_email,
    verify_password,
)

router = APIRouter()

MAX_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60
_failures: dict[str, tuple[int, float]] = {}


class RegisterRequest(BaseModel):
    email: str
    name: str = ""
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


def _public_user(user: User) -> dict:
    return {"email": user.email, "name": user.name or user.email.split("@")[0]}


def _prune_failures() -> None:
    if len(_failures) < 1000:
        return
    cutoff = time.time() - LOCKOUT_SECONDS
    for key in [key for key, (_, first) in _failures.items() if first < cutoff]:
        _failures.pop(key, None)


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    email = canonical_email(body.email)
    name = body.name.strip()[:80]
    password = body.password

    if not is_valid_email(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
        )
    if len(password) > 256:
        raise HTTPException(status_code=422, detail="Password is too long.")

    if db.query(User).filter(User.email == email).first():
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists. Sign in instead.",
        )

    user = User(email=email, name=name or email.split("@")[0], password_hash=hash_password(password))
    db.add(user)
    db.commit()
    return {"user": _public_user(user), "workspace_ready": False}


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    email = canonical_email(body.email)
    _prune_failures()

    failures, first_failure = _failures.get(email, (0, 0.0))
    if failures >= MAX_FAILURES and time.time() - first_failure < LOCKOUT_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed sign-in attempts. Try again in a few minutes.",
        )

    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(body.password, user.password_hash):
        failures = failures + 1 if time.time() - first_failure < LOCKOUT_SECONDS else 1
        _failures[email] = (failures, first_failure if failures > 1 else time.time())
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
        )

    _failures.pop(email, None)
    active = (
        db.query(DatasetMeta)
        .filter(DatasetMeta.owner_id == email, DatasetMeta.is_active == 1)
        .first()
    )
    has_data = bool(active and (active.row_count or 0) > 0)
    return {"user": _public_user(user), "workspace_ready": has_data}
