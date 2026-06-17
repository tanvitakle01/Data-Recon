from API_conn.connectors.base_connector import SAPConnector
from API_conn.config.config_loader import load_config
import pandas as pd
import requests


class IBPDemandConnector(SAPConnector):

    def __init__(self):
        config = load_config()["ibp"]
        super().__init__(config)

    def fetch(self):

        endpoint = (
            self.config["base_url"]
            + self.config["service"]
            + "/$metadata"
        )

        print("\nEndpoint:")
        print(endpoint)

        response = requests.get(
            endpoint,
            auth=(
                self.config["username"],
                self.config["password"]
            ),
            headers={
                "Accept": "application/xml"
            },
            timeout=60,
            allow_redirects=True
        )

        print("\nFinal URL:")
        print(response.url)

        print("\nStatus Code:")
        print(response.status_code)

        print("\nHeaders:")
        print(dict(response.headers))

        print("\nContent Type:")
        print(response.headers.get("content-type"))

        print("\nResponse Preview:")
        print(response.text[:5000])

        print("\nSERVICE =", repr(self.config["service"]))

        response.raise_for_status()

        return pd.DataFrame()