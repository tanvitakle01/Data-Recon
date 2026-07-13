"""Deterministic placeholder contract compiler.

This is NOT the LLM. It builds a minimal, valid draft contract straight from
the mapping sheet using fixed rules, so the full lifecycle
(compile -> validate -> approve -> reconcile) is runnable and testable while the
Groq compile phase remains scaffolding. It emits only contract JSON — the same
data shape the LLM will eventually produce — so nothing downstream cares which
compiler was used.

Mapping-sheet row contract (flexible keys accepted):
    {"source_col": <str>, "target_col": <str>, "role": "key"|"compare"|...}
Roles containing "compare"/"quantity"/"measure" become compare fields; all
other mapped rows become business-key components. Real parsed mapping sheets
(``mapping_sheet_parser.parse_mapping_sheet``) never populate "role" — for
those, the same hints are matched against the row's technical field,
description and target label instead (see ``_is_compare_row``).

The mapping sheet may also arrive as the full parsed-worksheet payload from
``mapping_sheet_parser.parse_mapping_sheet``; in that case the inferred
``mapping_candidates`` (falling back to raw ``rows``) are used as the rows,
and each row's "technical_field" is preferred when resolving against the real
schemas — see ``_resolve_field``.
"""

from __future__ import annotations

import re
from typing import Any

from backend.recon_engine.compiler.base import ContractCompiler, ContractCompilerError
from backend.recon_engine.models.contract import (
    BusinessKeyField,
    CompareField,
    ContractOperation,
    DraftContract,
    MatchType,
)
from backend.recon_engine.models.rules import BusinessRules, normalize_business_rules

_COMPARE_ROLE_HINTS = ("compare", "quantity", "qty", "measure", "value", "amount")

# Normalised condition labels for the conditional_* operations.
_COND_MAP = {
    "numeric": "numeric",
    "non_numeric": "non_numeric",
    "nonnumeric": "non_numeric",
    "non_empty": "non_empty",
    "nonempty": "non_empty",
}


def _clean_token(token: str) -> str:
    """Trim quotes and trailing sentence punctuation off a captured value."""
    return token.strip().strip("'\"").rstrip(".;,").strip()


def _condition(raw: str) -> str | None:
    key = _clean_token(raw).lower().replace(" ", "_").replace("-", "_")
    return _COND_MAP.get(key)


def compile_instruction_to_ops(field: str, instruction: str) -> list[ContractOperation]:
    """Deterministically translate ONE plain-language directive on ``field`` into
    executable operations. Returns ``[]`` when nothing is recognised (the caller
    then preserves the text in notes rather than guessing).

    This is the offline counterpart to the Groq compiler's value-transformation
    mapping — it exists so the degraded (no-LLM) path still turns the common
    rules into operations instead of dropping them into notes. It intentionally
    covers only unambiguous phrasings; anything else falls through to the LLM.
    """
    seg = (instruction or "").strip()
    low = seg.lower()
    if not seg:
        return []

    if re.search(r"remove\s+leading\s+zero", low):
        return [ContractOperation(op="remove_leading_zeros", field=field)]

    m = re.search(r"replace\s+(.+?)\s+with\s+(.+)", seg, re.I)
    if m:
        return [ContractOperation(
            op="replace_value", field=field,
            params={"from": _clean_token(m.group(1)), "to": _clean_token(m.group(2))},
        )]

    m = re.search(r"(?:add\s+)?prefix\s+(.+)", seg, re.I)
    if m and "replace" not in low:
        rest = m.group(1)
        cond = None
        when = re.search(r"\bwhen\s+(.+)$", rest, re.I)
        if when:
            cond = _condition(when.group(1))
            rest = rest[: when.start()]
        value = _clean_token(rest)
        if value:
            if cond:
                return [ContractOperation(
                    op="conditional_prefix", field=field,
                    params={"value": value, "condition": cond},
                )]
            return [ContractOperation(op="prepend_prefix", field=field, params={"value": value})]

    m = re.search(r"(?:append|add\s+suffix|suffix)\s+(.+)", seg, re.I)
    if m:
        rest = m.group(1)
        cond = None
        when = re.search(r"\bwhen\s+(.+)$", rest, re.I)
        if when:
            cond = _condition(when.group(1))
            rest = rest[: when.start()]
        value = _clean_token(rest)
        if value:
            if cond:
                return [ContractOperation(
                    op="conditional_suffix", field=field,
                    params={"value": value, "condition": cond},
                )]
            return [ContractOperation(op="append_suffix", field=field, params={"value": value})]

    if re.search(r"\b(upper\s?case|to\s+upper)\b", low):
        return [ContractOperation(op="uppercase", field=field)]
    if re.search(r"\b(lower\s?case|to\s+lower)\b", low):
        return [ContractOperation(op="lowercase", field=field)]
    if re.search(r"\b(trim|strip)\b", low):
        return [ContractOperation(op="trim_string", field=field)]

    return []


