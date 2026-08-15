"""Environment-driven configuration for the reconciliation engine.

Nothing here has a hard dependency on Groq or any network service — the Groq
settings are only *read*; whether they are required is decided by the compiler
scaffolding at call time (see ``compiler/groq_compiler.py``). This keeps the
whole subsystem importable and testable offline.

Environment variables
---------------------
GROQ_API_KEY        API key for the Groq LLM (the PRIMARY provider, tier 1).
                    Required ONLY when a real ``GroqContractCompiler`` is used to
                    draft a contract. Not needed for validation, approval, or
                    reconciliation.
GROQ_MODEL          Groq model id used for contract drafting.
                    Default: ``llama-3.3-70b-versatile``.
GROQ_BASE_URL       Optional override for the Groq API base URL.
GEMINI_API_KEY      API key for Gemini (fallback tier 2), called via Gemini's
                    OpenAI-compatible endpoint. Optional.
GEMINI_MODEL        Gemini model id used for tier 2. No default — must be set
                    for this tier to be usable.
GEMINI_BASE_URL     Optional override for the Gemini OpenAI-compatible base URL
                    (default: ``https://generativelanguage.googleapis.com/v1beta/openai/``).
CEREBRAS_API_KEY    API key for Cerebras (fallback tier 3), called via
                    Cerebras's OpenAI-compatible endpoint. Optional.
CEREBRAS_MODEL      Cerebras model id used for tier 3. No default — must be set
                    for this tier to be usable.
CEREBRAS_BASE_URL   Optional override for the Cerebras OpenAI-compatible base
                    URL (default: ``https://api.cerebras.ai/v1``).
OPENROUTER_API_KEY  API key for OpenRouter (fallback tier 4 — the last resort,
                    free models). Optional.
OPENROUTER_MODEL    OpenRouter model id used for tier 4.
                    Default: ``meta-llama/llama-3.1-8b-instruct:free``.
OPENROUTER_BASE_URL Optional override for the OpenRouter base URL
                    (default: ``https://openrouter.ai/api/v1``).
LLM_FALLBACK_COOLDOWN_SECONDS
                    After a Groq retryable failure, how long (seconds) to route
                    straight to the next tier before retrying Groq again.
                    Default: 60.
OPENAI_API_KEY      API key for OpenAI. No longer part of the default
                    Groq→Gemini→Cerebras→OpenRouter failover chain built by
                    ``build_llm_client()`` — kept only for standalone/manual use
                    of ``OpenAIJSONClient``. Optional.
OPENAI_MODEL        OpenAI model id for standalone use. Default: ``gpt-4o-mini``.
OPENAI_BASE_URL     Optional override for the OpenAI API base URL.
RECON_STORE_DIR     Directory root for all persisted state (SQLite DBs + raw
                    snapshot / shadow data files). Default: ``<repo>/data/recon_store``.
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
RECON_GROQ_STRICT   When true, a configured-but-failing Groq compile raises
                    instead of silently degrading to the deterministic stub
                    compiler. Default: false (degrade, matching the
                    script-transformation generator's fallback behaviour).
                    Turn this on in any environment where a stub-compiled
                    contract reaching Gate 1 should be treated as a bug, not a
                    normal degraded path. Accepts true/1/yes/on.
VALUE_PAIRING_WINDOW_YEARS
                    Size (in years) of each year-range batch the value-pairing
                    pipeline partitions the SOURCE side into (see
                    ``value_pairing.batching``) — e.g. 2 -> "2021-2022",
                    "2023-2024", ... Default: 2. A caller can still override
                    this per-call via ``pair_values(date_window_years=...)``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


def _repo_root() -> Path:
    # backend/recon_engine/config.py -> repo root is three levels up.
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class GroqSettings:
    """Groq LLM configuration. Read-only scaffolding for the compile phase.

    ``api_key`` is intentionally allowed to be ``None`` so the app runs without
    Groq configured. The contract compiler decides whether a key is required.
    """

    api_key: str | None
    model: str
    base_url: str | None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True)
class OpenAISettings:
    """OpenAI LLM configuration — kept for standalone use only.

    No longer part of the default ``build_llm_client()`` failover chain (see
    :mod:`backend.recon_engine.llm.failover`); ``OpenAIJSONClient`` still reads
    this if constructed directly.
    """

    api_key: str | None
    model: str
    base_url: str | None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True)
class GeminiSettings:
    """Gemini LLM configuration — fallback tier 2, via Gemini's OpenAI-compatible endpoint."""

    api_key: str | None
    model: str
    base_url: str | None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True)
class CerebrasSettings:
    """Cerebras LLM configuration — fallback tier 3, via Cerebras's OpenAI-compatible endpoint."""

    api_key: str | None
    model: str
    base_url: str | None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True)
class OpenRouterSettings:
    """OpenRouter LLM configuration — fallback tier 4, the last resort (free models)."""

    api_key: str | None
    model: str
    base_url: str | None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True)
