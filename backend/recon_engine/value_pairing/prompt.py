"""LLM pairing prompt construction — pipeline step 3 (Transformation Discovery).

Given the COMPLETE distinct source/target value lists (minus only values
already covered by a stored library pairing), the exact-match registry the
deterministic identity pre-pass already found, and optional STM
(mapping-sheet) context, asks the
LLM to propose ``{source_value, target_value, ops, reason}`` pairs, where
``ops`` is an ORDERED LIST of allow-listed transform steps — most real-world
identifier transforms are more than one step (a prefix AND a suffix), so a
single-op schema biases the model toward stopping after the first step it
finds. Each op has a worked example, including at least one CHAINED example,
so the model matches a concrete multi-step pattern rather than reasoning from
a bare name. The prompt also teaches a find-the-match-then-derive-the-rule
strategy (see ``_SUBSTRING_DERIVATION_STRATEGY``): when one value is literally
a contiguous substring of another, the prefix/suffix chain is derived from
that overlap instead of guessed independently.

The LLM never performs exact matching and must never RETURN one either (see
``_SYSTEM_PREAMBLE``'s hard rule against ``target_value == source_value``) —
that is exclusively the deterministic identity pre-pass's job. A source value
that already has an exact match may still appear here so the model can
propose a genuinely ADDITIONAL, different target when the data/mapping sheet
supports one (e.g. ``S102 -> S102`` exact, ``S102 -> PLS102@SF500``
transform, both valid, both coexist) — it is never asked to choose between
them, only to check for an extra one.

Same safety posture as ``field_mapper.py``: sampled/capped inputs, strict
JSON, existence gated. Every claim here is a HYPOTHESIS — ``verify.py`` is
what actually re-executes the full chain against the real operation registry;
nothing here is trusted outright, and ``pipeline.py`` drops any candidate
that restates an exact match regardless of what the model returns.
"""

from __future__ import annotations

import json
from typing import Any

# Capped so a huge residual doesn't blow the token budget; values beyond this
# cap are simply not attempted this run — they fall through to "unpaired" and
# can be retried on a later run (e.g. once the library has grown).
_MAX_VALUES_PER_SIDE = 200

_VOCABULARY = """Allow-listed transform vocabulary — every step you use MUST
be one of these exact operation names, with the exact param keys shown.
Never invent an operation or a param key.

- prepend_prefix {"value": "<text>"}
  Example: source "5006", prepend_prefix {"value": "PL"} -> "PL5006".
- append_suffix {"value": "<text>"}
  Example: source "PL5006", append_suffix {"value": "@S67900"} -> "PL5006@S67900".
- conditional_prefix {"value": "<text>", "condition": "numeric"|"non_numeric"|"non_empty"}
  Example: source "5006" (numeric), conditional_prefix {"value": "PL", "condition": "numeric"} -> "PL5006".
- conditional_suffix {"value": "<text>", "condition": "numeric"|"non_numeric"|"non_empty"}
  Example: source "S101" (non_numeric), conditional_suffix {"value": "-DC", "condition": "non_numeric"} -> "S101-DC".
- replace_value {"from": "<text>", "to": "<text>"}
  Example: source "N01-FG01", replace_value {"from": "N01", "to": "T01"} -> "T01-FG01".
- remove_leading_zeros {} or {"min_width": <int>}
  Strips leading zeros from the embedded numeric run only, leaving any
  alpha prefix/suffix intact — it does NOT require the value to start with
  a digit. ``min_width`` (default 1) is the floor to strip down to instead
  of bare significant digits — use it when the padded code keeps a fixed
  minimum digit width rather than stripping to nothing.
  Example: source "005006", remove_leading_zeros {} -> "5006".
  Example: source "FG0006", target "FG06" -> remove_leading_zeros {"min_width": 2} -> "FG06".
  This transform can also run in the OTHER direction: if the TARGET is the
  zero-padded side (e.g. source "FG06", target "FG0006"), still propose
  ``remove_leading_zeros`` — verification tries it against both sides.

MULTI-STEP CHAINS: most real identifier transforms need MORE THAN ONE step —
do not stop after the first step just because it gets partway there. Chain as
many steps as needed, applied in order, until the result matches the target
EXACTLY.
  Worked chain example: source "5006", target "PL5006@S21400" —
  step 1: prepend_prefix {"value": "PL"} -> "PL5006"
  step 2: append_suffix {"value": "@S21400"} -> "PL5006@S21400"
  -> "ops": [{"op": "prepend_prefix", "params": {"value": "PL"}},
             {"op": "append_suffix", "params": {"value": "@S21400"}}]
"""

_SUBSTRING_DERIVATION_STRATEGY = """FIND-THE-MATCH-THEN-DERIVE-THE-RULE (do this BEFORE
guessing a prefix/suffix independently): check whether an unpaired source value appears
literally, as a CONTIGUOUS SUBSTRING, somewhere inside an unpaired target value — or the other
way around, an unpaired target value inside an unpaired source value. When it does, DERIVE the
transform from that overlap instead of guessing two candidates separately:
- Whatever text precedes the match -> that's the prefix to prepend.
- Whatever text follows the match -> that's the suffix to append.
- Propose BOTH together as ONE chained transformation (prepend_prefix + append_suffix), not
  two separately-guessed candidates.

  Worked example:
    Source: "S102"
    Target candidates include: "DCS102@S21400"

    "S102" is found inside "DCS102@S21400", starting after "DC" and ending before "@S21400".
      -> prefix = "DC", suffix = "@S21400"
      -> propose: prepend_prefix {"value": "DC"} + append_suffix {"value": "@S21400"}
      -> applying this to "S102" produces "DCS102@S21400" — matches the candidate exactly.

This is find-the-match-then-derive-the-rule, not guess-the-rule-then-search-for-a-match — it
narrows your search space dramatically and hands you the exact prefix/suffix text to use,
rather than guessing at values. It supplements the vocabulary above, it does not replace it:
you still write the proposal as an ops chain from that vocabulary, and every proposal is still
mechanically re-executed and rejected if it does not reproduce the target exactly.
"""

