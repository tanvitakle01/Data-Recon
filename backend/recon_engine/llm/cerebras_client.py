"""Cerebras chat client that returns parsed JSON — failover tier 3.

Thin subclass of :class:`~backend.recon_engine.llm.openai_compatible.
OpenAICompatibleJSONClient`, calling Cerebras's OpenAI-compatible endpoint. The
``openai`` SDK is an optional dependency, imported lazily on first use by the
base class.
"""

from __future__ import annotations

from backend.recon_engine.config import get_settings
from backend.recon_engine.llm.openai_compatible import OpenAICompatibleJSONClient


class CerebrasJSONClient(OpenAICompatibleJSONClient):
    """Minimal Cerebras wrapper: messages in, parsed-JSON object out."""

    name = "cerebras"

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        super().__init__(
            api_key=api_key if api_key is not None else settings.cerebras.api_key,
            model=model or settings.cerebras.model,
            base_url=settings.cerebras.base_url,
            provider_label="Cerebras",
            api_key_env="CEREBRAS_API_KEY",
            model_env="CEREBRAS_MODEL",
        )
