"""Deterministic verification — pipeline step 4 (MANDATORY, non-negotiable).

Every LLM-proposed pairing — a single op or an ORDERED CHAIN of ops — is
re-executed through the REAL allow-listed operation(s) against the REAL
source value. Nothing reaches the review UI or the library without passing
this — see ``pipeline.pair_values``.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.recon_engine.operations.registry import get_operation


def verify_chain(ops: list[dict[str, Any]], field: str, source_value: str) -> tuple[bool, str]:
    """Apply an ORDERED sequence of allow-listed ops to ``source_value``.

    Each step's output feeds the next step's input; the caller compares the
    FINAL result against the claimed target — this function does not know
    the claim. Returns ``(ok, produced_value_or_reason)``. ``ok=False`` means
    the chain is empty, a step's op isn't allow-listed, its params are
    invalid, or it raised — every case is a rejection, never a crash.
    """
    if not ops:
        return False, "empty operation chain"

    frame = pd.DataFrame({field: [source_value]})
    for step in ops:
        op = str(step.get("op") or "")
        params = step.get("params")
        if not isinstance(params, dict):
            return False, f"step {op!r} has non-dict params"
        try:
            spec = get_operation(op)
        except KeyError as exc:
            return False, str(exc)

        errors = spec.validate(field, params, [field])
        if errors:
            return False, "; ".join(errors)

        try:
            frame = spec.func(frame, field, params)
        except Exception as exc:  # noqa: BLE001 — any failure is a rejection, not a crash
            return False, f"operation {op!r} raised: {exc}"

    produced = frame[field].iloc[0]
    return True, "" if pd.isna(produced) else str(produced)


def verify_pair(op: str, params: dict[str, Any], field: str, source_value: str) -> tuple[bool, str]:
    """Single-op convenience wrapper around :func:`verify_chain`."""
    return verify_chain([{"op": op, "params": params}], field, source_value)


def verify_chain_bidirectional(
    ops: list[dict[str, Any]], field: str, value_a: str, value_b: str
) -> tuple[bool, str]:
    """Try ``ops`` applied to ``value_a`` (expecting ``value_b``), then the
    reverse. Some transforms are inherently one-directional (e.g. stripping
    zero-padding only ever removes digits, never adds them), and either side
    of a claimed pair can be the one that actually needs the transform — a
    source zero-padded relative to the target, or a target zero-padded
    relative to the source. Returns ``(ok, direction)``: ``direction`` is
    ``"forward"`` when ``ops(value_a) == value_b``, ``"reverse"`` when
    ``ops(value_b) == value_a``, or ``""`` when neither direction verifies.
    """
    passed, produced = verify_chain(ops, field, value_a)
    if passed and produced == value_b:
        return True, "forward"
    passed, produced = verify_chain(ops, field, value_b)
    if passed and produced == value_a:
        return True, "reverse"
    return False, ""
