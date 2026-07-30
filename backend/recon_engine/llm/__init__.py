"""Provider-agnostic LLM layer with automatic Groq→Gemini→Cerebras→OpenRouter
failover.

Public surface:

* :func:`build_llm_client` — the Groq(primary)→Gemini→Cerebras→OpenRouter
  (last resort, free models) client, a drop-in for the old ``GroqJSONClient``
  (``complete_json(messages)``).
* :func:`get_last_llm_outcome` / :func:`reset_llm_outcome` — read/clear which
  provider served the last request (routes use this to log + notify).
* Error types and the retryable-failure classifier.
"""

from backend.recon_engine.llm.base import LLMProvider
from backend.recon_engine.llm.cerebras_client import CerebrasJSONClient
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
from backend.recon_engine.llm.gemini_client import GeminiJSONClient
from backend.recon_engine.llm.openai_client import OpenAIJSONClient
from backend.recon_engine.llm.openrouter_client import OpenRouterJSONClient

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
    "GeminiJSONClient",
    "CerebrasJSONClient",
    "OpenRouterJSONClient",
]
