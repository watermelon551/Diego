from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

# Ratchet budgets: keep these files below the current cap and reduce over time.
BUDGETS = {
    "service/run/orchestrator.py": 2800,
    "service/slides/js_quality_mixin.py": 1300,
    "service/templates/template_ops_mixin.py": 1260,
    "service/llm/client.py": 1050,
    "service/run/services/quality_repair_service.py": 450,
    "service/run/services/compile_service.py": 450,
    "service/run/services/reporting_service.py": 200,
    "tests/support/service_flow_shared.py": 300,
    "tests/support/llm_doubles.py": 260,
    "tests/support/template_builders.py": 260,
    "tests/service/test_agentic_qa.py": 700,
}


def test_file_size_budgets() -> None:
    violations: list[str] = []
    for rel_path, limit in BUDGETS.items():
        path = ROOT / rel_path
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > limit:
            violations.append(f"{rel_path}: {lines} > {limit}")
    assert not violations, "File-size budget exceeded:\n" + "\n".join(violations)
