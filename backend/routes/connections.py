"""Connections CRUD + Test Connection.

Every response model here is `ConnectionOut` or `TestConnectionResult`,
which by construction exclude every secret/ciphertext field (see
backend/connections/schemas.py). No route in this file may add a field that
carries plaintext or ciphertext secret material into a response — that is
the whole point of this feature.

`/test` requires an authenticated session (so this endpoint can't be used as
an open relay to probe arbitrary hosts) but does not persist anything — it
only returns a signed proof token, consumed by create/update below, which
also require an authenticated, org-scoped session.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.auth.dependencies import CurrentUser, get_current_user
from backend.connections import live_test, store
from backend.connections.schemas import (
    ConnectionCreate,
    ConnectionOut,
    ConnectionUpdate,
    TestConnectionRequest,
    TestConnectionResult,
)
from backend.connections.test_token import fingerprint_for, issue_test_token, verify_test_token

logger = logging.getLogger("recon.connections")

router = APIRouter(prefix="/api/connections", tags=["connections"])


@router.get("")
def list_connections(
    kind: str | None = None, user: CurrentUser = Depends(get_current_user)
) -> list[ConnectionOut]:
    return store.list_connections(user.org_id, kind)


@router.get("/{connection_id}")
def get_connection(connection_id: str, user: CurrentUser = Depends(get_current_user)) -> ConnectionOut:
    conn = store.get_connection(user.org_id, connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found.")
    return conn


@router.post("/test")
def test_connection(
    req: TestConnectionRequest, _user: CurrentUser = Depends(get_current_user)
) -> TestConnectionResult:
    success, message = live_test.test_connection(
        kind=req.kind,
        base_url=req.base_url,
        service=req.service,
        sap_client=req.sap_client,
        auth_type=req.auth_type,
        ca_bundle_pem=req.ca_bundle_pem,
        skip_tls_verify=req.skip_tls_verify,
        secret=req.secret,
    )
    if not success:
        return TestConnectionResult(success=False, message=message, test_token=None)

    fp = fingerprint_for(
        req.kind, req.base_url, req.service, req.sap_client, req.auth_type, req.secret,
        req.ca_bundle_pem, req.skip_tls_verify,
    )
    return TestConnectionResult(success=True, message=message, test_token=issue_test_token(fp))


@router.post("")
def create_connection(req: ConnectionCreate, user: CurrentUser = Depends(get_current_user)) -> ConnectionOut:
    fp = fingerprint_for(
        req.kind, req.base_url, req.service, req.sap_client, req.auth_type, req.secret,
        req.ca_bundle_pem, req.skip_tls_verify,
    )
    if not verify_test_token(req.test_token, fp):
        raise HTTPException(
            status_code=400,
            detail="Test Connection must succeed with these exact details before saving.",
        )
    try:
        return store.create_connection(
            user.org_id,
            user.user_id,
            name=req.name,
            kind=req.kind,
            base_url=req.base_url,
            service=req.service,
            sap_client=req.sap_client,
            auth_type=req.auth_type,
            environment=req.environment,
            enabled=req.enabled,
            ca_bundle_pem=req.ca_bundle_pem,
            skip_tls_verify=req.skip_tls_verify,
            secret=req.secret,
        )
    except Exception:
        logger.exception("connection creation failed for org %s", user.org_id)
        raise HTTPException(
            status_code=400, detail="Could not save this connection — check the name isn't already used."
        )


@router.put("/{connection_id}")
def update_connection(
    connection_id: str, req: ConnectionUpdate, user: CurrentUser = Depends(get_current_user)
) -> ConnectionOut:
    if req.secret is not None:
        existing = store.get_connection(user.org_id, connection_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Connection not found.")
        # ca_bundle_pem/skip_tls_verify are taken as sent in THIS request, not
        # merged with the existing row — the fingerprint must match exactly
        # what /test just verified, and the frontend resends the current form
        # values (not "existing") on both the test and the save call.
        fp = fingerprint_for(
            existing.kind,
            req.base_url or existing.base_url,
            req.service or existing.service,
            req.sap_client if req.sap_client is not None else existing.sap_client,
            req.auth_type or existing.auth_type,
            req.secret,
            req.ca_bundle_pem,
            bool(req.skip_tls_verify),
        )
        if not verify_test_token(req.test_token, fp):
            raise HTTPException(
                status_code=400,
                detail="Test Connection must succeed with these exact details before saving.",
            )

    updated = store.update_connection(
        user.org_id,
        user.user_id,
        connection_id,
        name=req.name,
        base_url=req.base_url,
        service=req.service,
        sap_client=req.sap_client,
        auth_type=req.auth_type,
        environment=req.environment,
        enabled=req.enabled,
        ca_bundle_pem=req.ca_bundle_pem,
        skip_tls_verify=req.skip_tls_verify,
        secret=req.secret,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Connection not found.")
    return updated


@router.delete("/{connection_id}")
def delete_connection(connection_id: str, user: CurrentUser = Depends(get_current_user)) -> dict[str, bool]:
    deleted = store.delete_connection(user.org_id, connection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Connection not found.")
    return {"ok": True}
