"""Test isolation: each test gets its own temporary persistent store."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("RECON_STORE_DIR", str(tmp_path / "store"))
    # No live LLM providers in tests unless a test opts in explicitly. Clearing
    # OpenAI too keeps the failover path deterministic (Groq-only / neither).
    for var in ("GROQ_API_KEY", "GROQ_MODEL", "OPENAI_API_KEY", "OPENAI_MODEL"):
        monkeypatch.delenv(var, raising=False)

    from backend.recon_engine.config import reset_settings_cache
    from backend.recon_engine.llm import reset_breaker
    from backend.recon_engine.storage.db import init_storage

    reset_settings_cache()
    reset_breaker()  # the failover circuit breaker is process-wide; reset per test
    init_storage()
    yield
    reset_settings_cache()
    reset_breaker()
