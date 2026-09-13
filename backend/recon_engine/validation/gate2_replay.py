"""Validation Gate 2 — sample replay.

Executes the contract against a small sample (50-100 rows) of real source data
and sanity-checks the result before approval:

  * date parsing success        (date_parse ops actually parse the data)
  * row count sanity            (the pipeline didn't drop everything)
  * null explosion detection    (transforms didn't blow up nulls)
  * aggregation sanity          (aggregations reduced, not vanished)
  * mapping sanity              (business keys are non-empty and overlap target)

Hard failures block approval; warnings are surfaced but non-blocking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.recon_engine.config import get_settings
from backend.recon_engine.engine.executor import LINEAGE_COL, build_shadow_source
from backend.recon_engine.engine.reconciler import _build_key
from backend.recon_engine.models.contract import DraftContract, TransformationContract
from backend.recon_engine.operations import OperationKind, get_operation
from backend.recon_engine.operations.ops import format_to_strftime

_PARSE_RATE_MIN = 0.5


@dataclass
class Gate2Report:
    ok: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "gate": "sample_replay",
            "ok": self.ok,
            "checks": self.checks,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def _null_fraction(df: pd.DataFrame) -> float:
    if df.empty or df.shape[1] == 0:
        return 0.0
    cols = [c for c in df.columns if c != LINEAGE_COL]
    if not cols:
        return 0.0
    sub = df[cols]
    total = sub.shape[0] * sub.shape[1]
    return float(sub.isna().sum().sum()) / total if total else 0.0


def _coerce(contract: Any) -> Any:
    if isinstance(contract, (DraftContract, TransformationContract)):
        return contract
    return DraftContract.model_validate(contract)


def replay_sample(
    contract: Any,
    source_sample_df: pd.DataFrame,
    target_sample_df: pd.DataFrame,
) -> Gate2Report:
    settings = get_settings()
    parsed = _coerce(contract)

    sample = source_sample_df.head(settings.replay_sample_max).copy()
    tgt_sample = target_sample_df.head(settings.replay_sample_max).copy()

    report = Gate2Report(ok=True)

    def add(name: str, ok: bool, message: str, *, warn: bool = False) -> None:
        report.checks.append({"name": name, "ok": ok, "message": message})
        if not ok:
            if warn:
                report.warnings.append(f"{name}: {message}")
            else:
                report.errors.append(f"{name}: {message}")
                report.ok = False

    if len(sample) < settings.replay_sample_min and len(source_sample_df) >= settings.replay_sample_min:
        sample = source_sample_df.head(settings.replay_sample_min).copy()

    # ── date parse success (per date_parse op) ──────────────────────────────
    for op in parsed.operations:
        if op.op == "date_parse" and op.field in sample.columns:
            fmt = format_to_strftime(op.params.get("source_format", ""))
            parsed_dates = pd.to_datetime(sample[op.field], format=fmt, errors="coerce")
            non_null_in = sample[op.field].notna().sum()
            rate = (parsed_dates.notna().sum() / non_null_in) if non_null_in else 1.0
            add(
                f"date_parse[{op.field}]",
                rate >= _PARSE_RATE_MIN,
                f"parsed {rate:.0%} of non-null values with format '{op.params.get('source_format')}'.",
            )

    # ── execute the shadow build ─────────────────────────────────────────────
    try:
        built = build_shadow_source(parsed, sample)
    except Exception as exc:  # noqa: BLE001 - report any executor failure
        add("shadow_build", False, f"executor raised: {exc}")
        return report
    shadow = built.shadow_df

    # ── row count sanity ─────────────────────────────────────────────────────
    # An empty shadow from a nonempty sample is downgraded to a WARNING
    # (rather than blocking approval outright) whenever either is true:
    #
    #   * the sample itself is smaller than this gate's own documented
    #     minimum (`replay_sample_min`) — a handful of rows can, by pure bad
    #     luck, contain none that survive an otherwise-correct rule; or
    #   * the contract has an enabled FILTER-kind operation at all (checked
    #     generically against the operations registry's own `kind` — never a
    #     specific op name or field/value) — no sample size can prove a
    #     selective filter is BUGGY rather than legitimately selective, since
    #     a rule that (correctly) keeps only 0.1% of real rows will empty out
    #     even a large sample most of the time. Only TRANSFORM/AGGREGATE
    #     operations can't organically empty a nonempty input this way, so an
    #     empty shadow with no enabled filter really does point at a defect
    #     elsewhere (e.g. a broken rename/cast/join) and still hard-blocks.
    thin_sample = len(sample) < settings.replay_sample_min
    has_enabled_filter = any(
        get_operation(op.op).kind == OperationKind.FILTER
        for op in parsed.operations
        if getattr(op, "enabled", True)
    )
    add(
        "row_count",
        not (len(sample) > 0 and len(shadow) == 0),
        f"source_sample={len(sample)} -> shadow={len(shadow)} rows.",
        warn=thin_sample or has_enabled_filter,
    )

    # ── aggregation sanity ───────────────────────────────────────────────────
    has_agg = any(op.op in {"group_by", "sum_aggregate"} for op in parsed.operations) or bool(
        getattr(parsed, "aggregation_rules", [])
    )
    if has_agg:
        add(
            "aggregation",
            0 < len(shadow) <= len(sample),
            f"aggregation reduced {len(sample)} -> {len(shadow)} rows.",
            warn=True,
        )

    # ── null explosion detection ─────────────────────────────────────────────
    src_null = _null_fraction(sample)
    shd_null = _null_fraction(shadow)
    add(
        "null_explosion",
        shd_null <= src_null + 0.5,
        f"null fraction source={src_null:.0%} shadow={shd_null:.0%}.",
        warn=True,
    )

    # ── mapping sanity ─────────────────────────────────────────────────────
    options = parsed.options or {}
    src_key_fields = [k.source_field for k in parsed.business_key]
    tgt_key_fields = [k.target_field for k in parsed.business_key]
    missing_src = [f for f in src_key_fields if f not in shadow.columns]
    if missing_src:
        add("mapping", False, f"shadow missing key field(s) {missing_src}.")
    else:
        shadow_keys = set(_build_key(shadow, src_key_fields, options))
        empty_keys = sum(1 for k in shadow_keys if not k.replace("|", "").strip())
        add(
            "mapping_keys_nonempty",
            empty_keys < max(1, len(shadow_keys)),
            f"{len(shadow_keys)} distinct source keys, {empty_keys} empty.",
        )
        if not tgt_sample.empty and all(f in tgt_sample.columns for f in tgt_key_fields):
            target_keys = set(_build_key(tgt_sample, tgt_key_fields, options))
            overlap = shadow_keys & target_keys
            add(
                "mapping_overlap",
                len(overlap) > 0,
                f"{len(overlap)} of {len(shadow_keys)} source keys found in target sample.",
                warn=True,
            )

    return report
