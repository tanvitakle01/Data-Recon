"""Lightweight live-system connectivity check for Test Connection.

Deliberately does NOT reuse S4SalesOrderConnector/IBPDemandConnector's fetch
methods (those pull real business data) — this only proves the endpoint and
credentials work, via a cheap OData $metadata request. On failure, returns a
short, sanitized message only — never a stack trace, response body, or
credential fragment. This is the leak pattern that s4_test_preview.py /
ibp_test_preview.py have today (returning `traceback.format_exc()` to the
client) and that this module must not repeat.

TLS verification is ON by default (`verify=True`). A connection whose host
sits behind a corporate/self-signed CA supplies `ca_bundle_pem`, written to a
short-lived temp file and passed as `verify=<path>` — this is the standard
way `requests` accepts a custom trust root. `skip_tls_verify` is the explicit,
non-default escape hatch; when set, the resulting InsecureRequestWarning is
suppressed only for this one deliberately-insecure call (not filtered
globally), since the underlying problem is a genuine choice, not something to
silence app-wide.
"""

from __future__ import annotations

import tempfile
import warnings
from pathlib import Path

import requests
import urllib3

from backend.connections.schemas import ConnectionSecretFields

_TIMEOUT_S = 20


def test_connection(
    *,
    kind: str,
    base_url: str,
    service: str,
    sap_client: str | None,
    auth_type: str,
    ca_bundle_pem: str | None = None,
    skip_tls_verify: bool = False,
    secret: ConnectionSecretFields,
) -> tuple[bool, str]:
    if auth_type != "basic":
        return False, f"Auth type '{auth_type}' is not yet supported for live testing."
    if not secret.username or not secret.password:
        return False, "Username and password are required."

    url = f"{base_url}/sap/opu/odata/sap/{service}/$metadata"
    headers = {"Accept": "application/xml"}
    if sap_client:
        headers["SAP-Client"] = sap_client

    ca_bundle_path: str | None = None
    tmp_file = None
    try:
        if skip_tls_verify:
            verify: bool | str = False
        elif ca_bundle_pem:
            tmp_file = tempfile.NamedTemporaryFile(
                mode="w", suffix=".pem", delete=False, encoding="utf-8"
            )
            tmp_file.write(ca_bundle_pem)
            tmp_file.close()
            ca_bundle_path = tmp_file.name
            verify = ca_bundle_path
        else:
            verify = True

        try:
            if skip_tls_verify:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
                    resp = requests.get(
                        url, auth=(secret.username, secret.password), headers=headers,
                        verify=verify, timeout=_TIMEOUT_S,
                    )
            else:
                resp = requests.get(
                    url, auth=(secret.username, secret.password), headers=headers,
                    verify=verify, timeout=_TIMEOUT_S,
                )
        except requests.exceptions.SSLError:
            if ca_bundle_pem:
                return False, (
                    "Certificate not trusted — the uploaded CA bundle didn't validate this "
                    "host. Double-check it's the correct root/intermediate for this server."
                )
            return False, (
                "Certificate not trusted — this host's certificate isn't in the default trust "
                "store. Upload your organization's CA bundle for this connection."
            )
        except requests.RequestException:
            return False, "Could not reach the host — check the base URL."
    finally:
        if ca_bundle_path:
            Path(ca_bundle_path).unlink(missing_ok=True)

    if resp.status_code == 401:
        return False, "Authentication failed — check the username and password."
    if resp.status_code == 403:
        return False, "Authenticated but not authorized for this service."
    if resp.status_code == 404:
        return False, "Service not found at this base URL — check the service path."
    if resp.status_code >= 400:
        return False, f"Unexpected response from the host (HTTP {resp.status_code})."

    if skip_tls_verify:
        return True, "Connection succeeded. TLS verification is OFF for this connection — not recommended for production."
    return True, "Connection succeeded."