_SYSTEM_PREAMBLE = f"""You are identifying TRANSFORMATION-BASED value pairings
between a SOURCE dataset and a TARGET dataset for reconciliation — candidate
pairs that require an EXISTING, mechanically-verifiable transformation, never
a semantic guess and never a brand new kind of rule you invent from nothing.

You are given the COMPLETE distinct source_values and target_values lists,
PLUS an "exact_match_registry" — the pairs the deterministic engine already
found via exact string equality (source_value == target_value). That registry
is not your job to reproduce or second-guess.

{_VOCABULARY}

{_SUBSTRING_DERIVATION_STRATEGY}

You may also be given an "stm_context" — a mapping-sheet excerpt describing
the naming convention in prose. Use it, and the exact_match_registry, and the
find-the-match-then-derive-the-rule strategy above, as your EVIDENCE for
which transform applies — never propose an ops chain that isn't grounded in
one of these. It never substitutes for an ops chain that actually reproduces
the target from the source (your claim will be mechanically re-executed,
step by step, and rejected if the FINAL result does not reproduce the target
EXACTLY).

HARD RULES:
- NEVER propose a pair where target_value equals source_value. That IS an
  exact match — exclusively the deterministic engine's job, already recorded
  in exact_match_registry. Returning one is always wrong, even if you believe
  it's correct.
- A source_value that already appears in exact_match_registry MAY still be
  proposed here, but only with a DIFFERENT target_value backed by a genuine
  transform — you are checking for an ADDITIONAL valid pairing that coexists
  with the exact match, never restating or replacing it.
- Only propose a pair when you have a concrete ops chain — grounded in
  stm_context, the vocabulary's derivation strategy, or both — that
  mechanically transforms the exact source_value into the exact target_value.
  If no such transformation rule applies to a value, leave it out entirely;
  do not force a guess.
- Only reference source/target values that appear EXACTLY in the lists given.
  Never invent a value, an operation, or a param key outside the vocabulary.
- Each source value maps to at most one NEW (transformation-based) target
  value per response.

Respond with a single JSON object only, no prose/markdown/code fences:
{{
  "pairs": [
    {{"source_value": "<exact source value>",
      "target_value": "<exact target value, != source_value>",
      "ops": [{{"op": "<allow-listed op name>", "params": {{...}}}}, ...],
      "reason": "<one line: which values, which transform chain>"}},
    ...
  ]
}}
"""


def build_messages(
    *,
    candidate_source: list[str],
    candidate_target: list[str],
    exact_matches: dict[str, str] | None = None,
    mapping_sheet_context: Any = None,
) -> list[dict[str, str]]:
    user_payload: dict[str, Any] = {
        "source_values": candidate_source[:_MAX_VALUES_PER_SIDE],
        "target_values": candidate_target[:_MAX_VALUES_PER_SIDE],
    }
    if exact_matches:
        user_payload["exact_match_registry"] = dict(
            list(exact_matches.items())[:_MAX_VALUES_PER_SIDE]
        )
    if mapping_sheet_context:
        user_payload["stm_context"] = mapping_sheet_context
    return [
        {"role": "system", "content": _SYSTEM_PREAMBLE},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, default=str)},
    ]


def _parse_ops(raw: Any) -> list[dict[str, Any]] | None:
    """Structurally validate an ``ops`` list: non-empty, each step a dict with
    a non-blank ``op`` string and a dict ``params``. Returns ``None`` if
    malformed — the caller drops the whole candidate rather than guessing.
    """
    if not isinstance(raw, list) or not raw:
        return None
    steps: list[dict[str, Any]] = []
    for step in raw:
        if not isinstance(step, dict):
            return None
        op = str(step.get("op") or "").strip()
        params = step.get("params")
        if not op or not isinstance(params, dict):
            return None
        steps.append({"op": op, "params": params})
    return steps


def parse_candidates(payload: Any) -> list[dict[str, Any]]:
    """Gate the raw LLM payload into a list of structurally-valid candidates.

    Purely structural — does not check any op is allow-listed or that the
    chain actually works; ``verify.py`` is what does that. This only guards
    against a malformed/missing response shape.
    """
    pairs = payload.get("pairs") if isinstance(payload, dict) else None
    if not isinstance(pairs, list):
        return []

    out: list[dict[str, Any]] = []
    for item in pairs:
        if not isinstance(item, dict):
            continue
        source_value = str(item.get("source_value") or "").strip()
        target_value = str(item.get("target_value") or "").strip()
        ops = _parse_ops(item.get("ops"))
        if not source_value or not target_value or ops is None:
            continue
        out.append(
            {
                "source_value": source_value,
                "target_value": target_value,
                "ops": ops,
                "reason": str(item.get("reason") or "").strip(),
            }
        )
    return out
