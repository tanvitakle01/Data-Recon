import os
import sys
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

import requests
import urllib3

# Ensure repo root is on sys.path so `import backend...` works when running
_THIS_DIR = os.path.dirname(__file__)
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.API_conn.config.config_loader import load_config


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


@dataclass
class RequestLog:
    label: str
    url: str
    method: str
    status_code: int
    auth_method: str
    sap_client_header_sent: bool
    response_headers: dict
    body_snippet: str


def build_service_base_url(cfg: dict) -> str:
    # Must match the known-good construction used in other diagnostics/tests
    return (
        f"{cfg['base_url']}"
        f"/sap/opu/odata/sap/"
        f"{cfg['service']}"
    )


def extract_basic_auth_method() -> str:
    # We always use requests' (username, password) auth tuple.
    return "requests.auth=(username,password) -> Authorization: Basic"


def do_get(
    session: requests.Session,
    label: str,
    url: str,
    *,
    auth: tuple[str, str],
    headers: dict,
    verify: bool,
    timeout: int,
) -> RequestLog:
    resp = session.get(
        url,
        auth=auth,
        headers=headers,
        verify=verify,
        timeout=timeout,
        allow_redirects=True,
    )

    content_type = resp.headers.get("content-type")
    snippet = (resp.text or "")[:1000]

    return RequestLog(
        label=label,
        url=url,
        method="GET",
        status_code=resp.status_code,
        auth_method=extract_basic_auth_method(),
        sap_client_header_sent=("SAP-Client" in headers),
        response_headers=dict(resp.headers),
        body_snippet=snippet,
    )


def print_log(log: RequestLog) -> None:
    print("=" * 120)
    print(f"[{log.label}]")
    print(f"URL: {log.url}")
    print(f"HTTP Method: {log.method}")
    print(f"Status: {log.status_code}")
    print(f"Auth method used: {log.auth_method}")
    print(f"SAP-Client header sent: {log.sap_client_header_sent}")

    # Include WWW-Authenticate if present (highly relevant for root cause)
    wa = log.response_headers.get("WWW-Authenticate")
    if wa:
        print(f"WWW-Authenticate: {wa}")

    print("Response headers:")
    for k in sorted(log.response_headers.keys()):
        print(f"  {k}: {log.response_headers[k]}")

    print("Response body (first 1000 chars):")
    print(log.body_snippet)


def main() -> int:
    cfg_all = load_config()
    if "s4" not in cfg_all:
        raise RuntimeError("Missing 's4' config section in backend/API_conn/config/sap_config.yaml")

    cfg = cfg_all["s4"]
    if not cfg.get("base_url") or not cfg.get("service"):
        raise RuntimeError("Incomplete s4 config: expected base_url and service")

    # Match existing working diagnostics (disable SSL verify).
    verify = False

    base_service = build_service_base_url(cfg)
    auth = (cfg["username"], cfg["password"])

    # Optional header: SAP-Client
    common_headers_xml = {
        "Accept": "application/xml",
    }
    common_headers_json = {
        "Accept": "application/json",
    }

    sap_client = cfg.get("client")
    if sap_client:
        common_headers_xml["SAP-Client"] = sap_client
        common_headers_json["SAP-Client"] = sap_client

    # 1) Service root
    service_root_url = f"{base_service}/"

    # 2) $metadata
    metadata_url = f"{base_service}/$metadata"

    # 3) Entity sets
    entity_sets = [
        "A_SalesOrder",
        "A_SalesOrderItem",
        "A_SalesOrderScheduleLine",
    ]

    session = requests.Session()

    logs: list[RequestLog] = []

    # Run requests
    logs.append(
        do_get(
            session,
            "SERVICE_ROOT",
            service_root_url,
            auth=auth,
            headers=common_headers_xml,
            verify=verify,
            timeout=60,
        )
    )

    logs.append(
        do_get(
            session,
            "$METADATA",
            metadata_url,
            auth=auth,
            headers=common_headers_xml,
            verify=verify,
            timeout=60,
        )
    )

    for es in entity_sets:
        # OData V2: <EntitySet>?$top=1
        # Quote in case of special chars (defensive).
        es_enc = quote(es, safe="")
        url = f"{base_service}/{es_enc}?$top=1"
        logs.append(
            do_get(
                session,
                f"ENTITYSET_{es}",
                url,
                auth=auth,
                headers=common_headers_json,
                verify=verify,
                timeout=60,
            )
        )

    # Print
    print("\nCONFIG (sanitized):")
    print(f"  base_url: {cfg.get('base_url')}")
    print(f"  service: {cfg.get('service')}")
    print(f"  username: {cfg.get('username')}")
    print(f"  client config present: {bool(cfg.get('client'))}")

    for log in logs:
        print_log(log)

    failures = [l for l in logs if l.status_code != 200]
    print("\n" + "-" * 120)
    if failures:
        print("Non-200 results:")
        for f in failures:
            print(f"  {f.label}: {f.status_code} -> {f.url}")
        return 2

    print("All tested endpoints returned HTTP 200")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

