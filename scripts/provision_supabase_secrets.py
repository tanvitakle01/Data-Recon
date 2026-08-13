"""Provision the two secrets that must never live in a committed file:

1. The `app_backend` Postgres role's password.
2. The Supabase Vault secret backing the connections KEK.

Run this ONCE, after `supabase/migrations/0001_auth_connections.sql` has
applied (that migration creates `app_backend` with no password and checks
that the Vault extension is enabled, but deliberately does neither secret
step itself — see that file's header comment).

This script generates both secrets in memory, applies them directly against
the database, and never writes either one to disk. The only thing you need
to copy afterward is the `DATABASE_URL_APP` line this script prints — the
KEK itself is never printed, because nothing outside the running application
ever needs to see it.

Usage
-----
    python scripts/provision_supabase_secrets.py

Reads DATABASE_URL_ADMIN from the environment (or backend/.env, using the
same minimal parser backend/main.py already uses — no python-dotenv
dependency). Requires the `psycopg` and `psycopg` package's binary extra,
already in requirements.txt.

Safe to re-run: the `app_backend` password is rotated every time you run it
(printing a fresh DATABASE_URL_APP you must re-save), while an existing
Vault secret of the same name is left untouched and merely reported.
"""

from __future__ import annotations

import argparse
import base64
import os
import secrets
import sys
import urllib.parse
from pathlib import Path

import psycopg
from psycopg import sql

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = REPO_ROOT / "backend" / ".env"
DEFAULT_KEK_SECRET_NAME = "connections_kek_v1"


def _load_env_file(path: Path) -> None:
    """Same minimal parser as backend/main.py's `_load_env_file` — kept
    independent (this script must run standalone, without importing the
    backend package) rather than shared, since the two are one line each."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _rotate_app_backend_password(conn: psycopg.Connection) -> str:
    password = secrets.token_hex(32)  # hex -> no characters need URL-encoding
    conn.execute(sql.SQL("alter role app_backend password {}").format(sql.Literal(password)))
    conn.commit()
    return password


def _ensure_vault_secret(conn: psycopg.Connection, name: str) -> str:
    """Create the KEK in Vault if it doesn't already exist under this name.

    Returns "created" or "already exists" — never the secret value itself,
    in either case.
    """
    existing = conn.execute("select id from vault.secrets where name = %s", (name,)).fetchone()
    if existing is not None:
        return "already exists"

    kek = secrets.token_bytes(32)
    kek_b64 = base64.b64encode(kek).decode("ascii")
    conn.execute(
        "select vault.create_secret(%s, %s, %s)",
        (kek_b64, name, "Connections envelope-encryption KEK, provisioned by provision_supabase_secrets.py"),
    )
    conn.commit()
    return "created"


def _database_url_app(database_url_admin: str, password: str) -> str:
    parsed = urllib.parse.urlsplit(database_url_admin)
    host_port = parsed.hostname or ""
    if parsed.port:
        host_port += f":{parsed.port}"
    new_netloc = f"app_backend:{password}@{host_port}"
    return urllib.parse.urlunsplit((parsed.scheme, new_netloc, parsed.path, parsed.query, parsed.fragment))


def _write_database_url_app(env_path: Path, value: str) -> None:
    if not env_path.is_file():
        return
    lines = env_path.read_text(encoding="utf-8-sig").splitlines()
    out = []
    replaced = False
    for line in lines:
        if line.strip().startswith("DATABASE_URL_APP="):
            out.append(f"DATABASE_URL_APP={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"DATABASE_URL_APP={value}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kek-secret-name",
        default=os.environ.get("KEK_VAULT_SECRET_NAME", DEFAULT_KEK_SECRET_NAME),
        help="Name of the Vault secret to create/check for (default: connections_kek_v1).",
    )
    parser.add_argument(
        "--no-write-env",
        action="store_true",
        help="Print DATABASE_URL_APP instead of writing it into backend/.env.",
    )
    args = parser.parse_args()

    _load_env_file(ENV_PATH)
    database_url_admin = os.environ.get("DATABASE_URL_ADMIN", "").strip()
    if not database_url_admin:
        print("DATABASE_URL_ADMIN is not set (checked environment and backend/.env).", file=sys.stderr)
        return 1

    with psycopg.connect(database_url_admin) as conn:
        password = _rotate_app_backend_password(conn)
        vault_status = _ensure_vault_secret(conn, args.kek_secret_name)

    database_url_app = _database_url_app(database_url_admin, password)

    print("app_backend password rotated.")
    print(f"Vault secret '{args.kek_secret_name}': {vault_status}.")

    if args.no_write_env:
        print("\nDATABASE_URL_APP=" + database_url_app)
    else:
        _write_database_url_app(ENV_PATH, database_url_app)
        print(f"\nDATABASE_URL_APP written to {ENV_PATH}.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
