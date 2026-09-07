"""Manual IBP connectivity probe — prints a full request/response trace.

Not a pytest test (it was named test_ibp.py, which made pytest collect it):
it's a hand-run diagnostic. The import below is relative to THIS directory,
so run it from here:

    cd backend/API_conn && python probe_ibp.py
"""

import requests
from requests.auth import HTTPBasicAuth

# Resolved from backend/API_conn/config/ — see the module docstring on cwd.
from config.config_loader import load_config, resolve_verify


def divider(title):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def print_headers(headers):
    for k, v in headers.items():
        print(f"{k}: {v}")


def inspect_response(name, response):
    divider(name)

    print("FINAL URL:")
    print(response.url)

    print("\nSTATUS:")
    print(response.status_code)

    print("\nCONTENT TYPE:")
    print(response.headers.get("Content-Type"))

    print("\nWWW-AUTHENTICATE:")
    print(response.headers.get("WWW-Authenticate"))

    print("\nSET-COOKIE:")
    print(response.headers.get("Set-Cookie"))

    print("\nRESPONSE HEADERS:")
    print_headers(response.headers)

    print("\nREDIRECT HISTORY:")
    if response.history:
        for idx, h in enumerate(response.history, start=1):
            print(
                f"{idx}. {h.status_code} -> {h.headers.get('Location')}"
            )
    else:
        print("No redirects")

    print("\nBODY PREVIEW:")
    print(response.text[:1500])


def main():

    cfg = load_config()

    ibp_cfg = cfg.get("ibp", {})

    username = ibp_cfg.get("username")
    password = ibp_cfg.get("password")
    verify = resolve_verify(ibp_cfg)

    base_url = "https://my400230-api.scmibp.ondemand.com"
    metadata_url = (
        "https://my400230-api.scmibp.ondemand.com"
        "/sap/opu/odata/IBP/PLANNING_DATA_API_SRV/$metadata"
    )

    divider("CONFIG")

    print("Username:", username)
    print("Password Present:", bool(password))

    session = requests.Session()

    # ------------------------------------------------------------------
    # TEST 1
    # ------------------------------------------------------------------

    try:

        r = session.get(
            metadata_url,
            verify=verify,
            timeout=60,
            allow_redirects=True,
        )

        inspect_response(
            "TEST 1 - NO AUTH",
            r,
        )

    except Exception as ex:
        print("TEST 1 FAILED")
        print(ex)

    # ------------------------------------------------------------------
    # TEST 2
    # ------------------------------------------------------------------

    try:

        r = session.get(
            metadata_url,
            verify=verify,
            timeout=60,
            allow_redirects=True,
            auth=HTTPBasicAuth(
                username,
                password,
            ),
            headers={
                "Accept": "application/xml"
            },
        )

        inspect_response(
            "TEST 2 - BASIC AUTH",
            r,
        )

        print("\nREQUEST HEADERS SENT:")
        print_headers(r.request.headers)

    except Exception as ex:
        print("TEST 2 FAILED")
        print(ex)

    # ------------------------------------------------------------------
    # TEST 3
    # ------------------------------------------------------------------

    try:

        service_root = (
            "https://my400230-api.scmibp.ondemand.com"
            "/sap/opu/odata/IBP/PLANNING_DATA_API_SRV"
        )

        r = session.get(
            service_root,
            verify=verify,
            timeout=60,
            allow_redirects=True,
            auth=HTTPBasicAuth(
                username,
                password,
            ),
        )

        inspect_response(
            "TEST 3 - SERVICE ROOT",
            r,
        )

    except Exception as ex:
        print("TEST 3 FAILED")
        print(ex)

    # ------------------------------------------------------------------
    # COOKIE INSPECTION
    # ------------------------------------------------------------------

    divider("SESSION COOKIES")

    if session.cookies:
        for cookie in session.cookies:
            print(
                cookie.name,
                "=",
                cookie.value,
            )
    else:
        print("No cookies")

    divider("AUTH DIAGNOSIS")

    print(
        """
Interpretation:

1. If WWW-Authenticate contains:
      Basic realm=...
   then Basic Auth is supported.

2. If redirects go to:
      accounts.sap.com
      *.authentication.sap.hana.ondemand.com
      *.ondemand.com/saml
   then SAML/IAS/OAuth is being used.

3. If metadata opens in browser but Basic Auth gets 401,
   then browser SSO is authenticating you.

4. If metadata returns XML when Basic Auth is sent,
   then authentication is working and entity discovery can proceed.
"""
    )


if __name__ == "__main__":
    main()