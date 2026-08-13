from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests

from backend.API_conn.config.config_loader import load_config, resolve_verify
from backend.API_conn.connectors.base_connector import SAPConnector


@dataclass
class S4ODataConfig:
    base_url: str
    service: str
    username: str
    password: str
    client: str | None = None


class S4SalesOrderConnector(SAPConnector):

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
            client=str(cfg.get("client")) if cfg.get("client") else None,
        )

        self.session = requests.Session()
        self.verify_ssl = resolve_verify(cfg)

    def _service_base_url(self) -> str:
        return (
            f"{self.s4.base_url}"
            f"/sap/opu/odata/sap/"
            f"{self.s4.service}"
        )

    def _auth(self):
        return (self.s4.username, self.s4.password)

    def _headers(self):
        headers = {
            "Accept": "application/json"
        }

        if self.s4.client:
            headers["SAP-Client"] = self.s4.client

        return headers

    def _fetch_entity(
        self,
        entity_set: str,
        top: int = 1000,
    ) -> pd.DataFrame:

        url = (
            f"{self._service_base_url()}/"
            f"{entity_set}"
            f"?$format=json"
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

        item_df = self._fetch_entity(
            "A_SalesOrderItem"
        )

        sched_df = self._fetch_entity(
            "A_SalesOrderScheduleLine"
        )

        if item_df.empty:
            return pd.DataFrame(
                columns=[
                    "Material",
                    "Plnt",
                    "ReqDlvDate",
                    "ReqDlvQty",
                ]
            )

        item_df = item_df[
            [
                "SalesOrder",
                "SalesOrderItem",
                "Material",
                "ProductionPlant",
                "RequestedQuantity",
            ]
        ]

        if not sched_df.empty:

            sched_df = sched_df[
                [
                    "SalesOrder",
                    "SalesOrderItem",
                    "RequestedDeliveryDate",
                ]
            ]

            final_df = item_df.merge(
                sched_df,
                on=["SalesOrder", "SalesOrderItem"],
                how="left",
            )

        else:

            final_df = item_df.copy()
            final_df["RequestedDeliveryDate"] = None

        final_df.rename(
            columns={
                "ProductionPlant": "Plnt",
                "RequestedQuantity": "ReqDlvQty",
                "RequestedDeliveryDate": "ReqDlvDate",
            },
            inplace=True,
        )

        return final_df[
            [
                "Material",
                "Plnt",
                "ReqDlvDate",
                "ReqDlvQty",
            ]
        ]