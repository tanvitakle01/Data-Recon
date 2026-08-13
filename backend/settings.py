"""Environment-driven configuration for auth, sessions, and connection
encryption. Kept separate from :mod:`backend.recon_engine.config`, which is
scoped to the reconciliation engine itself.

Same convention as the rest of the app: plain ``os.environ.get()``, no
pydantic-settings, resolved once and cached.

Environment variables
----------------------
SUPABASE_URL                  Supabase project URL, e.g. https://xxxx.supabase.co
SUPABASE_ANON_KEY              Anon/public key — used only for Supabase Auth calls
                               (signup/signin/password-reset) that don't need
                               elevated privilege.
SUPABASE_SERVICE_ROLE_KEY       Service-role key. Used ONLY for org creation at
                               signup and Vault access (see backend/db/vault.py,
                               backend/db/postgres.py) — never for normal
                               request-scoped queries, since it bypasses RLS.
DATABASE_URL_APP                Postgres DSN for the `app_backend` role (RLS
                               enforced). Used for all normal request-scoped
                               reads/writes.
DATABASE_URL_ADMIN              Postgres DSN with service_role/postgres
                               privilege. Used only where DATABASE_URL_APP's
                               RLS-scoped role cannot do the job (org creation,
                               Vault reads).
KEK_VAULT_SECRET_NAME            Name of the Vault secret holding the current
                               KEK. Default: "connections_kek_v1".
SESSION_COOKIE_NAME               Default: "dr_session".
SESSION_TTL_HOURS                  Default: 24.
FRONTEND_URL                        Origin the frontend is served from — used
                               to build the password-reset redirect link.
                               Default: "http://localhost:5173".
SQLITE_PATH                    Local-dev SQLite file backing auth/connections
                               while Supabase is swapped out for local dev
                               (see backend/db/sqlite.py). Default:
                               "backend/local.db". Not used when the
                               Supabase/Postgres path is wired back in.
LOCAL_KEK_PATH                  Local-dev KEK file, replacing Supabase Vault
                               (see backend/db/local_kek.py). Default:
                               "backend/.local_kek". Keep out of version
                               control.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class AppSettings:
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    database_url_app: str
    database_url_admin: str
    kek_vault_secret_name: str
    session_cookie_name: str
    session_ttl_hours: int
    frontend_url: str
    sqlite_path: str
    local_kek_path: str


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    return AppSettings(
        supabase_url=os.environ.get("SUPABASE_URL", ""),
        supabase_anon_key=os.environ.get("SUPABASE_ANON_KEY", ""),
        supabase_service_role_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
        database_url_app=os.environ.get("DATABASE_URL_APP", ""),
        database_url_admin=os.environ.get("DATABASE_URL_ADMIN", ""),
        kek_vault_secret_name=os.environ.get("KEK_VAULT_SECRET_NAME", "connections_kek_v1"),
        session_cookie_name=os.environ.get("SESSION_COOKIE_NAME", "dr_session"),
        session_ttl_hours=max(1, _int_env("SESSION_TTL_HOURS", 24)),
        frontend_url=os.environ.get("FRONTEND_URL", "http://localhost:5173"),
        sqlite_path=os.environ.get("SQLITE_PATH", str(_BACKEND_DIR / "local.db")),
        local_kek_path=os.environ.get("LOCAL_KEK_PATH", str(_BACKEND_DIR / ".local_kek")),
    )


def reset_app_settings_cache() -> None:
    get_app_settings.cache_clear()
