"""Environment-driven configuration for the reconciliation engine.

Nothing here has a hard dependency on Azure AI Foundry or any network service —
the settings below are only *read*; whether they are required is decided by
the compiler scaffolding at call time (see ``compiler/groq_compiler.py``).
This keeps the whole subsystem importable and testable offline.

Environment variables
---------------------
AZURE_FOUNDRY_MODEL    Deployment/model id on the Azure AI Foundry endpoint —
                    the ONLY LLM provider in this codebase (``build_llm_client()``
                    wires up nothing else). No default — must be set for the
                    LLM compile phase (and every other LLM call site — field
                    mapping, sheet identification, chat assistant, value
                    pairing, script generation) to be usable (see
                    ``llm/azure_foundry_client.py``, which fails loudly rather
                    than guessing a model name). Authentication is via Azure
                    AD (``DefaultAzureCredential`` — az login / managed
                    identity / env-based service principal), not an API key.
AZURE_FOUNDRY_BASE_URL Azure AI Foundry OpenAI-compatible base URL. Required —
                    no default; must be set at deploy time (see
                    ``llm/azure_foundry_client.py``, which fails loudly rather
                    than guessing an endpoint).
LLM_FALLBACK_COOLDOWN_SECONDS
                    Unused by the current Azure-AI-Foundry-only ``build_llm_client()``
                    (there is nothing to fail over to); kept for
                    ``FailoverLLMClient`` callers/tests that construct their own
                    multi-provider list. Default: 60.
SHADOW_TTL_DAYS     Retention window (days) for Shadow_Source data before
                    auto-cleanup. Default: 7.
RECON_PREVIEW_ROWS  Max rows embedded in a Transformation-Preview payload
                    (source/shadow/target samples sent to the UI). The full
                    dataset is never shipped — only this sample is. Default: 100.
RECON_PREVIEW_CELL_CHARS
                    Max characters per previewed cell; longer text values are
                    truncated with an ellipsis so a few huge fields can't bloat
                    the preview payload. Default: 200.
REPLAY_SAMPLE_MIN   Minimum rows for Gate 2 sample replay. Default: 50.
REPLAY_SAMPLE_MAX   Maximum rows for Gate 2 sample replay. Default: 100.
USE_SCRIPT_TRANSFORMATIONS
                    Feature flag for the Transformation Preview + Approval
                    workflow (LLM-generated transformation *script* -> static
                    validation -> sandbox preview -> user approves the
                    transformed DATA -> production execution). When false
                    (default) the contract-based compile/validate/approve flow
                    remains the active path. Accepts true/1/yes/on.
RECON_GROQ_STRICT   When true, a configured-but-failing Azure AI Foundry compile raises
                    instead of silently degrading to the deterministic stub
                    compiler (name kept for backward compatibility — it gates
                    the LLM compiler in general, not specifically Groq).
                    Default: false (degrade, matching the script-transformation
                    generator's fallback behaviour). Turn this on in any
                    environment where a stub-compiled contract reaching Gate 1
                    should be treated as a bug, not a normal degraded path.
                    Accepts true/1/yes/on.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass(frozen=True)
class AzureFoundrySettings:
    """Azure AI Foundry LLM configuration — the ONLY LLM provider in this
    codebase, via its OpenAI-compatible endpoint. Authenticated with Azure AD
    (``DefaultAzureCredential``), not a static API key, so there is no
    ``api_key`` field here — only the deployment/model id and base URL are
    configured through the environment."""

    model: str
    base_url: str | None

    @property
    def is_configured(self) -> bool:
        return bool(self.model) and bool(self.base_url)


@dataclass(frozen=True)
class Settings:
    shadow_ttl_days: int
    preview_rows: int
    preview_cell_chars: int
    replay_sample_min: int
    replay_sample_max: int
    use_script_transformations: bool
    groq_strict: bool
    llm_fallback_cooldown_s: int
    azure_foundry: AzureFoundrySettings = field(repr=False)

    @property
    def any_llm_configured(self) -> bool:
        """True when Azure AI Foundry — the only LLM provider in this
        codebase — has a model id and base URL configured."""
        return self.azure_foundry.is_configured


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return process-wide settings, resolved once from the environment.

    Cached so every module observes the same store location. Tests that need a
    temporary store call :func:`reset_settings_cache` after setting env vars.
    """
    azure_foundry = AzureFoundrySettings(
        # No invented defaults — this tier is only usable once both
        # AZURE_FOUNDRY_MODEL and AZURE_FOUNDRY_BASE_URL are actually set (see
        # llm/azure_foundry_client.py, which fails loudly rather than
        # guessing a model name or endpoint).
        model=os.environ.get("AZURE_FOUNDRY_MODEL", ""),
        base_url=os.environ.get("AZURE_FOUNDRY_BASE_URL", "") or None,
    )

    return Settings(
        shadow_ttl_days=_int_env("SHADOW_TTL_DAYS", 7),
        preview_rows=max(1, _int_env("RECON_PREVIEW_ROWS", 100)),
        preview_cell_chars=max(0, _int_env("RECON_PREVIEW_CELL_CHARS", 200)),
        replay_sample_min=_int_env("REPLAY_SAMPLE_MIN", 50),
        replay_sample_max=_int_env("REPLAY_SAMPLE_MAX", 100),
        use_script_transformations=_bool_env("USE_SCRIPT_TRANSFORMATIONS", False),
        groq_strict=_bool_env("RECON_GROQ_STRICT", False),
        llm_fallback_cooldown_s=max(0, _int_env("LLM_FALLBACK_COOLDOWN_SECONDS", 60)),
        azure_foundry=azure_foundry,
    )


def reset_settings_cache() -> None:
    """Clear the cached settings (used by tests that mutate the environment)."""
    get_settings.cache_clear()
