"""Local-dev replacement for :mod:`backend.auth.supabase_client`.

Matches that module's public surface exactly (`sign_up`, `sign_in`,
`request_password_reset`, `confirm_password_reset`, `get_user_profile`,
`SupabaseUser`, `SupabaseUserProfile`, `SupabaseAuthError`) so
`backend/routes/auth.py` only needs an import-line swap. Backed by the local
`users` table instead of Supabase GoTrue.

Passwords are hashed with stdlib `hashlib.scrypt` (random per-user salt) —
no new dependency, and scrypt is a deliberately slow KDF suitable for
password storage. There's no local email service, so
`request_password_reset` logs the reset link instead of sending it; fine for
a developer's own machine, not meant to go further than that.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backend.db.sqlite import app_connection

logger = logging.getLogger("recon.auth.local")

_RESET_TOKEN_TTL = timedelta(hours=1)
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32


class SupabaseAuthError(Exception):
    """Same contract as the Supabase version: callers must render a
    generic, caller-facing message — never this exception's text."""


@dataclass(frozen=True)
class SupabaseUser:
    id: str
    email: str
    full_name: str | None


@dataclass(frozen=True)
class SupabaseUserProfile:
    email: str
    full_name: str | None


_TS_FORMAT = "%Y-%m-%d %H:%M:%S"  # matches SQLite's datetime('now') output, so string comparison sorts correctly


def _now() -> str:
    return datetime.now(timezone.utc).strftime(_TS_FORMAT)


def _hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN
    )
    return f"{salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    salt_hex, _, digest_hex = stored.partition("$")
    if not digest_hex:
        return False
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    candidate = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN
    )
    return hmac.compare_digest(candidate, expected)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sign_up(email: str, password: str, full_name: str) -> SupabaseUser:
    with app_connection() as conn:
        existing = conn.execute("select id from users where email = ?", (email,)).fetchone()
        if existing is not None:
            raise SupabaseAuthError("email already registered")

        user_id = str(uuid.uuid4())
        conn.execute(
            "insert into users (id, email, password_hash, full_name, created_at) values (?, ?, ?, ?, ?)",
            (user_id, email, _hash_password(password), full_name, _now()),
        )
        conn.commit()
    return SupabaseUser(id=user_id, email=email, full_name=full_name)


def sign_in(email: str, password: str) -> SupabaseUser:
    with app_connection() as conn:
        row = conn.execute(
            "select id, email, password_hash, full_name from users where email = ?", (email,)
        ).fetchone()
    if row is None or not _verify_password(password, row["password_hash"]):
        raise SupabaseAuthError("invalid email or password")
    return SupabaseUser(id=row["id"], email=row["email"], full_name=row["full_name"])


def request_password_reset(email: str, redirect_to: str) -> None:
    """Fire-and-forget, matching the Supabase version's contract: never
    raises, so the caller responds identically whether the email exists or
    not. No email service exists locally, so the reset link is logged
    instead of sent.
    """
    try:
        with app_connection() as conn:
            row = conn.execute("select id from users where email = ?", (email,)).fetchone()
            if row is None:
                return

            raw_token = secrets.token_urlsafe(32)
            expires_at = (datetime.now(timezone.utc) + _RESET_TOKEN_TTL).strftime(_TS_FORMAT)
            conn.execute(
                "insert into password_reset_tokens (id, user_id, token_hash, expires_at, created_at) "
                "values (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), row["id"], _hash_token(raw_token), expires_at, _now()),
            )
            conn.commit()
        logger.info("[local-dev] password reset link for %s: %s?access_token=%s", email, redirect_to, raw_token)
    except Exception:
        logger.exception("local password reset request failed for %s", email)


def confirm_password_reset(access_token: str, new_password: str) -> None:
    token_hash = _hash_token(access_token)
    with app_connection() as conn:
        row = conn.execute(
            "select id, user_id, expires_at, used_at from password_reset_tokens where token_hash = ?",
            (token_hash,),
        ).fetchone()
        if row is None or row["used_at"] is not None or row["expires_at"] < _now():
            raise SupabaseAuthError("reset token invalid or expired")

        conn.execute("update users set password_hash = ? where id = ?", (_hash_password(new_password), row["user_id"]))
        conn.execute("update password_reset_tokens set used_at = ? where id = ?", (_now(), row["id"]))
        conn.commit()


def get_user_profile(user_id: str) -> SupabaseUserProfile:
    with app_connection() as conn:
        row = conn.execute("select email, full_name from users where id = ?", (user_id,)).fetchone()
    if row is None:
        raise SupabaseAuthError("user not found")
    return SupabaseUserProfile(email=row["email"], full_name=row["full_name"])
