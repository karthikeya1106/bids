"""
Identity for the BIDS API.

The browser never talks to FastAPI directly. Next.js authenticates the session
and forwards every request with a short-lived HMAC signature over the user's
email, so a caller cannot simply invent an ``X-BIDS-User`` header. Every data
endpoint resolves the owner through :func:`require_user` and scopes its queries
to it.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time

from fastapi import Header, HTTPException, status

# Shared only with the Next.js server (see backend/.env and frontend/.env.local).
INTERNAL_SECRET = os.getenv(
    "BIDS_INTERNAL_SECRET",
    "dev-only-bids-internal-signing-key-change-me",
)
SIGNATURE_WINDOW_SECONDS = int(os.getenv("BIDS_SIGNATURE_WINDOW_SECONDS", "90"))
PBKDF2_ITERATIONS = 310_000
MIN_PASSWORD_LENGTH = 8

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def canonical_email(email: str | None) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_PATTERN.match(email)) and len(email) <= 254


def sign_message(user: str, timestamp: str) -> str:
    """HMAC the owner + timestamp; mirrored in frontend/src/lib/backend.ts."""
    payload = f"{user}\n{timestamp}".encode("utf-8")
    return hmac.new(INTERNAL_SECRET.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_signature(
    x_bids_user: str | None,
    x_bids_timestamp: str | None,
    x_bids_signature: str | None,
) -> str:
    """Validate the server-to-server signature and return the canonical owner."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sign in to access this resource.",
        headers={"WWW-Authenticate": "Signature"},
    )
    if not x_bids_user or not x_bids_timestamp or not x_bids_signature:
        raise unauthorized

    try:
        timestamp = int(x_bids_timestamp)
    except (TypeError, ValueError):
        raise unauthorized

    if abs(time.time() - timestamp) > SIGNATURE_WINDOW_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Request signature expired. Reload the page and try again.",
        )

    owner = canonical_email(x_bids_user)
    if not is_valid_email(owner):
        raise unauthorized

    expected = sign_message(owner, x_bids_timestamp)
    if not hmac.compare_digest(expected, x_bids_signature.strip().lower()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Request signature is not valid.",
        )
    return owner


def require_user(
    x_bids_user: str | None = Header(default=None),
    x_bids_timestamp: str | None = Header(default=None),
    x_bids_signature: str | None = Header(default=None),
) -> str:
    """FastAPI dependency: returns the verified owner, or raises 401."""
    return verify_signature(x_bids_user, x_bids_timestamp, x_bids_signature)


# ─── Passwords ────────────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algorithm, iterations, salt, digest = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt),
            int(iterations),
        ).hex()
        return hmac.compare_digest(candidate, digest)
    except (ValueError, TypeError):
        return False
