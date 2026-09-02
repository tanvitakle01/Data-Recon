"""Transformation script generation: LLM (Azure AI Foundry, no fallback) with a
deterministic fallback.

    Parsed mapping JSON + rules  →  TransformationScript (pandas `transform(df)`)

Graceful degradation is the contract here: the LLM is attempted only when
Azure AI Foundry is configured, and *any* failure (Azure AI Foundry down, bad
JSON, a script that fails static validation) falls back to the deterministic
generator, so the
workflow never dies because the LLM is unavailable. Every generated script
(either origin) must still pass static validation and the sandbox before a
user ever sees its output, and the user approves the transformed data, not
the script.

The generator consumes the mapping-sheet parser output exactly as produced
(``mapping_candidates`` / ``transformation_notes`` / ``join_conditions`` /
``filters`` / ``rows``) — no normalised format is required.
"""

from __future__ import annotations

import json
import re as _re
import uuid
from typing import Any

from backend.recon_engine.compiler.base import ContractCompilerError
from backend.recon_engine.config import get_settings
from backend.recon_engine.llm import build_llm_client
from backend.recon_engine.scripting.models import (
    GeneratedBy,
    TransformationScript,
    script_sha256,
)
from backend.recon_engine.scripting.validator import validate_script

_SYSTEM_PREAMBLE = """You are a data-transformation script generator for a
reconciliation tool.

You receive a parsed SAP/IBP mapping workbook (mapping_candidates,
transformation_notes, join_conditions, filters, raw rows), free-text rules,
and the real source/target schemas. Produce a Python function that transforms
the SOURCE dataframe so it can be compared against the target.

OUTPUT RULES — follow all of them:
1. Respond with a single JSON object only: {"explanation": [...], "script": "...",
   "confidence": 0.0-1.0}. No prose, no markdown, no code fences.
2. "explanation" is a list of short business-readable steps, one per
   transformation, in execution order (e.g. "Removed leading zeros from MATNR").
3. "script" must define exactly one function `transform(df)` that takes a
   pandas DataFrame and returns the transformed DataFrame. Nothing else may
   execute at module level.
4. Use only pandas/numpy operations via the pre-injected names `pd` and `np`
   (plus `math`, `re`, `datetime`). Do NOT write import statements.
5. NEVER use os, sys, subprocess, socket, requests, urllib, open, eval, exec,
   file or network access of any kind, or dataframe I/O (to_csv, read_excel,
   df.query, df.eval, …). Underscore/dunder attributes are forbidden.
6. Only reference columns present in source_schema. Rename source columns to
   their mapped target names. Apply transformation notes and rules to the
   relevant columns. Apply filters by dropping non-matching rows. Join
   conditions that reference tables you do not have must be skipped and noted
   in the explanation instead.
7. Be conservative: when a instruction is ambiguous, prefer no-op over a
   guess, and say so in the explanation.
"""


def _new_id() -> str:
    return "script_" + uuid.uuid4().hex[:12]


def _norm(text: Any) -> str:
    return _re.sub(r"[^a-z0-9]", "", str(text).lower())


# ── LLM generation (Azure-AI-Foundry-only, no fallback) ──

def _generate_with_llm(
    *,
    parsed_mapping: dict[str, Any] | list[dict[str, Any]],
    rules: str,
    source_schema: list[str],
    target_schema: list[str],
    actor: str,
) -> TransformationScript:
    client = build_llm_client()
    if not client.is_configured:
        raise ContractCompilerError("No LLM provider is configured (AZURE_FOUNDRY_MODEL).")

    user_payload = {
        "source_schema": source_schema,
        "target_schema": target_schema,
        "mapping_sheet": parsed_mapping,
        "rules_text": rules,
    }
    payload = client.complete_json(
        [
            {"role": "system", "content": _SYSTEM_PREAMBLE},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]
    )

    script_text = payload.get("script") if isinstance(payload, dict) else None
    if not script_text or not isinstance(script_text, str):
        raise ContractCompilerError("LLM response did not contain a script.")
    explanation = payload.get("explanation") or []
    if not isinstance(explanation, list):
        explanation = [str(explanation)]
    try:
        confidence = float(payload.get("confidence", 0.75))
    except (TypeError, ValueError):
        confidence = 0.75

    return TransformationScript(
        script_id=_new_id(),
        generated_by=GeneratedBy.AZURE_FOUNDRY,
        explanation=[str(step) for step in explanation],
        script=script_text,
        script_hash=script_sha256(script_text),
        source_columns=list(source_schema),
        target_columns=list(target_schema),
        confidence=max(0.0, min(1.0, confidence)),
        created_by=actor,
    )


# ── deterministic fallback ───────────────────────────────────────────────────

