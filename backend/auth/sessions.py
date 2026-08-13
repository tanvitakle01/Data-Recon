"""The app's own server-owned session store — backs the opaque httpOnly
cookie. Supabase's JWTs never become this session; this module is the only
source of truth for "is this request authenticated."
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backend.db.sqlite import app_connection
from backend.settings import get_app_settings


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    user_id: str
    org_id: str
    expires_at: datetime


_TS_FORMAT = "%Y-%m-%d %H:%M:%S"  # matches SQLite's datetime('now') output, so string comparison sorts correctly


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _format_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(_TS_FORMAT)


def _parse_ts(raw: str) -> datetime:
    return datetime.strptime(raw, _TS_FORMAT).replace(tzinfo=timezone.utc)


def mint_session(user_id: str, org_id: str, user_agent: str | None, ip: str | None) -> str:
    """Create a session row and return the raw opaque token for the cookie.

    The raw token is returned exactly once, here — only its SHA-256 hash is
    ever persisted, so a database dump alone cannot be replayed as a valid
    session.
    """
    settings = get_app_settings()
    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.session_ttl_hours)

    with app_connection() as conn:
        conn.execute(
            """
            insert into sessions (id, user_id, org_id, token_hash, created_at, expires_at, last_seen_at, user_agent, ip)
            values (?, ?, ?, ?, datetime('now'), ?, datetime('now'), ?, ?)
            """,
            (str(uuid.uuid4()), user_id, org_id, _hash(raw_token), _format_ts(expires_at), user_agent, ip),
        )
        conn.commit()
    return raw_token


def verify_session(raw_token: str) -> SessionInfo | None:
    """Look up a session by its cookie token.

    Returns None for missing, expired, or revoked alike — callers must treat
    all three as plain "not authenticated" and never distinguish the reason.
    """
    if not raw_token:
        return None
    with app_connection() as conn:
        row = conn.execute(
            """
            select id, user_id, org_id, expires_at
            from sessions
            where token_hash = ? and revoked_at is null and expires_at > datetime('now')
            """,
            (_hash(raw_token),),
        ).fetchone()
        if row is None:
            return None
        conn.execute("update sessions set last_seen_at = datetime('now') where id = ?", (row["id"],))
        conn.commit()
    return SessionInfo(
        session_id=str(row["id"]),
        user_id=str(row["user_id"]),
        org_id=str(row["org_id"]),
        expires_at=_parse_ts(row["expires_at"]),
    )


def revoke_session(raw_token: str) -> None:
    if not raw_token:
        return
    with app_connection() as conn:
        conn.execute(
            "update sessions set revoked_at = datetime('now') where token_hash = ? and revoked_at is null",
            (_hash(raw_token),),
        )
        conn.commit()
