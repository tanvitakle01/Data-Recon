"""Azure AI Foundry chat client that returns parsed JSON — the sole provider.

Thin subclass of :class:`~backend.recon_engine.llm.openai_compatible.
OpenAICompatibleJSONClient`, calling the AI-Adoption-COE Azure AI Foundry
OpenAI-compatible endpoint. Unlike the other tiers, authentication is not a
static API key: it's an Azure AD bearer token obtained via
``DefaultAzureCredential`` (az login / managed identity / env-based service
principal), refreshed on demand by the token provider the ``openai`` SDK
calls for each request. ``truststore`` is injected into the SSL context so
Azure AD/Foundry TLS is trusted through the corporate proxy. The ``openai``
and ``azure-identity`` packages are optional dependencies of the base class /
this module respectively.
"""

from __future__ import annotations

import truststore

truststore.inject_into_ssl()

from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from backend.recon_engine.config import get_settings
from backend.recon_engine.llm.openai_compatible import OpenAICompatibleJSONClient


class AzureFoundryJSONClient(OpenAICompatibleJSONClient):
    """Minimal Azure AI Foundry wrapper: messages in, parsed-JSON object out."""

    name = "azure_foundry"

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        if api_key is None:
            credential = DefaultAzureCredential()
            api_key = get_bearer_token_provider(credential, "https://ai.azure.com/.default")
        super().__init__(
            api_key=api_key,
            model=model or settings.azure_foundry.model,
            base_url=settings.azure_foundry.base_url,
            provider_label="Azure AI Foundry",
            api_key_env="AZURE_FOUNDRY_MODEL",
            model_env="AZURE_FOUNDRY_MODEL",
        )

    @property
    def is_configured(self) -> bool:
        # Auth comes from the ambient Azure AD credential chain, not a key we
        # hold here, so "configured" means only that a model id was supplied.
        return bool(self._model)
