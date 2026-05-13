from __future__ import annotations

import pytest

from service.config import load_settings


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.test")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("COMPILE_PROVIDER", "none")
    monkeypatch.setenv("ASSET_PROVIDER", "mock")


def test_load_settings_should_allow_memory_run_store_without_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("DIEGO_RUN_STORE", "memory")
    monkeypatch.delenv("DIEGO_DATABASE_URL", raising=False)

    settings = load_settings()

    assert settings.run_store == "memory"
    assert settings.database_url == ""


def test_load_settings_should_require_database_url_only_for_postgres_run_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("DIEGO_RUN_STORE", "postgres")
    monkeypatch.delenv("DIEGO_DATABASE_URL", raising=False)

    with pytest.raises(
        ValueError,
        match="DIEGO_DATABASE_URL is required when DIEGO_RUN_STORE=postgres",
    ):
        load_settings()
