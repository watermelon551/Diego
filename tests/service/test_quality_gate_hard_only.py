from __future__ import annotations

from pathlib import Path

from service.llm import MockLLMClient
from service.run.orchestrator import RunOrchestrator
from service.infra.store import RunStore
from tests.support.runtime_helpers import make_settings


def _make_orchestrator(tmp_path: Path) -> RunOrchestrator:
    return RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )


def test_quality_gate_should_treat_page_badge_as_high_risk_not_blocking(tmp_path: Path) -> None:
    orch = _make_orchestrator(tmp_path)
    classified = orch._classify_slide_issues(
        [
            "missing required page badge position",
            "title font too small (32 < 36)",
        ]
    )
    assert not classified["blocking"]
    assert any("missing required page badge position" in item for item in classified["high_risk"])
    assert any("title font too small" in item for item in classified["high_risk"])


def test_quality_gate_should_keep_geometry_overflow_as_blocking(tmp_path: Path) -> None:
    orch = _make_orchestrator(tmp_path)
    classified = orch._classify_slide_issues(
        [
            "box-1 out of slide bounds",
            "box-1 overlaps box-2 (ratio=0.20)",
        ]
    )
    assert len(classified["blocking"]) == 2
