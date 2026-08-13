"""Org-scoped CRUD for connections, plus decrypt-at-call-time secret access.

Every query here goes through `app_scoped_connection`, never a bare pool
connection — that is what makes RLS's org isolation apply. `ConnectionOut`
rows never include the four ciphertext/wrap columns; only
`get_connection_secrets` reads them, and only to hand back a short-lived,
in-memory, never-cached, never-logged plaintext object for a connector to
consume immediately.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backend.connections.schemas import ConnectionOut, ConnectionSecretFields
from backend.crypto.envelope import Envelope, decrypt_secret, encrypt_secret
from backend.db.local_kek import get_kek
from backend.db.sqlite import app_scoped_connection
from backend.settings import get_app_settings

_COLUMNS = (
    "id, name, kind, base_url, service, sap_client, auth_type, environment, enabled, "
    "ca_bundle_pem, skip_tls_verify, "
    "last_tested_at, last_test_status, last_used_at, created_by, created_at, updated_by, updated_at"
)

_TS_FORMAT = "%Y-%m-%d %H:%M:%S"  # matches SQLite's datetime('now') output


def _parse_ts(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    return datetime.strptime(raw, _TS_FORMAT).replace(tzinfo=timezone.utc)


def _row_to_out(row: tuple) -> ConnectionOut:
    return ConnectionOut(
        id=str(row[0]),
        name=row[1],
        kind=row[2],
        base_url=row[3],
        service=row[4],
        sap_client=row[5],
        auth_type=row[6],
        environment=row[7],
        enabled=bool(row[8]),
        ca_bundle_pem=row[9],
        skip_tls_verify=bool(row[10]),
        last_tested_at=_parse_ts(row[11]),
        last_test_status=row[12],
        last_used_at=_parse_ts(row[13]),
        created_by=str(row[14]),
        created_at=_parse_ts(row[15]),
        updated_by=str(row[16]) if row[16] else None,
        updated_at=_parse_ts(row[17]),
    )


def list_connections(org_id: str, kind: str | None = None) -> list[ConnectionOut]:
    with app_scoped_connection(org_id) as conn:
        if kind:
            rows = conn.execute(
                f"select {_COLUMNS} from connections where org_id = ? and kind = ? order by created_at asc",
                (org_id, kind),
            ).fetchall()
        else:
            rows = conn.execute(
                f"select {_COLUMNS} from connections where org_id = ? order by created_at asc",
                (org_id,),
            ).fetchall()
    return [_row_to_out(row) for row in rows]


def get_connection(org_id: str, connection_id: str) -> ConnectionOut | None:
    with app_scoped_connection(org_id) as conn:
        row = conn.execute(
            f"select {_COLUMNS} from connections where org_id = ? and id = ?",
            (org_id, connection_id),
        ).fetchone()
    return _row_to_out(row) if row else None


def create_connection(
    org_id: str,
    user_id: str,
    *,
    name: str,
    kind: str,
    base_url: str,
    service: str,
    sap_client: str | None,
    auth_type: str,
    environment: str,
    enabled: bool,
    ca_bundle_pem: str | None = None,
    skip_tls_verify: bool = False,
    secret: ConnectionSecretFields,
) -> ConnectionOut:
    kek = get_kek()
    envelope = encrypt_secret(secret.model_dump(exclude_none=True), kek)
    kek_key_id = get_app_settings().kek_vault_secret_name
    connection_id = str(uuid.uuid4())

    with app_scoped_connection(org_id) as conn:
        row = conn.execute(
            f"""
            insert into connections (
                id, org_id, name, kind, base_url, service, sap_client, auth_type, environment, enabled,
                ca_bundle_pem, skip_tls_verify,
                secret_ciphertext, secret_nonce, wrapped_dek, dek_nonce, kek_key_id, created_by
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            returning {_COLUMNS}
            """,
            (
                connection_id, org_id, name, kind, base_url, service, sap_client, auth_type, environment, enabled,
                ca_bundle_pem, skip_tls_verify,
                envelope.secret_ciphertext, envelope.secret_nonce, envelope.wrapped_dek, envelope.dek_nonce,
                kek_key_id, user_id,
            ),
        ).fetchone()
        conn.commit()
    return _row_to_out(row)


def update_connection(
    org_id: str,
    user_id: str,
    connection_id: str,
    *,
    name: str | None,
    base_url: str | None,
    service: str | None,
    sap_client: str | None,
    auth_type: str | None,
    environment: str | None,
    enabled: bool | None,
    ca_bundle_pem: str | None = None,
    skip_tls_verify: bool | None = None,
    secret: ConnectionSecretFields | None,
) -> ConnectionOut | None:
    set_clauses: list[str] = []
    values: list[Any] = []

    for col, val in (
        ("name", name),
        ("base_url", base_url),
        ("service", service),
        ("sap_client", sap_client),
        ("auth_type", auth_type),
        ("environment", environment),
        ("enabled", enabled),
        ("ca_bundle_pem", ca_bundle_pem),
        ("skip_tls_verify", skip_tls_verify),
    ):
        if val is not None:
            set_clauses.append(f"{col} = ?")
            values.append(val)

    if secret is not None:
        kek = get_kek()
        envelope = encrypt_secret(secret.model_dump(exclude_none=True), kek)
        set_clauses += ["secret_ciphertext = ?", "secret_nonce = ?", "wrapped_dek = ?", "dek_nonce = ?", "kek_key_id = ?"]
        values += [
            envelope.secret_ciphertext, envelope.secret_nonce, envelope.wrapped_dek, envelope.dek_nonce,
            get_app_settings().kek_vault_secret_name,
        ]

    set_clauses.append("updated_by = ?")
    values.append(user_id)
    set_clauses.append("updated_at = datetime('now')")

    values += [org_id, connection_id]
    with app_scoped_connection(org_id) as conn:
        row = conn.execute(
            f"update connections set {', '.join(set_clauses)} where org_id = ? and id = ? returning {_COLUMNS}",
            values,
        ).fetchone()
        conn.commit()
    return _row_to_out(row) if row else None


def record_test_result(org_id: str, connection_id: str, success: bool, message: str) -> None:
    with app_scoped_connection(org_id) as conn:
        conn.execute(
            """
            update connections
            set last_tested_at = datetime('now'), last_test_status = ?, last_test_message = ?
            where org_id = ? and id = ?
            """,
            ("success" if success else "failure", message, org_id, connection_id),
        )
        conn.commit()


def delete_connection(org_id: str, connection_id: str) -> bool:
    with app_scoped_connection(org_id) as conn:
        result = conn.execute(
            "delete from connections where org_id = ? and id = ?",
            (org_id, connection_id),
        )
        conn.commit()
    return result.rowcount > 0


@dataclass(frozen=True)
class ConnectionSecrets:
    kind: str
    base_url: str
    service: str
    sap_client: str | None
    auth_type: str
    ca_bundle_pem: str | None
    skip_tls_verify: bool
    secret: dict


def get_connection_secrets(org_id: str, connection_id: str) -> ConnectionSecrets:
    """Decrypt-at-call-time: fetch, decrypt, and hand back a short-lived,
    in-memory object for a connector constructor to consume immediately.
    Never cache, log, or persist the returned secret.
    """
    with app_scoped_connection(org_id) as conn:
        row = conn.execute(
            """
            select kind, base_url, service, sap_client, auth_type, ca_bundle_pem, skip_tls_verify,
                   secret_ciphertext, secret_nonce, wrapped_dek, dek_nonce, kek_key_id
            from connections where org_id = ? and id = ?
            """,
            (org_id, connection_id),
        ).fetchone()
        if row is not None:
            conn.execute(
                "update connections set last_used_at = datetime('now') where org_id = ? and id = ?",
                (org_id, connection_id),
            )
            conn.commit()

    if row is None:
        raise LookupError(f"connection {connection_id} not found for this organization")

    kek = get_kek(row[11])
    envelope = Envelope(secret_ciphertext=row[7], secret_nonce=row[8], wrapped_dek=row[9], dek_nonce=row[10])
    secret = decrypt_secret(envelope, kek)
    return ConnectionSecrets(
        kind=row[0], base_url=row[1], service=row[2], sap_client=row[3], auth_type=row[4],
        ca_bundle_pem=row[5], skip_tls_verify=bool(row[6]), secret=secret,
    )
