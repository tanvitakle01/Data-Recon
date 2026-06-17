from API_conn.connectors.base_connector import SAPConnector
from API_conn.config.config_loader import load_config
import pandas as pd

class S4SalesOrderConnector(SAPConnector):

    def __init__(self):
        config = load_config()["s4"]
        super().__init__(config)

    def fetch(self):
        return pd.DataFrame()
"""
s4:
  base_url: https://<s4-host>
  service: API_SALES_ORDER_SRV
  username: <user>
  password: <password>

Base URL
Authentication type
Username
Password
Client number
API_SALES_ORDER_SRV endpoint

"""