"""Contract-driven deterministic reconciliation engine.

This package implements the reconciliation architecture in which:

    LLM output  = Data   (a Transformation Contract, JSON only)
    Engine output = Execution (a deterministic, allow-listed engine)

The LLM (Groq, see :mod:`backend.recon_engine.compiler.groq_compiler`) may ONLY
emit a Transformation Contract. It never generates or executes code. All data
transformation and reconciliation is performed by the deterministic engine
(:mod:`backend.recon_engine.engine`) using a fixed, allow-listed operation
registry (:mod:`backend.recon_engine.operations`).

See ``README.md`` in this package for the full architecture description.
"""

from backend.recon_engine.config import get_settings

__all__ = ["get_settings"]
