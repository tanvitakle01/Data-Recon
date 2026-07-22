"""LLM-inferred FIELD mapping for the no-mapping-sheet path (allow-listed).

Given a sample of the *actually-fetched* source and target data, infer the
COLUMN-to-COLUMN mapping — which source column corresponds to which target
column — plus each pairing's role (Key / Compare). This replaces the difflib
``auto_map_columns`` heuristic on the wizard's no-sheet path with a
data-informed inference that emits the SAME ``{display, mapping}`` shape the
Step-4 table already consumes.

CRITICAL BOUNDARY — FIELD mapping only, never VALUE mapping. This decides
``Material -> PRDID`` (column → column). It must NEVER emit value pairs like
``S101 -> DCS101@S21400`` — value-to-value mapping stays the deterministic
matcher's job (``matching/product.py`` / ``matching/location.py``). The output
is structurally column-names-only and every name is gated against the real
column sets, so a value pair cannot survive the normalizer.

Same safety posture as :mod:`sheet_identifier`:

* **Same provider chain.** Goes through ``build_llm_client()`` (Groq primary →
  OpenAI fallback), never a bespoke client.
* **Never raises on LLM failure.** Degrades to an empty mapping the frontend
  treats as "map manually" — no deterministic fallback (the wizard's no-sheet
  path is LLM-only by design).
* **Existence-gated.** Every column the model names must exist in the columns
  actually sent (which already exclude MDT auxiliary evidence fields — those
  are dropped by the frontend before the request). Invented names are rejected.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import pandas as pd

from backend.recon_engine.config import get_settings
from backend.recon_engine.engine.executor import _is_blank  # reuse the blank primitive
from backend.recon_engine.llm import build_llm_client, get_last_llm_outcome

logger = logging.getLogger("recon.field_mapper")

# Role labels MUST match the emoji strings the Step-4 table (MappingEditor.jsx)
# renders and the deterministic `isKeyRole` (/key/i) test keys off.
KEY_ROLE = "🔑 Key"
COMPARE_ROLE = "📊 Compare"

_DEFAULT_OPTIONS = {"case_insensitive": True, "trim_whitespace": True}

# Populated example values sampled per column for the prompt. Capped for token
# cost; enough to reveal a column's format (IDs, dates, quantities) without
# dumping raw rows.
_SAMPLES_PER_COLUMN = 12

_SYSTEM_PREAMBLE = """You are mapping columns from a SOURCE dataset to a TARGET
dataset for reconciliation. You are given, for each side, the column names and a
small sample of real, non-null values from each column.

Infer which SOURCE column corresponds to which TARGET column by reasoning about
BOTH the column names AND the shape/content of their sample values (identifier-
like codes, dates, quantities, descriptive text, etc.). Do NOT rely on any prior
assumption about what specific fields "should" map — different datasets use
entirely different names, including custom fields. Reason from the data in front
of you, not from memorized field pairings.

For each pairing you propose, assign a role:
  - "Key"     : an identifier/dimension used to match records (e.g. product,
                location, date-like columns, order numbers).
  - "Compare" : a measured value compared once keys align (e.g. quantity/amount
                columns).

Rules:
- Only reference column names that appear EXACTLY in the provided lists. Never
  invent a column, and never put a data VALUE where a column name belongs.
- Output column-to-column (field) mappings ONLY. Never output value-to-value
  mappings.
- If you cannot confidently pair a column, leave it UNMAPPED rather than forcing
  a guess.
- Map each source column to at most one target column, and vice versa.

Respond with a single JSON object only, no prose/markdown/code fences:
{
  "mappings": [
    {"source_column": "<exact source column name>",
     "target_column": "<exact target column name>",
     "role": "Key" | "Compare",
     "reason": "<one line citing the evidence you used: name similarity, value shape, ...>",
     "label": "<optional short concept name for display; omit if unsure>"},
    ...
  ],
  "unmapped": {
    "source": ["<source columns you could not confidently pair>", ...],
    "target": ["<target columns you could not confidently pair>", ...]
  }
}
"""


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _sample_columns(df: pd.DataFrame, n: int = _SAMPLES_PER_COLUMN) -> list[dict[str, Any]]:
    """For each column, collect up to ``n`` genuinely-populated example values.

    Sampled PER COLUMN (not by filtering the row set to dense rows), so a
    sparse-but-real column still contributes examples. Columns that are entirely
    blank are dropped from the prompt (they carry no mapping signal). Uses
    ``_is_blank`` so ""/whitespace/"nan"/"NaT" all count as empty.
    """
    out: list[dict[str, Any]] = []
    for col in df.columns:
        samples: list[str] = []
        seen: set[str] = set()
        for value in df[col]:
            if _is_blank(value):
                continue
            text = str(value).strip()
            if text in seen:
                continue
            seen.add(text)
            samples.append(text)
            if len(samples) >= n:
                break
        if samples:  # drop entirely-empty columns
            out.append({"name": str(col), "samples": samples})
    return out


def _is_compare_role(value: Any) -> bool:
    return "compare" in str(value or "").strip().lower()


def _degraded(reason: str) -> dict[str, Any]:
    """A safe result the frontend treats as 'no auto-mapping — map manually'."""
    return {
        "display": [],
        "mapping": {"key_fields": [], "compare_fields": [], "options": dict(_DEFAULT_OPTIONS)},
        "unmapped": {"source": [], "target": []},
        "warnings": [reason],
        "degraded": True,
        "degraded_reason": reason,
        "provider": None,
        "fallback": False,
        "provider_notice": None,
    }


def _normalize(
    payload: Any,
    source_cols: list[str],
    target_cols: list[str],
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Gate + normalize the model output into the Step-4 ``display`` shape.

    Enforces the boundary deterministically (the model is never trusted):
    * Existence gate — a named column must resolve to a real column on its side
      (exact, then case/punctuation-insensitive). Anything else — an invented
      name or a leaked data VALUE — is dropped with a warning.
    * 1:1 dedupe, first-wins, matching the prior heuristic's behavior.
    """
    mappings = payload.get("mappings") if isinstance(payload, dict) else None
    if not isinstance(mappings, list):
        return []

    src_lookup = {_norm(c): c for c in source_cols}
    tgt_lookup = {_norm(c): c for c in target_cols}
    src_exact = set(source_cols)
    tgt_exact = set(target_cols)

    used_src: set[str] = set()
    used_tgt: set[str] = set()
    display: list[dict[str, Any]] = []

    for item in mappings:
        if not isinstance(item, dict):
            continue
        sc_raw = str(item.get("source_column") or "").strip()
        tc_raw = str(item.get("target_column") or "").strip()
        sc = sc_raw if sc_raw in src_exact else src_lookup.get(_norm(sc_raw))
        tc = tc_raw if tc_raw in tgt_exact else tgt_lookup.get(_norm(tc_raw))

        if not sc or not tc:
            if sc_raw or tc_raw:
                warnings.append(
                    f"Dropped a mapping naming a column not in the selected data "
                    f"(source={sc_raw!r}, target={tc_raw!r}) — no invented columns "
                    f"or value-level pairs are accepted."
                )
            continue
        if sc in used_src or tc in used_tgt:
            continue  # 1:1, first-wins

        used_src.add(sc)
        used_tgt.add(tc)
        role = COMPARE_ROLE if _is_compare_role(item.get("role")) else KEY_ROLE
        display.append(
            {
                "logical": str(item.get("label") or item.get("concept") or "").strip(),
                "source_col": sc,
                "target_col": tc,
                "role": role,
                "reason": str(item.get("reason") or item.get("evidence") or "").strip(),
                "provenance": "generated",
            }
        )
    return display


