import os
import re
import sys
import traceback
import xml.etree.ElementTree as ET
from typing import Any

import requests


# Allow running as: python scripts/discover_ibp_odata_metadata.py
# Ensure repo root is on sys.path so `import backend...` works.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _safe_findall(root: ET.Element, path: str):
    try:
        return root.findall(path)
    except Exception:
        return []


def fetch_metadata(url: str, username: str, password: str, timeout: int = 60) -> tuple[int, str]:
    r = requests.get(
        url,
        auth=(username, password),
        headers={"Accept": "application/xml,text/xml,application/json"},
        timeout=timeout,
        allow_redirects=True,
        verify=False,
    )
    return r.status_code, r.text


def parse_metadata(xml_text: str) -> dict[str, Any]:
    root = ET.fromstring(xml_text)

    entity_sets = set()
    entity_types = set()

    # V2 metadata typically: EntitySet Name="..." EntityType="Namespace.Type"
    for elem in root.iter():
        tag = _strip_ns(elem.tag)
        if tag == "EntitySet":
            name = elem.attrib.get("Name")
            if name:
                entity_sets.add(name)
        elif tag == "EntityType":
            tname = elem.attrib.get("Name")
            if tname:
                entity_types.add(tname)

    # Collect properties per entity type
    entity_type_properties: dict[str, set[str]] = {}
    # EntityType has nested Property tags
    for elem in root.iter():
        tag = _strip_ns(elem.tag)
        if tag == "EntityType":
            et_name = elem.attrib.get("Name")
            if not et_name:
                continue
            props = set()
            for child in list(elem):
                ctag = _strip_ns(child.tag)
                if ctag == "Property":
                    pname = child.attrib.get("Name")
                    if pname:
                        props.add(pname)
            entity_type_properties[et_name] = props

    return {
        "entity_sets": sorted(entity_sets),
        "entity_types": sorted(entity_types),
        "entity_type_properties": {k: sorted(v) for k, v in entity_type_properties.items()},
    }