def _compile_directives(field: str, text: str) -> tuple[list[ContractOperation], list[str]]:
    """Split ``text`` into directives (on ';' / newlines) and compile each.

    Returns ``(operations, unrecognised_segments)`` so the caller can compile
    what it understands and preserve the rest verbatim in notes.
    """
    operations: list[ContractOperation] = []
    unrecognised: list[str] = []
    for segment in re.split(r"[;\n]+", text or ""):
        seg = segment.strip()
        if not seg:
            continue
        ops = compile_instruction_to_ops(field, seg)
        if ops:
            operations.extend(ops)
        else:
            unrecognised.append(seg)
    return operations, unrecognised


def _get(row: dict[str, Any], *keys: str) -> str | None:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return str(row[k])
    return None


def _sheet_rows(mapping_sheet: list[dict[str, Any]] | dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise the mapping-sheet input to a flat list of row dicts."""
    if isinstance(mapping_sheet, dict):
        return mapping_sheet.get("mapping_candidates") or mapping_sheet.get("rows") or []
    return mapping_sheet


def _is_compare_row(row: dict[str, Any]) -> bool:
    """Best-effort key-vs-compare classification.

    The legacy simple template sets an explicit "role"/"logical"/"type" — used
    first if present. Real enterprise sheets parsed by
    ``mapping_sheet_parser`` never set that key, so we also scan the row's
    technical field, description and target label for the same hint words
    (e.g. a technical field named "ReqDlvQty" or a description mentioning
    "quantity"). This is a heuristic fallback only — Groq's semantic reading
    of the full mapping context is the reliable path; this just keeps the
    offline stub from dumping every field into the business key.
    """
    explicit_role = (_get(row, "role", "logical", "type") or "").lower()
    if explicit_role:
        return any(hint in explicit_role for hint in _COMPARE_ROLE_HINTS)
    haystack = " ".join(
        str(row[k]).lower()
        for k in ("technical_field", "description", "target_field", "source_field")
        if row.get(k)
    )
    return any(hint in haystack for hint in _COMPARE_ROLE_HINTS)


def _resolve_field(primary: str | None, technical: str | None, schema: list[str]) -> str | None:
    """Match a mapping-sheet field reference to an actual schema column.

    Mapping sheets frequently name a column three different ways: a
    human-readable label, a table-qualified source reference, and a technical
    field name. Only names that literally appear in the real schema are
    usable downstream (Gate 1 enforces this) — so try, in order, an exact
    match, a case-insensitive match, and the same two checks against the
    row's "technical_field" (which most often lines up with the schema's
    technical column names). Returns ``None`` if nothing resolves — callers
    must not guess.
    """
    schema_by_lower = {c.lower(): c for c in schema}
    for candidate in (primary, technical):
        if not candidate:
            continue
        if candidate in schema:
            return candidate
        match = schema_by_lower.get(candidate.lower())
        if match:
            return match
    return None


class StubContractCompiler(ContractCompiler):
    name = "stub"

    def compile(
        self,
        *,
        mapping_sheet: list[dict[str, Any]] | dict[str, Any],
        rules: str,
        business_rules: BusinessRules | None = None,
        source_schema: list[str],
        target_schema: list[str],
        comparison_type: str,
        source_type: str,
        target_type: str,
    ) -> DraftContract:
        rows = _sheet_rows(mapping_sheet)
        if not rows:
            raise ContractCompilerError("Mapping sheet is empty; nothing to compile.")

        operations: list[ContractOperation] = []
        business_key: list[BusinessKeyField] = []
        compare_fields: list[CompareField] = []
        unresolved: list[str] = []
        note_parts: list[str] = []

        for row in rows:
            raw_src = _get(row, "source_col", "source_field", "source")
            raw_tgt = _get(row, "target_col", "target_field", "target")
            technical = _get(row, "technical_field")
            if not raw_src and not raw_tgt:
                continue

            # Schema-valid names only — never the sheet's raw label/reference.
            src = _resolve_field(raw_src, technical, source_schema)
            tgt = _resolve_field(raw_tgt, technical, target_schema)
            if not src or not tgt:
                unresolved.append(f"{raw_src or '?'} -> {raw_tgt or '?'}")
                continue

            if _is_compare_row(row):
                # Normalise numeric measures on the source side before comparison.
                operations.append(ContractOperation(op="numeric_cast", field=src))
                compare_fields.append(
                    CompareField(source_field=src, target_field=tgt, match_type=MatchType.EXACT)
                )
            else:
                # Normalise key fields deterministically (string + trim).
                operations.append(ContractOperation(op="identity_cast_string", field=src))
                operations.append(ContractOperation(op="trim_string", field=src))
                business_key.append(BusinessKeyField(source_field=src, target_field=tgt))

            # Compile the mapping sheet's own transformation text into executable
            # operations on this field — the whole point of the redesign is that
            # such rules never live only in notes. Unrecognised text is preserved.
            transform_text = _get(row, "transformation", "transformation_rule")
            if transform_text:
                row_ops, leftover = _compile_directives(src, transform_text)
                operations.extend(row_ops)
                for seg in leftover:
                    note_parts.append(f"[mapping/{src}] {seg}")

        if not business_key:
            detail = f" Unresolved rows: {unresolved}." if unresolved else ""
            raise ContractCompilerError(
                "Mapping sheet produced no business-key fields resolvable against the "
                "supplied source/target schemas; at least one key is required." + detail
            )

        # ── user transformation rules -> operations (never notes if compilable) ──
        # Each rule names a field the user recognises; resolve it to a real source
        # column exactly like a mapping row, then compile the instruction. Only
        # rules that resolve AND compile become operations; everything else (an
        # unresolved field, an instruction we can't parse, or matching/filter
        # rules the stub doesn't interpret) is preserved verbatim in notes for
        # the human reviewer — no executable logic is fabricated or lost.
        normalized_rules = normalize_business_rules(business_rules)
        for rule in normalized_rules.transformation_rules:
            src = _resolve_field(rule.field, None, source_schema)
            if not src:
                note_parts.append(f"[unresolved transform] {rule.field}: {rule.instruction}")
                continue
            rule_ops, leftover = _compile_directives(src, rule.instruction)
            operations.extend(rule_ops)
            for seg in leftover:
                note_parts.append(f"[transform/{rule.field}] {seg}")

        # Matching/filter rules are left for the LLM compiler; the stub preserves
        # them verbatim rather than guessing at compare/filter semantics.
        for label, extra in (
            ("matching", normalized_rules.matching_rules),
            ("filter", normalized_rules.filter_rules),
        ):
            for rule in extra:
                note_parts.append(f"[{label}/{rule.field}] {rule.instruction}")

        notes_parts = [p for p in ((rules or "").strip() or None,) if p]
        notes_parts.extend(note_parts)
        if unresolved:
            notes_parts.append(
                "Skipped rows with no schema-matching field: " + "; ".join(unresolved)
            )

        return DraftContract(
            comparison_type=comparison_type,
            source_type=source_type,
            target_type=target_type,
            operations=operations,
            business_key=business_key,
            compare_fields=compare_fields,
            source_schema=list(source_schema),
            target_schema=list(target_schema),
            compiler=self.name,
            notes=" | ".join(notes_parts) or None,
        )
