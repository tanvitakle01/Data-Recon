import os
import sys
import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote

import requests

# Ensure repo root is on sys.path so `import backend...` works when running
# this file directly.
_THIS_DIR = os.path.dirname(__file__)
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.API_conn.config.config_loader import load_config


@dataclass
class EntityTestResult:
    entity_set: str
    url: str
    status_code: int
    outcome: str  # "OK", "UNAUTHORIZED", "FORBIDDEN", "NOT_FOUND", "OTHER_ERROR"
    content_type: str | None
    response_snippet: str


def _service_base_url(cfg: dict) -> str:
    # Must match working test_auth.py
    return (
        f"{cfg['base_url']}"
        f"/sap/opu/odata/sap/"
        f"{cfg['service']}"
    )


def extract_entity_sets(metadata_xml: str) -> list[str]:
    # EntitySet Name="..." occurrences
    names = re.findall(r'<EntitySet[^>]*Name="([^"]+)"', metadata_xml)
    # Deduplicate while preserving order
    seen = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def classify_status(status_code: int) -> str:
    if status_code == 200:
        return "OK"
    if status_code in (401,):
        return "UNAUTHORIZED"
    if status_code in (403,):
        return "FORBIDDEN"
    if status_code in (404,):
        return "NOT_FOUND"
    return "OTHER_ERROR"


def fetch_metadata(session: requests.Session, metadata_url: str, auth: tuple[str, str], verify: bool) -> str:
    r = session.get(metadata_url, auth=auth, verify=verify, timeout=60)
    print(f"$metadata -> {r.status_code} | {r.headers.get('content-type')}")
    r.raise_for_status()
    return r.text


def test_entity_sets(
    session: requests.Session,
    service_base: str,
    entity_sets: Iterable[str],
    auth: tuple[str, str],
    verify: bool,
) -> list[EntityTestResult]:
    results: list[EntityTestResult] = []

    headers = {
        # Try JSON first for easier parsing.
        "Accept": "application/json",
    }

    for entity_set in entity_sets:
        # EntitySet name can contain special chars; keep safe.
        data_url = f"{service_base}/{quote(entity_set, safe='')}?$top=1"

        try:
            r = session.get(data_url, auth=auth, headers=headers, verify=verify, timeout=60)
            snippet = r.text[:500] if r.text else ""
            results.append(
                EntityTestResult(
                    entity_set=entity_set,
                    url=data_url,
                    status_code=r.status_code,
                    outcome=classify_status(r.status_code),
                    content_type=r.headers.get("content-type"),
                    response_snippet=snippet,
                )
            )
        except requests.RequestException as e:
            results.append(
                EntityTestResult(
                    entity_set=entity_set,
                    url=data_url,
                    status_code=-1,
                    outcome="OTHER_ERROR",
                    content_type=None,
                    response_snippet=str(e)[:500],
                )
            )

    return results


def main() -> int:
    cfg_all = load_config()
    if "s4" not in cfg_all:
        raise RuntimeError("Missing 's4' in sap_config.yaml")

    cfg = cfg_all["s4"]
    if not cfg.get("base_url") or not cfg.get("service"):
        raise RuntimeError("Incomplete s4 config in sap_config.yaml")

    verify = False  # matches your working test_auth.py

    service_base = _service_base_url(cfg)
    metadata_url = f"{service_base}/$metadata"

    auth = (cfg["username"], cfg["password"])

    session = requests.Session()

    metadata_xml = fetch_metadata(session, metadata_url, auth=auth, verify=verify)
    entity_sets = extract_entity_sets(metadata_xml)

    print(f"Discovered {len(entity_sets)} EntitySets")
    print("First 30 EntitySets:")
    print(entity_sets[:30])

    results = test_entity_sets(session, service_base, entity_sets, auth=auth, verify=verify)

    counts: dict[str, int] = {}
    for r in results:
        counts[r.outcome] = counts.get(r.outcome, 0) + 1

    print("\n=== EntitySet Test Summary ===")
    for k in sorted(counts.keys()):
        print(f"{k}: {counts[k]}")

    failures = [r for r in results if r.status_code != 200]
    if failures:
        print("\n=== Failures (non-200) ===")
        for r in failures[:50]:
            print(f"\nEntitySet: {r.entity_set}")
            print(f"URL: {r.url}")
            print(f"Status: {r.status_code} ({r.outcome})")
            if r.content_type:
                print(f"Content-Type: {r.content_type}")
            if r.response_snippet:
                print(f"Response (first 500 chars): {r.response_snippet}")

    ok = any(r.status_code == 200 for r in results)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

