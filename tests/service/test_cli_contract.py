from __future__ import annotations

from pathlib import Path

from service.run.orchestrator import RunOrchestrator
from service.infra.store import RunStore

from tests.support.service_flow_shared import MockLLMClient, make_settings


def test_orchestrator_should_expose_cli_runtime_methods(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )

    for name in [
        "create_run",
        "get_run_detail",
        "confirm_outline",
        "upload_template",
        "build_compile_bundle",
    ]:
        assert hasattr(orch, name), name
        assert callable(getattr(orch, name)), name