def _clean_unmapped(
    payload: Any, source_cols: list[str], target_cols: list[str]
) -> dict[str, list[str]]:
    """Validate the model's ``unmapped`` lists against the real column sets.

    Purely informational (surfaced for the audit trail); never invents names.
    """
    raw = payload.get("unmapped") if isinstance(payload, dict) else None
    raw = raw if isinstance(raw, dict) else {}

    def _keep(values: Any, allowed: list[str]) -> list[str]:
        allow_norm = {_norm(c): c for c in allowed}
        out: list[str] = []
        seen: set[str] = set()
        for v in values if isinstance(values, list) else []:
            resolved = str(v) if str(v) in set(allowed) else allow_norm.get(_norm(v))
            if resolved and resolved not in seen:
                seen.add(resolved)
                out.append(resolved)
        return out

    return {
        "source": _keep(raw.get("source"), source_cols),
        "target": _keep(raw.get("target"), target_cols),
    }


def _to_mapping(display: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the backend-consumption buckets from the display rows."""
    key_fields = [
        {"source_col": r["source_col"], "target_col": r["target_col"]}
        for r in display
        if r["role"] == KEY_ROLE
    ]
    compare_fields = [
        {"source_col": r["source_col"], "target_col": r["target_col"]}
        for r in display
        if r["role"] == COMPARE_ROLE
    ]
    return {
        "key_fields": key_fields,
        "compare_fields": compare_fields,
        "options": dict(_DEFAULT_OPTIONS),
    }


def infer_field_mapping(
    source_df: pd.DataFrame, target_df: pd.DataFrame
) -> dict[str, Any]:
    """Infer the source→target FIELD mapping from sampled data (LLM).

    Never raises on LLM failure: returns a ``degraded`` result the frontend
    treats as "no auto-mapping, build the field mapping manually". The returned
    ``display`` / ``mapping`` match the shape produced by the old ``/automap``
    heuristic, so it slots straight into the existing Step-4 table state.
    """
    if not get_settings().any_llm_configured:
        return _degraded(
            "No AI provider is configured (GROQ_API_KEY / OPENAI_API_KEY) — "
            "build the field mapping manually."
        )

    source_cols = [str(c) for c in source_df.columns]
    target_cols = [str(c) for c in target_df.columns]
    user_payload = {
        "source": {"columns": _sample_columns(source_df)},
        "target": {"columns": _sample_columns(target_df)},
    }

    if not user_payload["source"]["columns"] or not user_payload["target"]["columns"]:
        return _degraded(
            "Source or target data has no populated columns to infer a mapping "
            "from — build the field mapping manually."
        )

    try:
        client = build_llm_client()
        payload = client.complete_json(
            [
                {"role": "system", "content": _SYSTEM_PREAMBLE},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, default=str)},
            ]
        )
    except Exception as exc:  # noqa: BLE001 — degradation is the contract
        logger.warning("Field-mapping inference failed; degrading to manual. %s", exc)
        return _degraded(f"AI field-mapping inference failed: {exc}")

    warnings: list[str] = []
    display = _normalize(payload, source_cols, target_cols, warnings)
    mapping = _to_mapping(display)
    unmapped = _clean_unmapped(payload, source_cols, target_cols)

    outcome = get_last_llm_outcome()
    return {
        "display": display,
        "mapping": mapping,
        "unmapped": unmapped,
        "warnings": warnings,
        "degraded": False,
        "degraded_reason": None,
        "provider": (outcome.provider_used if outcome and outcome.provider_used else None),
        "fallback": bool(outcome and outcome.fallback_occurred),
        "provider_notice": outcome.notice if outcome else None,
    }
