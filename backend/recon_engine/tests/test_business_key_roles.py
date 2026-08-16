"""LLM-based date/quantity business-key role detection for the chat/"from
data" Auto-mode path.

The LLM is faked so these tests are deterministic — the point is the
wrapper's contract (gating against real columns, graceful degrade), not the
model. The exact columns here (``Req.Dlv.Dt``, ``ReqDlvQty``, ``KEYFIGUREDATE``,
``SALESORDERREQUEST``) are the real-world case that broke the deterministic
alias matcher (``field_roles.detect_roles_for_columns``) this module replaces
for chat-uploaded files.
"""

from __future__ import annotations

import pytest

from backend.recon_engine.auto_pipeline import business_key_roles


class _FakeClient:
    def __init__(self, payload=None, raises=None):
        self._payload = payload
        self._raises = raises

    def complete_json(self, messages):  # noqa: ARG002 - signature match
        if self._raises is not None:
            raise self._raises
        return self._payload


@pytest.fixture
def llm_configured(monkeypatch):
    monkeypatch.setattr(
        business_key_roles, "get_settings", lambda: type("S", (), {"any_llm_configured": True})()
    )


def _install_llm(monkeypatch, *, payload=None, raises=None):
    monkeypatch.setattr(
        business_key_roles, "build_llm_client", lambda: _FakeClient(payload=payload, raises=raises)
    )


_SOURCE_COLUMNS = ["Plant", "Material", "ReqDlvQty", "Req.Dlv.Dt"]
_TARGET_COLUMNS = ["LOCID", "PRDID", "SALESORDERREQUEST", "KEYFIGUREDATE"]

_SOURCE_ROWS = [{"Plant": "P1000", "Material": "MAT-100", "ReqDlvQty": 50, "Req.Dlv.Dt": "2024-02-01"}]
_TARGET_ROWS = [{"LOCID": "P1000", "PRDID": "MAT-100", "SALESORDERREQUEST": 50, "KEYFIGUREDATE": "2024-02-01"}]

_PAYLOAD = {
    "source": {
        "date": {"field": "Req.Dlv.Dt", "confidence": "high", "reason": "Values parse as dates."},
        "quantity": {"field": "ReqDlvQty", "confidence": "high", "reason": "Plain numeric quantity."},
    },
    "target": {
        "date": {"field": "KEYFIGUREDATE", "confidence": "high", "reason": "Values parse as dates."},
        "quantity": {"field": "SALESORDERREQUEST", "confidence": "high", "reason": "Plain numeric quantity."},
    },
}


def test_identifies_date_and_quantity_from_abbreviated_headers(monkeypatch, llm_configured):
    """The exact real-world regression: a deterministic alias matcher misses
    'Req.Dlv.Dt'/'ReqDlvQty'/'KEYFIGUREDATE'/'SALESORDERREQUEST' entirely;
    the LLM (given column names + sample row evidence) resolves all four."""
    _install_llm(monkeypatch, payload=_PAYLOAD)

    result = business_key_roles.identify_business_key_roles(
        _SOURCE_COLUMNS, _TARGET_COLUMNS, _SOURCE_ROWS, _TARGET_ROWS
    )

    assert result["degraded"] is False
    assert result["source"]["date"]["field"] == "Req.Dlv.Dt"
    assert result["source"]["quantity"]["field"] == "ReqDlvQty"
    assert result["target"]["date"]["field"] == "KEYFIGUREDATE"
    assert result["target"]["quantity"]["field"] == "SALESORDERREQUEST"


def test_gates_out_a_field_name_not_in_the_real_columns(monkeypatch, llm_configured):
    """A hallucinated field name that doesn't exist in the real column list
    is dropped (field -> None), never trusted as-is."""
    bad_payload = {
        "source": {
            "date": {"field": "Delivery Date", "confidence": "high", "reason": "invented"},
            "quantity": {"field": "ReqDlvQty", "confidence": "high", "reason": "ok"},
        },
        "target": _PAYLOAD["target"],
    }
    _install_llm(monkeypatch, payload=bad_payload)

    result = business_key_roles.identify_business_key_roles(
        _SOURCE_COLUMNS, _TARGET_COLUMNS, _SOURCE_ROWS, _TARGET_ROWS
    )

    assert result["source"]["date"]["field"] is None
    assert result["source"]["quantity"]["field"] == "ReqDlvQty"


def test_degrades_on_llm_failure_instead_of_raising(monkeypatch, llm_configured):
    _install_llm(monkeypatch, raises=RuntimeError("provider unavailable"))

    result = business_key_roles.identify_business_key_roles(
        _SOURCE_COLUMNS, _TARGET_COLUMNS, _SOURCE_ROWS, _TARGET_ROWS
    )

    assert result["degraded"] is True
    assert result["source"]["date"]["field"] is None
    assert result["target"]["quantity"]["field"] is None


def test_degrades_when_no_llm_provider_configured():
    result = business_key_roles.identify_business_key_roles(
        _SOURCE_COLUMNS, _TARGET_COLUMNS, _SOURCE_ROWS, _TARGET_ROWS
    )
    assert result["degraded"] is True
