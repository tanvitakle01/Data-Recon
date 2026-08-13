"""Direct REST calls to Supabase Auth (GoTrue) rather than the `supabase-py`
client. `supabase-py`'s `Client.auth` keeps the current session as instance
state, and reusing one shared client across concurrent requests would risk
one user's request observing another's in-flight session — not something a
multi-request server should carry as ambient risk. Every function here is
stateless: request in, JSON out.

Supabase's own access/refresh tokens are consumed HERE and never persisted or
returned, with one narrow, documented exception in
:func:`confirm_password_reset`. `backend/auth/sessions.py` mints the app's
own opaque session instead of using anything Supabase issues.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

from backend.settings import get_app_settings

_TIMEOUT_S = 15


class SupabaseAuthError(Exception):
    """Any Supabase Auth failure. Callers must render a generic, caller-facing
    message — never this exception's text, which can leak whether an email
    is registered."""


@dataclass(frozen=True)
class SupabaseUser:
    id: str
    email: str
    full_name: str | None


@dataclass(frozen=True)
class SupabaseUserProfile:
    email: str
    full_name: str | None


def _headers() -> dict[str, str]:
    settings = get_app_settings()
    return {"apikey": settings.supabase_anon_key, "Content-Type": "application/json"}


def sign_up(email: str, password: str, full_name: str) -> SupabaseUser:
    settings = get_app_settings()
    resp = requests.post(
        f"{settings.supabase_url}/auth/v1/signup",
        json={"email": email, "password": password, "data": {"full_name": full_name}},
        headers=_headers(),
        timeout=_TIMEOUT_S,
    )
    if resp.status_code >= 400:
        raise SupabaseAuthError(f"signup failed ({resp.status_code})")
    user = resp.json().get("user") or {}
    user_id = user.get("id")
    if not user_id:
        raise SupabaseAuthError("signup response missing user id")
    return SupabaseUser(id=user_id, email=user.get("email") or email, full_name=full_name)


def sign_in(email: str, password: str) -> SupabaseUser:
    settings = get_app_settings()
    resp = requests.post(
        f"{settings.supabase_url}/auth/v1/token?grant_type=password",
        json={"email": email, "password": password},
        headers=_headers(),
        timeout=_TIMEOUT_S,
    )
    if resp.status_code >= 400:
        raise SupabaseAuthError(f"signin failed ({resp.status_code})")
    body = resp.json()
    user = body.get("user") or {}
    user_id = user.get("id")
    if not user_id:
        raise SupabaseAuthError("signin response missing user id")
    full_name = (user.get("user_metadata") or {}).get("full_name")
    # body["access_token"] / body["refresh_token"] are intentionally dropped
    # here — they never leave this function.
    return SupabaseUser(id=user_id, email=user.get("email") or email, full_name=full_name)


def request_password_reset(email: str, redirect_to: str) -> None:
    """Fire-and-forget: never raises, so the caller responds identically
    whether the email exists, is malformed-but-parseable, or the call to
    Supabase itself failed — that symmetry is what prevents email enumeration.
    """
    settings = get_app_settings()
    try:
        requests.post(
            f"{settings.supabase_url}/auth/v1/recover",
            params={"redirect_to": redirect_to},
            json={"email": email},
            headers=_headers(),
            timeout=_TIMEOUT_S,
        )
    except requests.RequestException:
        pass


def confirm_password_reset(access_token: str, new_password: str) -> None:
    """Apply a new password using the short-lived recovery access_token that
    Supabase's password-reset email link hands back to the frontend.

    Narrow, documented exception to "Supabase tokens never reach the
    browser": Supabase's hosted recovery email inherently redirects the
    user's browser to a URL carrying this token — there is no fully
    server-side alternative with Supabase's built-in email flow. The token
    is used exactly once, here, to authorize this single password change,
    and is never turned into this app's session or stored anywhere.
    """
    settings = get_app_settings()
    resp = requests.put(
        f"{settings.supabase_url}/auth/v1/user",
        json={"password": new_password},
        headers={**_headers(), "Authorization": f"Bearer {access_token}"},
        timeout=_TIMEOUT_S,
    )
    if resp.status_code >= 400:
        raise SupabaseAuthError(f"password reset confirm failed ({resp.status_code})")


def get_user_profile(user_id: str) -> SupabaseUserProfile:
    """Admin lookup by user id — requires the service_role key.

    This is Supabase's own Auth admin API, unrelated to our Postgres RLS
    boundary; it never touches the `connections`/`organizations` tables.
    """
    settings = get_app_settings()
    resp = requests.get(
        f"{settings.supabase_url}/auth/v1/admin/users/{user_id}",
        headers={
            "apikey": settings.supabase_service_role_key,
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
        },
        timeout=_TIMEOUT_S,
    )
    if resp.status_code >= 400:
        raise SupabaseAuthError(f"user profile lookup failed ({resp.status_code})")
    body = resp.json()
    full_name = (body.get("user_metadata") or {}).get("full_name")
    return SupabaseUserProfile(email=body.get("email") or "", full_name=full_name)
