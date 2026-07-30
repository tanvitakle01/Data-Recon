"""Auto-mode pipeline: a LangGraph StateGraph driving the 7-step reconciliation
wizard end-to-end without human approval screens.

Manual mode is untouched by this package — every node here calls the exact
same business-logic functions the manual wizard's routes already call
(``pair_values``, ``service.compile_draft``, ``service.run_reconciliation``,
etc.), directly rather than via HTTP, so behavior never drifts between the
two modes.
"""

from backend.recon_engine.auto_pipeline.graph import run_auto_pipeline

__all__ = ["run_auto_pipeline"]
