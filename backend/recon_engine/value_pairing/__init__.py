"""Deterministic-extraction + LLM-pairing + mandatory-verification pipeline.

Replaces the retired MDT-tier matchers (``matching.product``/``matching.location``)
for resolving Key-field identifier values (e.g. Material -> PRDID,
ProductionPlant -> LOCID) between a source and target dataset. See
``pipeline.pair_values`` for the entry point and step-by-step contract.
"""

from backend.recon_engine.value_pairing.pipeline import (
    pair_values,
    pair_values_deterministic_only,
)

__all__ = ["pair_values", "pair_values_deterministic_only"]