def main():
    # Load app config
    from backend.API_conn.config.config_loader import load_config

    cfg_all = load_config()
    ibp = cfg_all.get("ibp") or {}

    username = ibp.get("username")
    password = ibp.get("password")
    if not username or not password:
        print("Missing IBP username/password in backend/API_conn/config/sap_config.yaml")
        sys.exit(1)

    planning_area = ibp.get("planning_area")
    key_figure = ibp.get("key_figure")
    planning_level = ibp.get("planning_level")

    base_url = str(ibp.get("base_url", "")).rstrip("/")

    print("=" * 80)
    print("IBP OData Metadata Discovery")
    print("=" * 80)
    print("planning_area:", planning_area)
    print("key_figure:", key_figure)
    print("planning_level:", planning_level)
    print("base_url:", base_url)

    candidate_metadata_urls = [
        f"{base_url}/odata/v1/$metadata",
        f"{base_url}/odata/v2/$metadata",
        f"{base_url}/sap/opu/odata/$metadata",
        f"{base_url}/sap/opu/odata/sap/$metadata",
        f"{base_url}/sap/opu/odata/IBP/$metadata",
    ]

    # Add a couple common IBP namespace guesses
    if base_url:
        candidate_metadata_urls += [
            f"{base_url}/sap/opu/odata/sap/IBP/$metadata",
        ]

    xml_out = os.path.abspath("ibp_metadata.xml")

    ok_xml = None
    ok_url = None
    for url in candidate_metadata_urls:
        try:
            print("\nTrying metadata:", url)
            status, text = fetch_metadata(url, username=username, password=password)
            print("HTTP:", status, "length:", len(text))

            if 200 <= status < 300 and "EntitySet" in text and ("schema" in text or "EntityType" in text):
                ok_xml = text
                ok_url = url
                break

        except Exception as e:
            print("Failed:", url)
            print(type(e).__name__, str(e))

    if not ok_xml:
        print("\nCould not download a parsable $metadata from any candidate URL.")
        sys.exit(2)

    with open(xml_out, "w", encoding="utf-8") as f:
        f.write(ok_xml)

    print("\nSaved metadata to:", xml_out)
    print("Metadata URL used:", ok_url)

    parsed = parse_metadata(ok_xml)
    entity_sets = parsed["entity_sets"]
    entity_type_properties = parsed["entity_type_properties"]

    # Search keywords inside entity sets/properties
    keywords = [
        "HPA2508",
        "I_SALESORDERREQUEST",
        "I_DAYPRODLOCDEMAND",
        "MATERIAL",
        "PRODUCT",
        "LOCATION",
        "CUSTOMER",
        "DATE",
        "PERIOD",
        "QUANTITY",
        "SALESORDER",
    ]

    print("\n--- Candidate matches ---")

    def matches_any(s: str) -> bool:
        up = s.upper()
        return any(k.upper() in up for k in keywords)

    matched_entity_sets = [es for es in entity_sets if matches_any(es)]

    print("Matched entity sets (by name):")
    for es in matched_entity_sets[:50]:
        print(" -", es)

    # Build candidate entity sets by property presence
    key_props = [
        "PRODUCTID",
        "LOCATIONID",
        "PERIODID",
        "I_SALESORDERREQUEST",
        "MATERIAL",
        "PLNT",
        "WERKS",
        "REQDLV",
        "QTY",
        "QUANTITY",
    ]

    candidates = []
    for et_name, props in entity_type_properties.items():
        prop_up = {p.upper() for p in props}
        if any(p in prop_up for p in ["PRODUCTID", "LOCATIONID", "PERIODID"]) and any(
            p in prop_up for p in [k.upper() for k in [key_figure] if k]
        ):
            candidates.append((et_name, sorted(props)))
        elif any(p in prop_up for p in [key_figure.upper() if key_figure else ""]) and any(
            p in prop_up for p in ["PRODUCTID", "LOCATIONID", "PERIODID"]
        ):
            candidates.append((et_name, sorted(props)))

    print("\nCandidate EntityTypes (by property presence):")
    for et_name, props in candidates[:20]:
        print("\nEntityType:", et_name)
        print("Relevant props:", [p for p in props if any(k.upper() in p.upper() for k in ["PRODUCT", "LOCATION", "PERIOD", "I_SALESORDERREQUEST", "QTY", "DATE", "MATERIAL", "PLNT", "WERKS"])])

    # Since metadata parsing above does not map EntitySet->EntityType reliably across namespaces,
    # we provide suggested preview endpoints for entity sets that match keywords.

    print("\n--- Suggested preview endpoints ($top=10) ---")
    # Prefer entity sets likely linked to planning level
    preferred_prefixes = [
        str(planning_level or ""),
        "I_DAYPRODLOCDEMAND",
        "I_SALESORDERREQUEST",
        "DEMAND",
        "SALES",
        "ORDER",
        "REQUEST",
    ]

    suggested = []
    for es in entity_sets:
        if any(pref.lower() in es.lower() for pref in preferred_prefixes if pref):
            suggested.append(es)
        elif matches_any(es):
            suggested.append(es)

    # Deduplicate while preserving order
    seen = set()
    suggested_unique = []
    for es in suggested:
        if es not in seen:
            seen.add(es)
            suggested_unique.append(es)

    # Limit to 15 to keep output readable
    suggested_unique = suggested_unique[:15]

    # Suggested fields: attempt to follow the expected reconciliation schema
    select_fields_candidates = [
        "PRODUCTID",
        "LOCATIONID",
        "PERIODID",
        key_figure or "I_SALESORDERREQUEST",
        "MATNR",
        "WERKS",
        "MATERIAL",
        "PLANT",
        "REQDLVDT",
        "REQDLVQTY",
    ]

    # Build query URLs using the same base_url (caller will adjust if needed)
    # We infer OData v1 vs v2 vs sap/opu/odata from the metadata url.
    base_for_queries = None
    if ok_url:
        # Strip '/$metadata'
        base_for_queries = ok_url.replace("/$metadata", "")
    else:
        base_for_queries = f"{base_url}/odata/v1"

    # Print
    print("\nUsing query base:", base_for_queries)

    for es in suggested_unique:
        # Create a $select string with only non-empty candidates
        select_fields = [f for f in select_fields_candidates if f]
        select = ",".join(select_fields[:6])
        sample_url = f"{base_for_queries}/{es}?$top=10&$select={select}"
        sample_url_simple = f"{base_for_queries}/{es}?$top=10"
        print("\nEntitySet:", es)
        print("- URL (simple):", sample_url_simple)
        print("- URL (select):", sample_url)

    print("\nDone.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("\nERROR:", type(e).__name__, str(e))
        print(traceback.format_exc())
        sys.exit(3)

