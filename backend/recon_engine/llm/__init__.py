"""Provider-agnostic LLM layer with automatic Groq→OpenAI failover.

Public surface:

* :func:`build_llm_client` — the Groq(primary)→OpenAI(fallback) client, a
  drop-in for the old ``GroqJSONClient`` (``complete_json(messages)``).
* :func:`get_last_llm_outcome` / :func:`reset_llm_outcome` — read/clear which
  provider served the last request (routes use this to log + notify).
* Error types and the retryable-failure classifier.
"""

from backend.recon_engine.llm.base import LLMProvider
from backend.recon_engine.llm.errors import (
    AllProvidersUnavailableError,
    RetryableLLMError,
    is_retryable_exception,
)
from backend.recon_engine.llm.failover import (
    ALL_UNAVAILABLE_NOTICE,
    FALLBACK_NOTICE,
    FailoverLLMClient,
    LLMOutcome,
    build_llm_client,
    get_last_llm_outcome,
    reset_breaker,
    reset_llm_outcome,
)
from backend.recon_engine.llm.openai_client import OpenAIJSONClient

__all__ = [
    "LLMProvider",
    "AllProvidersUnavailableError",
    "RetryableLLMError",
    "is_retryable_exception",
    "ALL_UNAVAILABLE_NOTICE",
    "FALLBACK_NOTICE",
    "FailoverLLMClient",
    "LLMOutcome",
    "build_llm_client",
    "get_last_llm_outcome",
    "reset_breaker",
    "reset_llm_outcome",
    "OpenAIJSONClient",
]
