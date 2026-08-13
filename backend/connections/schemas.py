from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ConnectionSecretFields(BaseModel):
    """Write-only. Present on create, and on update ONLY when replacing the
    secret. There is deliberately no corresponding field on any response
    model — the plaintext secret must never round-trip back to a client."""

    username: str | None = None
    password: str | None = None
    client_id: str | None = None
    client_secret: str | None = None


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1)
    kind: str  # "s4" | "ibp"
    base_url: str
    service: str
    sap_client: str | None = None
    auth_type: str = "basic"  # "basic" | "oauth2_client_credentials" | "x509"
    environment: str = "dev"  # "dev" | "qa" | "prod"
    enabled: bool = True
    # CA bundle is not a secret — a PEM-encoded certificate (chain), needed
    # for hosts behind a corporate/self-signed CA that isn't in the default
    # trust store. skip_tls_verify is the explicit, non-default escape hatch;
    # false by default so verification is on unless a user opts out.
    ca_bundle_pem: str | None = None
    skip_tls_verify: bool = False
    secret: ConnectionSecretFields
    test_token: str


class ConnectionUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    service: str | None = None
    sap_client: str | None = None
    auth_type: str | None = None
    environment: str | None = None
    enabled: bool | None = None
    ca_bundle_pem: str | None = None
    skip_tls_verify: bool | None = None
    secret: ConnectionSecretFields | None = None
    test_token: str | None = None


class ConnectionOut(BaseModel):
    """Never includes any secret or ciphertext field — that is the entire
    point of this model existing separately from the DB row."""

    id: str
    name: str
    kind: str
    base_url: str
    service: str
    sap_client: str | None
    auth_type: str
    environment: str
    enabled: bool
    ca_bundle_pem: str | None
    skip_tls_verify: bool
    last_tested_at: datetime | None
    last_test_status: str | None
    last_used_at: datetime | None
    created_by: str
    created_at: datetime
    updated_by: str | None
    updated_at: datetime


class TestConnectionRequest(BaseModel):
    kind: str
    base_url: str
    service: str
    sap_client: str | None = None
    auth_type: str = "basic"
    ca_bundle_pem: str | None = None
    skip_tls_verify: bool = False
    secret: ConnectionSecretFields


class TestConnectionResult(BaseModel):
    success: bool
    message: str
    test_token: str | None = None
