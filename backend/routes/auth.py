"""Auth routes: signup, signin, signout, current user, password reset.

Every failure response is a generic, non-specific message — this satisfies
"never reveal whether an email is registered" for sign-in and password
reset, and keeps signup's error surface uniformly generic too. Full
exception detail is logged server-side only, via ``logger.exception``, and
only ever includes the email address, never the password (the request body
itself is never logged — see ``main.py``'s diagnostic 422 handler, which is
explicitly scoped to skip this router).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from backend.auth import local_client as supabase_client
from backend.auth.dependencies import CurrentUser, get_current_user
from backend.auth.local_client import SupabaseAuthError
from backend.auth.schemas import (
    CurrentUserResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequestBody,
    SignInRequest,
    SignUpRequest,
)
from backend.auth.sessions import mint_session, revoke_session
from backend.db.sqlite import admin_connection, app_scoped_connection, user_scoped_connection
from backend.settings import get_app_settings

logger = logging.getLogger("recon.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])

_GENERIC_SIGNIN_ERROR = "Invalid email or password."
_GENERIC_SIGNUP_ERROR = "Unable to create your account. Please check your details and try again."


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    user_agent = request.headers.get("user-agent")
    ip = request.client.host if request.client else None
    return user_agent, ip


def _set_session_cookie(response: Response, raw_token: str) -> None:
    settings = get_app_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )


@router.post("/signup")
def signup(req: SignUpRequest, request: Request, response: Response) -> CurrentUserResponse:
    try:
        user = supabase_client.sign_up(req.email, req.password, req.full_name)
    except SupabaseAuthError:
        logger.exception("signup failed for %s", req.email)
        raise HTTPException(status_code=400, detail=_GENERIC_SIGNUP_ERROR)

    try:
        org_id = str(uuid.uuid4())
        with admin_connection() as conn:
            conn.execute(
                "insert into organizations (id, name, created_by) values (?, ?, ?)",
                (org_id, req.organization_name, user.id),
            )
            conn.execute(
                "insert into org_members (org_id, user_id, role) values (?, ?, 'owner')",
                (org_id, user.id),
            )
            conn.commit()
    except Exception:
        logger.exception("organization creation failed after signup for %s", req.email)
        raise HTTPException(
            status_code=500, detail="Account created but organization setup failed. Please contact support."
        )

    user_agent, ip = _client_meta(request)
    raw_token = mint_session(user.id, org_id, user_agent, ip)
    _set_session_cookie(response, raw_token)

    return CurrentUserResponse(email=user.email, full_name=user.full_name, organization_name=req.organization_name)


@router.post("/signin")
def signin(req: SignInRequest, request: Request, response: Response) -> CurrentUserResponse:
    try:
        user = supabase_client.sign_in(req.email, req.password)
    except SupabaseAuthError:
        logger.info("signin rejected for %s", req.email)
        raise HTTPException(status_code=401, detail=_GENERIC_SIGNIN_ERROR)

    with user_scoped_connection(user.id) as conn:
        row = conn.execute(
            "select org_id from org_members where user_id = ? order by created_at asc limit 1",
            (user.id,),
        ).fetchone()
    if row is None:
        logger.error("signin succeeded for %s but no organization membership found", req.email)
        raise HTTPException(status_code=401, detail=_GENERIC_SIGNIN_ERROR)
    org_id = str(row[0])

    with app_scoped_connection(org_id) as conn:
        org_row = conn.execute("select name from organizations where id = ?", (org_id,)).fetchone()
    organization_name = org_row[0] if org_row else ""

    user_agent, ip = _client_meta(request)
    raw_token = mint_session(user.id, org_id, user_agent, ip)
    _set_session_cookie(response, raw_token)

    return CurrentUserResponse(email=user.email, full_name=user.full_name, organization_name=organization_name)


@router.post("/signout")
def signout(request: Request, response: Response) -> dict[str, bool]:
    settings = get_app_settings()
    raw_token = request.cookies.get(settings.session_cookie_name)
    if raw_token:
        revoke_session(raw_token)
    response.delete_cookie(key=settings.session_cookie_name, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)) -> CurrentUserResponse:
    profile = supabase_client.get_user_profile(user.user_id)
    with app_scoped_connection(user.org_id) as conn:
        org_row = conn.execute("select name from organizations where id = ?", (user.org_id,)).fetchone()
    return CurrentUserResponse(
        email=profile.email,
        full_name=profile.full_name,
        organization_name=org_row[0] if org_row else "",
    )


@router.post("/password-reset/request")
def password_reset_request(req: PasswordResetRequestBody) -> dict[str, bool]:
    settings = get_app_settings()
    redirect_to = f"{settings.frontend_url}/password-reset/confirm"
    supabase_client.request_password_reset(req.email, redirect_to)
    return {"ok": True}


@router.post("/password-reset/confirm")
def password_reset_confirm(req: PasswordResetConfirmRequest) -> dict[str, bool]:
    try:
        supabase_client.confirm_password_reset(req.access_token, req.new_password)
    except SupabaseAuthError:
        logger.exception("password reset confirm failed")
        raise HTTPException(status_code=400, detail="That reset link is invalid or has expired.")
    return {"ok": True}
