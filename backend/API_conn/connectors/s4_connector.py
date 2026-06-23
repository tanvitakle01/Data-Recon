from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
from urllib.parse import quote

import pandas as pd
import requests

from backend.API_conn.config.config_loader import load_config
from backend.API_conn.connectors.base_connector import SAPConnector


@dataclass
class S4ODataConfig:
    base_url: str
    service: str
    username: str
    password: str
    client: str | None = None


class S4SalesOrderConnector(SAPConnector):
    """S/4HANA OData connector.

    IMPORTANT:
    - Assumes OData V2 style endpoints:
      <base>/sap/opu/odata/sap/<service>/$metadata
      <base>/sap/opu/odata/sap/<service>/<EntitySet>?

    - This connector intentionally mirrors the known-good URL construction from
      backend/tests/test_auth.py (as provided in the task statement).

    NOTE (temporary diagnostics):
    - Added `fetch_entity_set(entity_set, top)` to support /api/s4/test-preview.
      This keeps credentials/URLs unchanged.
    """


    def __init__(self):
        config_all = load_config()
        if "s4" not in config_all:
            raise RuntimeError("Missing 's4' config")

        cfg = config_all["s4"]
        super().__init__(cfg)

        self.s4 = S4ODataConfig(
            base_url=str(cfg["base_url"]),
            service=str(cfg["service"]),
            username=str(cfg["username"]),
            password=str(cfg["password"]),
            client=str(cfg.get("client")) if cfg.get("client") is not None else None,
        )

        # Reuse a session across calls (keeps cookies if SAP issues them).
        self.session = requests.Session()

        # Match repo diagnostic style: SSL verify disabled (temp) like test_auth.
        # If you want strict SSL, switch this to True.
        self.verify_ssl = False

    def _service_base_url(self) -> str:
        # Must match working test_auth.py
        return (
            f"{self.s4.base_url}"
            f"/sap/opu/odata/sap/"
            f"{self.s4.service}"
        )

    def _metadata_url(self) -> str:
        return f"{self._service_base_url()}/$metadata"

    def _auth(self) -> tuple[str, str]:
        return (self.s4.username, self.s4.password)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/xml",
        }
        # Optional: some SAP setups require X-SAP-Logon or SAP-Client.
        # We do not guess beyond config; only send SAP-Client if configured.
        if self.s4.client:
            headers["SAP-Client"] = self.s4.client
        return headers

    def fetch(self) -> pd.DataFrame:
        # Fetch metadata, discover entity sets, then try to fetch configured entity data.
        metadata_xml = self._fetch_metadata()
        entity_sets = self._extract_entity_sets(metadata_xml)


        # Prefer a common sales-order entity set if present; otherwise try all until we find data.
        preferred = [
            "A_SalesOrder",
            "SalesOrder",
            "A_SalesOrderType",
            "SalesOrderHeader",
            "A_SalesOrderItem",
        ]

        candidate_sets: list[str] = []
        for p in preferred:
            if p in entity_sets:
                candidate_sets.append(p)
        for es in entity_sets:
            if es not in candidate_sets:
                candidate_sets.append(es)

        for es in candidate_sets:
            df = self._try_fetch_entity_set(es)
            if df is not None and not df.empty:
                return df

        # If we reached here, no entity set returned data.
        return pd.DataFrame()

    def _fetch_metadata(self) -> str:
        url = self._metadata_url()
        r = self.session.get(
            url,
            auth=self._auth(),
            headers=self._headers(),
            verify=self.verify_ssl,
            timeout=60,
        )
        r.raise_for_status()
        return r.text

    def _extract_entity_sets(self, metadata_xml: str) -> list[str]:
        names = re.findall(r'<EntitySet[^>]*Name="([^"]+)"', metadata_xml)
        out: list[str] = []
        seen = set()
        for n in names:
            if n not in seen:
                seen.add(n)
                out.append(n)
        return out

    def fetch_entity_set(self, entity_set: str, top: int = 1) -> list[dict[str, Any]]:
        """Temporary diagnostic fetch for a single entity set with a configurable $top.

        IMPORTANT: This keeps existing connector auth/URL logic intact.
        """
        records_df = self._try_fetch_entity_set(entity_set=entity_set, top=top)

        # Connector internals return DataFrame; convert to list-of-dicts
        if records_df is None or records_df.empty:
            return []

        # Ensure JSON-serializable types
        return records_df.fillna("").astype(str).to_dict(orient="records")

    def _try_fetch_entity_set(self, entity_set: str, top: int = 1) -> pd.DataFrame | None:
        # Minimal payload
        service_base = self._service_base_url()

        # Keep URL safe
        entity_set_enc = quote(entity_set, safe="")

        # OData V2 common query
        url = f"{service_base}/{entity_set_enc}?$top={int(top)}"


        headers = {
            "Accept": "application/json",
        }
        if self.s4.client:
            headers["SAP-Client"] = self.s4.client

        r = self.session.get(
            url,
            auth=self._auth(),
            headers=headers,
            verify=self.verify_ssl,
            timeout=60,
            allow_redirects=True,
        )

        # Temporary diagnostics requirement
        print("S4 TEST PREVIEW RESPONSE:", r)
        print("S4 TEST PREVIEW STATUS CODE:", r.status_code)


        # If unauthorized, preserve error semantics
        if r.status_code in (401, 403):
            r.raise_for_status()

        # Missing entity set
        if r.status_code == 404:
            return pd.DataFrame()

        r.raise_for_status()

        # Many SAP OData JSON responses are in data.d.results for V2.
        try:
            payload = r.json()
        except ValueError:
            return pd.DataFrame()

        # Try common nesting
        if isinstance(payload, dict):
            if "d" in payload and isinstance(payload["d"], dict):
                d = payload["d"]
                if "results" in d and isinstance(d["results"], list):
                    return pd.DataFrame(d["results"])
                if "results" not in d:
                    # Sometimes d itself is the object
                    return pd.DataFrame([d])
            if "value" in payload and isinstance(payload["value"], list):
                return pd.DataFrame(payload["value"])

        return pd.DataFrame()

