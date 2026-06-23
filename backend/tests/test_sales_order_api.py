import os
import sys

import requests
import urllib3

# Ensure repo root is on sys.path so `import backend...` works when running
# this file directly.
_THIS_DIR = os.path.dirname(__file__)
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.API_conn.config.config_loader import load_config


def main():
    cfg_all = load_config()
    cfg = cfg_all["s4"]

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Must match backend/tests/test_auth.py pattern from the task statement.
    base_url = (
        f"{cfg['base_url']}"
        f"/sap/opu/odata/sap/"
        f"{cfg['service']}"
    )

    metadata_url = f"{base_url}/$metadata"

    # 1) Verify metadata works
    r_meta = requests.get(
        metadata_url,
        auth=(cfg["username"], cfg["password"]),
        verify=False,
        timeout=30,
    )

    print("$metadata URL:", metadata_url)
    print("$metadata STATUS:", r_meta.status_code)
    print("$metadata content-type:", r_meta.headers.get("content-type"))
    print(r_meta.text[:500])

    r_meta.raise_for_status()

    print(
        "\nNext step: run backend/tests/diag_s4_odata.py to discover EntitySets and test them for 401 vs 404."
    )


if __name__ == "__main__":
    main()

