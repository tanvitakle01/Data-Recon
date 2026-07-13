"""Contract compiler interface.

A compiler turns a mapping sheet + free-text rules + the *real* source/target
schemas into a :class:`DraftContract`. That is its ONLY job. A compiler must
never execute a transformation, emit code, or touch data — it produces contract
JSON and nothing else. The deterministic engine does all execution.
"""

from __future__ import annotations

import abc
from typing import Any

from backend.recon_engine.models.contract import DraftContract
from backend.recon_engine.models.rules import BusinessRules


class ContractCompilerError(RuntimeError):
    """Raised when a compiler cannot produce a draft contract."""


class ContractCompiler(abc.ABC):
    """Base class for all contract compilers (Groq, deterministic stub, ...)."""

    #: short provenance tag stored on the draft (e.g. "groq", "stub").
    name: str = "base"

    @abc.abstractmethod
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
        """Produce a draft Transformation Contract (JSON data only).

        Args:
            mapping_sheet: either a plain list of mapping rows, each a dict of
                column -> value (e.g. ``{"source_col": "Plnt", "target_col": "LOCID", "role": "key"}``),
                or the full parsed-worksheet payload produced by
                ``mapping_sheet_parser.parse_mapping_sheet`` (``sheet_name`` /
                ``headers`` / ``rows`` / ``mapping_candidates`` / notes).
            rules: legacy free-text rules/instructions. Only meaningful when
                ``business_rules`` is empty — the caller (``service.compile_draft``)
                guarantees the two are never both populated.
            business_rules: structured transformation/matching/filter rules
                from the Business Rules Builder. The preferred instruction
                channel; a compiler should use this over ``rules`` whenever
                it is non-empty.
            source_schema / target_schema: the actual field names retrieved from
                the S/4 connector, IBP connector, or uploaded file — never assumed.
            comparison_type: e.g. ``"sales_history"``.
            source_type / target_type: e.g. ``"s4"`` / ``"ibp"`` / ``"excel"``.

        Returns:
            A :class:`DraftContract`. It is NOT validated or approved here; it
            must still pass Gate 1, Gate 2, and human approval.
        """
        raise NotImplementedError
