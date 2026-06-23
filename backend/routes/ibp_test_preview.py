from __future__ import annotations

import json
import traceback
from typing import Any
from urllib.parse import quote

import pandas as pd
import requests
from fastapi import APIRouter, HTTPException

from backend.API_conn.config.config_loader import load_config

router = APIRouter()


def _df_to_payload(df: pd.DataFrame) -> dict[str, Any]:
    if df is None:
        df = pd.DataFrame()

    cols = list(df.columns)
    head = df.head(10)
    preview_records = head.astype(str).to_dict(orient="records")

    return {
        "success": True,
        "count": int(len(df)),
        "columns": cols,
        "preview": preview_records,
        "data": df.fillna("").astype(str).to_dict(orient="records"),
    }


def _try_parse_odata_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Best-effort extraction for OData V2 style: {"d":{"results": [...]}}."""

    if not isinstance(payload, dict):
        return []

    # OData V2
    d = payload.get("d")
    if isinstance(d, dict) and isinstance(d.get("results"), list):
        return d["results"]

    # Some OData variants use {"value": [...]}
    if isinstance(payload.get("value"), list):
        return payload["value"]

    # Otherwise, if payload looks like a single entity
    if d and isinstance(d, dict):
        # If d contains scalar keys, treat as one record
        return [d]

    return []


def _metadata_to_entity_sets(metadata_xml: str) -> list[str]:
    import re

    # Match EntitySet Name="..."
    names = re.findall(r'<EntitySet[^>]*Name="([^"]+)"', metadata_xml)

    out: list[str] = []
    seen = set()
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _pick_best_entity_set(entity_sets: list[str], planning_level: str) -> list[str]:
    """Heuristic: for the given planning level, pick entity sets that look like demand/key figure.

    We cannot guarantee naming; this is intentionally verbose and safe.
    """
    # planning level may appear as a literal in entity set names
    level_l = planning_level.lower()

    scored: list[tuple[float, str]] = []
    for es in entity_sets:
        es_l = es.lower()
        score = 0.0

        if "dayprodlocdemand" in es_l or "dayprod" in es_l:
            score += 5.0
        if level_l in es_l:
            score += 10.0
        if "demand" in es_l:
            score += 2.0
        if "salesorder" in es_l or "sales" in es_l:
            score += 2.0
        if "i_salesorderrequest" in es_l or "keyfigure" in es_l:
            score += 2.0

        # Prefer schedule/transaction-like sets
        if "request" in es_l or "demand" in es_l:
            score += 1.0

        if score > 0:
            scored.append((score, es))

    scored.sort(reverse=True, key=lambda x: x[0])

    # Return top candidates; if heuristic finds nothing, return the full list
    if scored:
        return [es for _, es in scored[:5]]
    return entity_sets[:5]


@router.get("/api/ibp/test-preview")
async def ibp_test_preview() -> dict[str, Any]:
    try:
        config_all = load_config()
        if "ibp" not in config_all:
            raise RuntimeError("Missing 'ibp' config")
        ibp_cfg = config_all["ibp"]

        planning_area = ibp_cfg.get("planning_area")
        key_figure = ibp_cfg.get("key_figure")
        planning_level = ibp_cfg.get("planning_level")

        base_url = str(ibp_cfg["base_url"]).rstrip("/")
        # NOTE: IBP connector previously stored a service string with a UI fragment.
        # We do not assume that is a valid OData service root.
        service_hint = str(ibp_cfg.get("service", ""))

        username = str(ibp_cfg["username"])
        password = str(ibp_cfg["password"])

        # Common IBP OData patterns.
        # If one fails, we will log and try the next.
        candidate_service_roots: list[str] = []

        # Pattern A: OData endpoints are typically under /odata/<service>
        # If `service_hint` is already an OData service technical name, this may work.
        if service_hint:
            candidate_service_roots.append(f"{base_url}{service_hint}")

        # Pattern B: replace UI fragment with /odata/.
        # Many IBP tenants use: <base_url>/odata/<ServiceName>
        # service_hint may include UI fragment; try to strip it.
        if service_hint and "odata" not in service_hint.lower():
            candidate_service_roots.append(f"{base_url}/odata{service_hint}")

        # Pattern C: common odata service namespace placeholder.
        candidate_service_roots.append(f"{base_url}/odata")

        last_error: str | None = None

        # Find a working $metadata endpoint
        metadata_xml: str | None = None
        metadata_url: str | None = None
        used_root: str | None = None

        for root in candidate_service_roots:
            # Try both with and without trailing slash and service root variants
            for suffix in ["/$metadata", "/$metadata"]:
                url = root.rstrip("/") + suffix
                try:
                    print("IBP $metadata URL:", url)
                    r = requests.get(
                        url,
                        auth=(username, password),
                        headers={"Accept": "application/xml"},
                        timeout=60,
                        verify=False,
                        allow_redirects=True,
                    )
                    print("IBP $metadata Status:", r.status_code)
                    print("IBP $metadata content-type:", r.headers.get("content-type"))

                    if r.status_code >= 400:
                        # keep going
                        last_error = f"metadata status {r.status_code}"
                        continue

                    metadata_xml = r.text
                    metadata_url = url
                    used_root = root
                    break
                except Exception as e:
                    last_error = f"metadata fetch failed: {e}"
                    continue

            if metadata_xml:
                break

        if not metadata_xml:
            msg = "IBP metadata discovery failed"
            print("IBP metadata discovery failed")
            raise HTTPException(
                status_code=500,
                detail=f"{msg}. Last error: {last_error}.",
            )

        entity_sets = _metadata_to_entity_sets(metadata_xml)
        print("IBP used_root:", used_root)
        print("IBP $metadata URL:", metadata_url)
        print("IBP Entity sets count:", len(entity_sets))
        print("IBP Entity sets sample:", entity_sets[:30])

        candidates = _pick_best_entity_set(entity_sets=entity_sets, planning_level=str(planning_level))
        print("IBP candidate entity sets:", candidates)

        # Try fetching candidates until we get records.
        fetched_records: list[dict[str, Any]] = []
        chosen_entity_set: str | None = None
        chosen_url: str | None = None

        # Build very conservative filter: planning area and key figure are often filterable.
        # If field names differ, the filter will just return 0 rows (or 400); we will fall back.
        # We'll try without filters first.
        for es in candidates:
            es_enc = quote(es, safe="")

            # Minimal OData query for records
            url = None
            # Try common OData base: <root>/<EntitySet>?$top=10
            # Some services may require the service root to include /odata/<ServiceName>
            root = used_root.rstrip("/")
            if root.lower().endswith("/odata"):
                # if root was just /odata, can't build; skip
                root = used_root.rstrip("/")

            # Try: <used_root>/<EntitySet>?$top=10
            url = f"{used_root.rstrip('/')}/{es_enc}?$top=10"

            headers = {"Accept": "application/json"}
            print("IBP URL:", url)

            try:
                resp = requests.get(
                    url,
                    auth=(username, password),
                    headers=headers,
                    timeout=60,
                    verify=False,
                    allow_redirects=True,
                )
                print("IBP Status:", resp.status_code)
                print("IBP Content-Type:", resp.headers.get("content-type"))

                if resp.status_code >= 400:
                    continue

                # Parse JSON
                payload = resp.json()
                records = _try_parse_odata_results(payload)
                if records:
                    fetched_records = records
                    chosen_entity_set = es
                    chosen_url = url
                    print("IBP First Record:", records[0])
                    break
            except Exception as e:
                last_error = f"fetch entity set {es} failed: {e}"
                continue

        if not fetched_records:
            # Last attempt: try to fetch the first entity set with filters using planning area/key figure
            # This is optional, but we still log everything.
            raise HTTPException(
                status_code=500,
                detail=f"IBP test-preview failed to fetch any entity set records. Last error: {last_error}",
            )

        # Return in same structure as S4 preview: success/count/data
        return {
            "success": True,
            "count": int(len(fetched_records[:10])),
            "data": fetched_records[:10],
            "debug": {
                "metadata_url": metadata_url,
                "entity_set": chosen_entity_set,
                "url": chosen_url,
                "planning_area": planning_area,
                "key_figure": key_figure,
                "planning_level": planning_level,
                "ibp_field_sample_keys": list(fetched_records[0].keys())[:50] if fetched_records else [],
            },
        }

    except HTTPException:
        raise
    except Exception as exc:
        error_text = f"{exc}\n{traceback.format_exc()}"
        print("IBP test-preview exception:", error_text)
        return {
            "success": False,
            "error": error_text,
        }

