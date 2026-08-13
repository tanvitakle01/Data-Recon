"""FastAPI Depends() chain for authenticated, org-scoped routes.

This is the first (and, for most routes, only) DI usage in the codebase —
deliberately kept to one canonical chain: get_current_session -> get_current_user
-> require_org. Routes needing org isolation must take `require_org` and pass
its result into `app_scoped_connection` (`backend.db.sqlite` for now, while
local dev runs against SQLite; `backend.db.postgres` once Supabase is wired
back in) — org_id must never be read from request body/query/path instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from backend.auth.sessions import SessionInfo, verify_session
from backend.settings import get_app_settings


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    org_id: str


def get_current_session(request: Request) -> SessionInfo:
    settings = get_app_settings()
    raw_token = request.cookies.get(settings.session_cookie_name)
    session = verify_session(raw_token) if raw_token else None
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return session


def get_current_user(session: SessionInfo = Depends(get_current_session)) -> CurrentUser:
    return CurrentUser(user_id=session.user_id, org_id=session.org_id)


def require_org(user: CurrentUser = Depends(get_current_user)) -> str:
    """The verified session's org_id — the sole trusted source of org scope."""
    return user.org_id
