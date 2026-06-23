# backend/tests/test_auth.py

import requests
from backend.API_conn.config.config_loader import load_config

cfg = load_config()["s4"]

url = (
    f"{cfg['base_url']}"
    f"/sap/opu/odata/sap/"
    f"{cfg['service']}"
    f"/$metadata"
)

print("URL:", url)
print("USER:", cfg["username"])

response = requests.get(
    url,
    auth=(cfg["username"], cfg["password"]),
    verify=False,
    timeout=30
)

print("STATUS:", response.status_code)

for k, v in response.headers.items():
    print(k, ":", v)

print(response.text[:1000])

with open("metadata.xml", "w", encoding="utf-8") as f:
    f.write(response.text)