from __future__ import annotations

import datetime


def to_odata_datetime_literal(value) -> str:
    """Format a date/datetime (or ``YYYY-MM-DD`` string) as an OData V2
    ``datetime'...'`` filter literal, e.g. ``datetime'2024-01-01T00:00:00'``.

    Inverse direction of :func:`sap_odata_date_to_ddmmyyyy` — used to build
    ``$filter`` clauses, never to parse a response.
    """
    if isinstance(value, str):
        value = datetime.datetime.strptime(value, "%Y-%m-%d")
    return "datetime'" + value.strftime("%Y-%m-%dT%H:%M:%S") + "'"


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
