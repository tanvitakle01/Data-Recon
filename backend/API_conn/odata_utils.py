from __future__ import annotations

import datetime


def sap_odata_date_to_ddmmyyyy(value):
    """Convert an OData V2 `/Date(<epoch_ms>)/` string to `dd.mm.yyyy`.

    Values that don't match the pattern are returned unchanged so callers
    can pass through already-formatted or empty values safely.
    """
    if not value:
        return ""

    s = str(value)

    if s.startswith("/Date("):
        digits = "".join(ch for ch in s if ch.isdigit())

        if digits:
            dt = datetime.datetime.utcfromtimestamp(int(digits) / 1000)
            return dt.strftime("%d.%m.%Y")

    return s
