"""Test isolation: each test gets its own temporary persistent store."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("RECON_STORE_DIR", str(tmp_path / "store"))
    # No live LLM calls in tests unless a test opts in explicitly. Clearing
    # AZURE_FOUNDRY_MODEL keeps build_llm_client() deterministic
    # (configured-or-unconfigured, never a live call).
    for var in ("AZURE_FOUNDRY_MODEL", "AZURE_FOUNDRY_BASE_URL"):
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
