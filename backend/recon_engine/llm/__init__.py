"""Provider-agnostic LLM layer. Azure AI Foundry is the only LLM provider in
the codebase — ``build_llm_client()`` wires up nothing else, and no other
provider client exists to fail over to.

Public surface:

* :func:`build_llm_client` — the Azure-AI-Foundry-only client
  (``complete_json(messages)``).
* :func:`get_last_llm_outcome` / :func:`reset_llm_outcome` — read/clear which
  provider served the last request (routes use this to log + notify).
* Error types and the retryable-failure classifier.
"""

from backend.recon_engine.llm.base import LLMProvider
from backend.recon_engine.llm.call_context import (
    clear_llm_call_context,
    get_llm_call_context,
    set_llm_call_context,
)
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
from backend.recon_engine.llm import session_override
from backend.recon_engine.llm.session_override import (
    LLMOverride,
    get_request_override,
    mask_secrets,
)
from backend.recon_engine.llm.azure_foundry_client import AzureFoundryJSONClient

__all__ = [
    "LLMProvider",
    "set_llm_call_context",
    "get_llm_call_context",
    "clear_llm_call_context",
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
    "AzureFoundryJSONClient",
    "session_override",
    "LLMOverride",
    "get_request_override",
    "mask_secrets",
]
