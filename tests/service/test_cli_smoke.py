from __future__ import annotations

from pathlib import Path

from service.run import build_orchestrator


def test_build_orchestrator_should_expose_run_cli_facade(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.test")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("DIEGO_RUN_STORE", "memory")
    monkeypatch.setenv("COMPILE_PROVIDER", "none")
    monkeypatch.setenv("ASSET_PROVIDER", "mock")

    orchestrator = build_orchestrator(tmp_path)

    for name in (
        "create_run",
        "get_run_detail",
        "confirm_outline",
        "upload_template",
        "build_compile_bundle",
    ):
        assert hasattr(orchestrator, name), f"missing facade method: {name}"
