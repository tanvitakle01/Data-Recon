from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests

from backend.API_conn.connectors.base_connector import SAPConnector
from backend.API_conn.config.config_loader import load_config, resolve_verify

@dataclass
class IBPDataConfig:
    base_url: str
    service: str
    username: str
    password: str
    client: str | None = None


class IBPDemandConnector(SAPConnector):

    def __init__(self):
        config_all= load_config()

        if "ibp" not in config_all:
            raise RuntimeError("Missing 'ibp' config")
        
        cfg = config_all["ibp"]

        super().__init__(cfg)
        self.session = requests.Session()
        self.verify_ssl = resolve_verify(cfg)

        self.ibp = IBPDataConfig(
            base_url=str(cfg["base_url"]),
            service=str(cfg["service"]),
            username=str(cfg["username"]),
            password=str(cfg["password"]),
            client=str(cfg.get("client")) if cfg.get("client") else None,
        )

    def _service_base_url(self):
        return (
            f"{self.ibp.base_url}"
            f"/sap/opu/odata/"
            f"{self.ibp.service}"
        )
    
    def _auth(self):
        return (self.ibp.username, self.ibp.password)

    def _headers(self):
        headers = { 
            "Accept": "application/json"
        }

        if self.ibp.client:
            headers["sap-client"] = self.ibp.client

        return headers
    
    def _fetch_entity(
            self, 
            entity_set: str, 
            top: int=1000,
    ):
        url = (
            f"{self._service_base_url()}/"
            f"{entity_set}"
            f"?$format=json&$select=LOCID, PRDID, SALESORDERREQUEST, PERIODID0_TSTAMP"
        )

        #$top=1000&

        response = self.session.get(
            url,    
            auth=self._auth(),
            headers=self._headers(),    
            verify=self.verify_ssl,
            timeout=60,
        )

        response.raise_for_status()

        payload = response.json()

        rows = payload.get("d", {}).get("results", [])

        return pd.DataFrame(rows)
    
    def fetch(self) -> pd.DataFrame:
        ibp_df = self._fetch_entity("ZOBP2508")

        if ibp_df.empty:
            return pd.DataFrame(
               columns=[
                   "LOCID",
                   "PRDID",
                   "SALESORDERREQUEST",
                   "KEYFIGUREDATE",
               ]
            )

        ibp_df = ibp_df[
            [
                "LOCID",
                "PRDID",
                "SALESORDERREQUEST",
                "PERIODID0_TSTAMP",
            ]
        ].copy()

        ibp_df.rename(
            columns={
                "PERIODID0_TSTAMP": "KEYFIGUREDATE",
            },
            inplace=True,
        )

        return ibp_df[
            [
                "LOCID",
                "PRDID",
                "SALESORDERREQUEST",
                "KEYFIGUREDATE",
            ]
        ]
    
        
    

