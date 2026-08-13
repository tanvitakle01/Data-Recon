"""Two Postgres connection pools, deliberately kept separate.

`app_backend` is a role with normal (non-bypass-RLS) grants — used for every
request-scoped query touching organization data. RLS policies key off
`current_setting('app.current_org_id')`, which `app_scoped_connection` sets
per-transaction from the *verified session's* org_id, never from client
input. This makes RLS a real, independently-enforced isolation layer: even a
handler that forgets a `WHERE org_id = ...` clause cannot cross tenants,
because the database role itself is restricted.

`service_role` (via `admin_connection`) bypasses RLS entirely, by Supabase's
own design. It is used only where that's unavoidable: creating a brand-new
organization at signup (no org row exists yet to scope by) and reading
Supabase Vault (`vault.decrypted_secrets` is service_role-only). Do not widen
its use — every additional caller is a hole in the isolation guarantee above.
"""

from __future__ import annotations

import contextlib
from typing import Iterator

import psycopg
from psycopg_pool import ConnectionPool

from backend.settings import get_app_settings

_app_pool: ConnectionPool | None = None
_admin_pool: ConnectionPool | None = None


def _get_app_pool() -> ConnectionPool:
    global _app_pool
    if _app_pool is None:
        settings = get_app_settings()
        _app_pool = ConnectionPool(settings.database_url_app, min_size=1, max_size=10, open=True)
    return _app_pool


def _get_admin_pool() -> ConnectionPool:
    global _admin_pool
    if _admin_pool is None:
        settings = get_app_settings()
        _admin_pool = ConnectionPool(settings.database_url_admin, min_size=1, max_size=5, open=True)
    return _admin_pool


@contextlib.contextmanager
def app_scoped_connection(org_id: str) -> Iterator[psycopg.Connection]:
    """Connection on `app_backend`, org-scoped for one transaction.

    Every route touching `organizations`/`org_members`/`connections` MUST use
    this rather than a bare pool connection.
    """
    pool = _get_app_pool()
    with pool.connection() as conn:
        with conn.transaction():
            conn.execute("SET LOCAL app.current_org_id = %s", (org_id,))
            yield conn


@contextlib.contextmanager
def user_scoped_connection(user_id: str) -> Iterator[psycopg.Connection]:
    """Connection on `app_backend` scoped by user_id rather than org_id.

    For the one lookup that must happen before org_id is known: which org(s)
    a just-authenticated user belongs to, during sign-in. Backed by the
    `org_members_self_lookup` RLS policy, which only permits reading rows for
    this specific user_id — not a blanket bypass.
    """
    pool = _get_app_pool()
    with pool.connection() as conn:
        with conn.transaction():
            conn.execute("SET LOCAL app.current_user_id = %s", (user_id,))
            yield conn


@contextlib.contextmanager
def app_connection() -> Iterator[psycopg.Connection]:
    """Connection on `app_backend` with no org scope set.

    For queries that aren't organization-scoped — session lookup by token
    hash happens before org_id is known. Relies on `sessions`/
    `auth_audit_log`'s backend-only RLS policies, not `app.current_org_id`.
    """
    pool = _get_app_pool()
    with pool.connection() as conn:
        yield conn


@contextlib.contextmanager
def admin_connection() -> Iterator[psycopg.Connection]:
    """Connection with service_role privilege — bypasses RLS.

    Restricted to org creation at signup and Vault reads. See module
    docstring before adding a new caller.
    """
    pool = _get_admin_pool()
    with pool.connection() as conn:
        yield conn