class Settings:
    store_dir: Path
    shadow_ttl_days: int
    preview_rows: int
    preview_cell_chars: int
    replay_sample_min: int
    replay_sample_max: int
    use_script_transformations: bool
    groq_strict: bool
    llm_fallback_cooldown_s: int
    value_pairing_window_years: int
    groq: GroqSettings = field(repr=False)
    gemini: GeminiSettings = field(repr=False)
    cerebras: CerebrasSettings = field(repr=False)
    openrouter: OpenRouterSettings = field(repr=False)
    openai: OpenAISettings = field(repr=False)

    @property
    def any_llm_configured(self) -> bool:
        """True when at least one provider in the active failover chain
        (Groq → Gemini → Cerebras → OpenRouter) has a key. ``openai`` is
        deliberately excluded — it is no longer part of that chain."""
        return (
            self.groq.is_configured
            or self.gemini.is_configured
            or self.cerebras.is_configured
            or self.openrouter.is_configured
        )

    # ── Derived paths ────────────────────────────────────────────────────────
    @property
    def main_db_path(self) -> Path:
        """Primary metadata store: raw snapshots, contracts, runs, results, audit."""
        return self.store_dir / "recon.db"

    @property
    def shadow_db_path(self) -> Path:
        """Separate DB file emulating the ``recon_shadow`` schema boundary."""
        return self.store_dir / "recon_shadow.db"

    @property
    def raw_data_dir(self) -> Path:
        """On-disk immutable raw snapshot payloads (append-only)."""
        return self.store_dir / "raw"

    @property
    def shadow_data_dir(self) -> Path:
        """On-disk shadow-source payloads (disposable, TTL-governed)."""
        return self.store_dir / "shadow"

    @property
    def results_data_dir(self) -> Path:
        """On-disk reconciliation result detail payloads."""
        return self.store_dir / "results"

    @property
    def previews_data_dir(self) -> Path:
        """On-disk transformed-preview payloads (script-flow snapshots)."""
        return self.store_dir / "previews"

    def ensure_dirs(self) -> None:
        for p in (
            self.store_dir,
            self.raw_data_dir,
            self.shadow_data_dir,
            self.results_data_dir,
            self.previews_data_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)


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
    store_dir_env = os.environ.get("RECON_STORE_DIR", "").strip()
    store_dir = Path(store_dir_env) if store_dir_env else (_repo_root() / "data" / "recon_store")

    groq = GroqSettings(
        api_key=os.environ.get("GROQ_API_KEY") or None,
        model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        base_url=os.environ.get("GROQ_BASE_URL") or None,
    )
    gemini = GeminiSettings(
        api_key=os.environ.get("GEMINI_API_KEY") or None,
        # No invented default — this tier is only usable once GEMINI_MODEL is
        # actually set (see llm/gemini_client.py, which fails loudly rather
        # than guessing a model name).
        model=os.environ.get("GEMINI_MODEL", ""),
        base_url=os.environ.get("GEMINI_BASE_URL")
        or "https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    cerebras = CerebrasSettings(
        api_key=os.environ.get("CEREBRAS_API_KEY") or None,
        model=os.environ.get("CEREBRAS_MODEL", ""),
        base_url=os.environ.get("CEREBRAS_BASE_URL") or "https://api.cerebras.ai/v1",
    )
    openrouter = OpenRouterSettings(
        api_key=os.environ.get("OPENROUTER_API_KEY") or None,
        model=os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free"),
        base_url=os.environ.get("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1",
    )
    openai = OpenAISettings(
        api_key=os.environ.get("OPENAI_API_KEY") or None,
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
    )

    return Settings(
        store_dir=store_dir,
        shadow_ttl_days=_int_env("SHADOW_TTL_DAYS", 7),
        preview_rows=max(1, _int_env("RECON_PREVIEW_ROWS", 100)),
        preview_cell_chars=max(0, _int_env("RECON_PREVIEW_CELL_CHARS", 200)),
        replay_sample_min=_int_env("REPLAY_SAMPLE_MIN", 50),
        replay_sample_max=_int_env("REPLAY_SAMPLE_MAX", 100),
        use_script_transformations=_bool_env("USE_SCRIPT_TRANSFORMATIONS", False),
        groq_strict=_bool_env("RECON_GROQ_STRICT", False),
        llm_fallback_cooldown_s=max(0, _int_env("LLM_FALLBACK_COOLDOWN_SECONDS", 60)),
        value_pairing_window_years=max(1, _int_env("VALUE_PAIRING_WINDOW_YEARS", 1)),
        groq=groq,
        gemini=gemini,
        cerebras=cerebras,
        openrouter=openrouter,
        openai=openai,
    )


def reset_settings_cache() -> None:
    """Clear the cached settings (used by tests that mutate the environment)."""
    get_settings.cache_clear()
