"""Sheet-driven system identification: allow-list discipline + graceful degrade.

The LLM is faked so these tests are deterministic — the point is not the model
but the wrapper's contract: a configured connector is auto-selected with cited
evidence, an out-of-registry system is flagged (never coerced), and any failure
degrades to a manual-selection result rather than raising.
"""

from __future__ import annotations

import pytest

from backend.recon_engine import sheet_identifier


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
    """Pretend an LLM provider is configured (conftest clears the keys)."""
    monkeypatch.setattr(
        sheet_identifier, "get_settings", lambda: type("S", (), {"any_llm_configured": True})()
    )


def _install_llm(monkeypatch, *, payload=None, raises=None):
    monkeypatch.setattr(
        sheet_identifier, "build_llm_client", lambda: _FakeClient(payload=payload, raises=raises)
    )


# A realistic STM-sheet identification following the ASYMMETRIC extraction rule:
# S/4 source shows BUSINESS descriptions; IBP target shows TECHNICAL field names.
_STM_PAYLOAD = {
    "source": {
        "kind": "s4",
        "evidence": "Source references use S/4 TABLE-FIELD naming: VBAP-MATNR, VBEP-EDATU.",
        "confidence": "high",
        "fields": ["Material", "Production Plant", "Requested Quantity", "Requested Delivery Date"],
    },
    "target": {
        "kind": "ibp",
        "evidence": "Header banner reads 'Target: IBP'; technical fields PRDID/LOCID.",
        "confidence": "high",
        "fields": ["PRDID", "LOCID", "SALESORDERREQUEST", "PERIODID0_TSTAMP"],
    },
}


def test_identifies_s4_source_and_ibp_target_with_evidence(monkeypatch, llm_configured):
    _install_llm(monkeypatch, payload=_STM_PAYLOAD)
    result = sheet_identifier.identify_systems({"headers": ["Source Table/Field", "IBP Field"]})

    assert result["degraded"] is False
    src, tgt = result["source"], result["target"]

    assert src["kind"] == "s4"
    assert src["connector_id"] == "sap_s4hana"
    assert src["configured"] is True
    assert "VBAP" in src["evidence"]  # evidence is cited, not blank

    assert tgt["kind"] == "ibp"
    assert tgt["connector_id"] == "sap_ibp"
    assert tgt["configured"] is True

    assert result["warnings"] == []  # a clean, fully-identified sheet


def test_stm_sheet_produces_exact_expected_candidate_fields(monkeypatch, llm_configured):
    """Acceptance: the real STM sheet's expected asymmetric candidate fields.

    The fake LLM output deliberately leaks a technical VBAP-MATNR into the
    source list to prove the deterministic guard strips it, yielding EXACTLY the
    business descriptions on the source side and the technical names on target.
    """
    payload = {
        "source": {
            "kind": "s4",
            "evidence": "VBAP/VBEP table prefixes.",
            "confidence": "high",
            # A leaked technical ref among the business descriptions:
            "fields": ["Material", "VBAP-MATNR", "Production Plant", "Requested Quantity", "Requested Delivery Date"],
        },
        "target": {
            "kind": "ibp",
            "evidence": "Target: IBP banner.",
            "confidence": "high",
            "fields": ["PRDID", "LOCID", "SALESORDERREQUEST", "PERIODID0_TSTAMP"],
        },
    }
    _install_llm(monkeypatch, payload=payload)
    result = sheet_identifier.identify_systems({"headers": []})

    # SOURCE: business descriptions only — the technical VBAP-MATNR is stripped.
    assert result["source"]["fields"] == [
        "Material",
        "Production Plant",
        "Requested Quantity",
        "Requested Delivery Date",
    ]
    # TARGET: technical names, kept verbatim (never replaced by business labels).
    assert result["target"]["fields"] == [
        "PRDID",
        "LOCID",
        "SALESORDERREQUEST",
        "PERIODID0_TSTAMP",
    ]
    # The strip is surfaced, not silent.
    assert any("VBAP-MATNR" in w for w in result["warnings"])


def test_target_side_technical_names_are_never_filtered(monkeypatch, llm_configured):
    # IBP technical names must survive verbatim even though some LOOK like
    # single tokens; the TABLE-FIELD guard applies to the SOURCE side only.
    payload = {
        "source": {"kind": "s4", "evidence": "x", "confidence": "high", "fields": ["Material"]},
        "target": {"kind": "ibp", "evidence": "x", "confidence": "high", "fields": ["PRDID", "LOCID"]},
    }
    _install_llm(monkeypatch, payload=payload)
    result = sheet_identifier.identify_systems({"headers": []})
    assert result["target"]["fields"] == ["PRDID", "LOCID"]


def test_out_of_registry_system_is_flagged_not_coerced(monkeypatch, llm_configured):
    # The sheet looks like BW on the source side. BW is not a registered
    # connector — it must NOT be snapped to the nearest option (s4).
    payload = {
        "source": {
            "kind": "bw",
            "evidence": "Source fields are BW InfoObjects (0MATERIAL, ZADSO naming).",
            "confidence": "high",
            "fields": ["0MATERIAL"],
        },
        "target": _STM_PAYLOAD["target"],
    }
    _install_llm(monkeypatch, payload=payload)
    result = sheet_identifier.identify_systems({"headers": ["BW Field", "IBP Field"]})

    src = result["source"]
    assert src["kind"] is None  # NOT coerced to s4
    assert src["connector_id"] is None
    assert src["configured"] is False
    assert src["in_registry"] is False
    assert src["suggested_kind"] == "bw"  # raw suggestion preserved for transparency
    # A warning explains why, citing the evidence — not a silent drop.
    assert any("bw" in w.lower() for w in result["warnings"])

    # The target side is unaffected — still correctly IBP.
    assert result["target"]["kind"] == "ibp"


def test_llm_failure_degrades_to_manual(monkeypatch, llm_configured):
    _install_llm(monkeypatch, raises=RuntimeError("groq exploded"))
    result = sheet_identifier.identify_systems({"headers": []})

    assert result["degraded"] is True
    assert result["source"]["kind"] is None
    assert result["target"]["kind"] is None
    assert result["degraded_reason"]


def test_no_llm_configured_degrades(monkeypatch):
    # get_settings NOT patched → conftest cleared the keys → nothing configured.
    result = sheet_identifier.identify_systems({"headers": []})
    assert result["degraded"] is True
    assert "provider" in (result["degraded_reason"] or "").lower() or result["degraded_reason"]


def test_unidentified_side_produces_warning(monkeypatch, llm_configured):
    # The LLM couldn't tell for the source side (kind=null) — surface a warning,
    # keep the evidence, and don't auto-select anything.
    payload = {
        "source": {"kind": None, "evidence": "Ambiguous field naming.", "confidence": "low", "fields": []},
        "target": _STM_PAYLOAD["target"],
    }
    _install_llm(monkeypatch, payload=payload)
    result = sheet_identifier.identify_systems({"headers": []})
    assert result["source"]["kind"] is None
    assert any("source" in w.lower() for w in result["warnings"])
    assert result["target"]["kind"] == "ibp"
