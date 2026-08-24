"""Caller-supplied traceability context for :func:`FailoverLLMClient.
complete_json` — a request-scoped ``ContextVar``, mirroring ``failover.py``'s
own ``_CURRENT_OUTCOME`` pattern, so ``complete_json``'s signature never
changes and callers that never set a context (Manual mode, tests) keep
working exactly as before with ``run_id``/``batch_id``/``node`` simply
``None`` in the logged row.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMCallContext:
    run_id: str | None = None
    batch_id: str | None = None
    node: str | None = None


_CTX: contextvars.ContextVar[LLMCallContext] = contextvars.ContextVar(
    "recon_llm_call_context", default=LLMCallContext()
)


def set_llm_call_context(*, run_id: str | None = None, batch_id: str | None = None, node: str | None = None) -> None:
    _CTX.set(LLMCallContext(run_id=run_id, batch_id=batch_id, node=node))


def get_llm_call_context() -> LLMCallContext:
    return _CTX.get()


def clear_llm_call_context() -> None:
    _CTX.set(LLMCallContext())
