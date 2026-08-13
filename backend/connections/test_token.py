"""Short-lived proof token that ties a successful Test Connection to the
exact credentials being saved — this is what makes "save is blocked on
failure" a server-enforced rule rather than a client-side-only guard. A
client cannot test with valid credentials and then swap in different ones
before calling create/update, because the token is signed over a fingerprint
of every field (including the secret) that was actually tested.

Signed with the KEK itself rather than a separate provisioned secret — the
token only needs to be unforgeable by a client, not to protect anything the
KEK doesn't already protect, so introducing a second secret would add
operational surface for no security benefit.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from backend.connections.schemas import ConnectionSecretFields
from backend.db.local_kek import get_kek

_TTL_SECONDS = 300


def fingerprint_for(
    kind: str,
    base_url: str,
    service: str,
    sap_client: str | None,
    auth_type: str,
    secret: ConnectionSecretFields,
    ca_bundle_pem: str | None = None,
    skip_tls_verify: bool = False,
) -> str:
    payload = json.dumps(
        {
            "kind": kind,
            "base_url": base_url,
            "service": service,
            "sap_client": sap_client,
            "auth_type": auth_type,
            "secret": secret.model_dump(exclude_none=True),
            "ca_bundle_pem": ca_bundle_pem,
            "skip_tls_verify": skip_tls_verify,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def issue_test_token(fingerprint: str) -> str:
    payload = json.dumps({"fp": fingerprint, "exp": time.time() + _TTL_SECONDS}).encode("utf-8")
    sig = hmac.new(get_kek(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload).decode() + "." + base64.urlsafe_b64encode(sig).decode()


def verify_test_token(token: str | None, fingerprint: str) -> bool:
    if not token or "." not in token:
        return False
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        payload = base64.urlsafe_b64decode(payload_b64)
        sig = base64.urlsafe_b64decode(sig_b64)
    except Exception:  # noqa: BLE001 - malformed token, treat as invalid
        return False

    expected_sig = hmac.new(get_kek(), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected_sig):
        return False

    try:
        data = json.loads(payload)
    except Exception:  # noqa: BLE001
        return False
    return data.get("fp") == fingerprint and data.get("exp", 0) >= time.time()