def _candidate_rows(
    parsed_mapping: dict[str, Any] | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if isinstance(parsed_mapping, dict):
        return parsed_mapping.get("mapping_candidates") or parsed_mapping.get("rows") or []
    return parsed_mapping or []


def _get(row: dict[str, Any], *keys: str) -> str | None:
    for k in keys:
        value = row.get(k)
        if value not in (None, ""):
            return str(value).strip()
    return None


# (regex on the transformation/rule text, python expression template, step template)
# {col} is the pandas column reference. Deterministic and intentionally narrow:
# only unambiguous instructions are automated; everything else is left as-is.
_TEXT_RULES: list[tuple[str, str, str]] = [
    (
        r"leading\s*zero",
        '{col} = {col}.astype(str).str.strip().str.lstrip("0")',
        "Removed leading zeros from {name}",
    ),
    (
        r"upper\s*case|to\s+upper",
        "{col} = {col}.astype(str).str.strip().str.upper()",
        "Converted {name} to upper case",
    ),
    (
        r"lower\s*case|to\s+lower",
        "{col} = {col}.astype(str).str.strip().str.lower()",
        "Converted {name} to lower case",
    ),
    (
        r"trim|whitespace",
        "{col} = {col}.astype(str).str.strip()",
        "Trimmed whitespace in {name}",
    ),
    (
        r"(cast|convert).{0,20}(string|text|char)",
        "{col} = {col}.astype(str).str.strip()",
        "Converted {name} to string",
    ),
    (
        r"numeric|number|integer|decimal|quantity",
        '{col} = pd.to_numeric({col}, errors="coerce")',
        "Converted {name} to a number",
    ),
    (
        r"date",
        '{col} = pd.to_datetime({col}, errors="coerce").dt.strftime("%Y-%m-%d")',
        "Normalized date format of {name} to YYYY-MM-DD",
    ),
]


def _fallback_script(
    *,
    parsed_mapping: dict[str, Any] | list[dict[str, Any]],
    rules: str,
    source_schema: list[str],
    target_schema: list[str],
    actor: str,
) -> TransformationScript:
    """Deterministic previewable script: renames + obvious transformations.

    Never fails: with nothing recognisable it produces an identity transform,
    keeping the workflow operational when Groq is unavailable.
    """
    candidates = _candidate_rows(parsed_mapping)
    target_norm = {_norm(c): c for c in target_schema}

    lines: list[str] = []
    explanation: list[str] = []
    renames: dict[str, str] = {}
    seen_sources: set[str] = set()

    for row in candidates:
        src = _get(row, "source_field", "source_col", "source")
        tgt = _get(row, "target_field", "target_col", "target")
        tech = _get(row, "technical_field")
        if not src or src not in source_schema or src in seen_sources:
            continue
        seen_sources.add(src)

        # Obvious transformations from the row's transformation text.
        note = (_get(row, "transformation", "transformation_rule", "rule") or "").lower()
        if note:
            for pattern, expr, step in _TEXT_RULES:
                if _re.search(pattern, note):
                    col = f'df["{src}"]'
                    lines.append(f"    {expr.format(col=col)}")
                    explanation.append(step.format(name=src))
                    break

        # Rename to the mapped target name. Enterprise sheets often carry a
        # business label in target_field and the real column in technical_field
        # — prefer whichever actually exists in the target schema.
        for candidate_name in (tgt, tech):
            if not candidate_name:
                continue
            resolved = target_norm.get(_norm(candidate_name))
            if resolved and resolved != src:
                renames[src] = resolved
                break

    if renames:
        pairs = ", ".join(f'"{s}": "{t}"' for s, t in renames.items())
        lines.append(f"    df = df.rename(columns={{{pairs}}})")
        for s, t in renames.items():
            explanation.append(f"Renamed {s} to {t}")

    if not lines:
        explanation.append("No transformations detected — data passed through unchanged")

    script_text = "def transform(df):\n    df = df.copy()\n" + (
        "\n".join(lines) + "\n" if lines else ""
    ) + "    return df\n"

    if rules.strip():
        explanation.append(
            "Note: free-text rules were not interpreted (AI generator unavailable); "
            "review the preview carefully."
        )

    return TransformationScript(
        script_id=_new_id(),
        generated_by=GeneratedBy.FALLBACK,
        explanation=explanation,
        script=script_text,
        script_hash=script_sha256(script_text),
        source_columns=list(source_schema),
        target_columns=list(target_schema),
        confidence=0.4 if lines else 0.2,
        created_by=actor,
    )


# ── orchestration: attempt Azure AI Foundry → deterministic fallback ────────

def generate_script(
    *,
    parsed_mapping: dict[str, Any] | list[dict[str, Any]],
    rules: str,
    source_schema: list[str],
    target_schema: list[str],
    actor: str = "system",
) -> tuple[TransformationScript, str | None]:
    """Generate a statically-valid TransformationScript.

    Returns ``(script, degraded_reason)``. ``degraded_reason`` is ``None``
    when Groq succeeded, otherwise a short description of why the
    deterministic fallback was used. Never raises because of Groq.
    """
    degraded_reason: str | None = None

    if get_settings().any_llm_configured:
        try:
            script = _generate_with_llm(
                parsed_mapping=parsed_mapping,
                rules=rules,
                source_schema=source_schema,
                target_schema=target_schema,
                actor=actor,
            )
            report = validate_script(script.script)
            if report.ok:
                return script, None
            degraded_reason = (
                "AI-generated script failed static validation: " + "; ".join(report.errors[:3])
            )
        except Exception as exc:  # noqa: BLE001 - degradation is the contract
            degraded_reason = f"AI script generation failed: {exc}"
    else:
        degraded_reason = "No AI provider is configured (AZURE_FOUNDRY_MODEL not set)."

    script = _fallback_script(
        parsed_mapping=parsed_mapping,
        rules=rules,
        source_schema=source_schema,
        target_schema=target_schema,
        actor=actor,
    )
    return script, degraded_reason
