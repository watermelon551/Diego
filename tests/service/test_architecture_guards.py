from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _iter_py_files(base: Path):
    for path in base.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def test_legacy_shims_should_use_explicit_exports() -> None:
    shim_files = [
        ROOT / "service" / "app.py",
        ROOT / "service" / "orchestrator.py",
        ROOT / "service" / "llm_client.py",
        ROOT / "service" / "store.py",
        ROOT / "service" / "skill_profile.py",
        ROOT / "service" / "style_catalog.py",
    ]
    for path in shim_files:
        text = path.read_text(encoding="utf-8")
        assert "import *" not in text, f"{path} should not use wildcard exports"


def test_layer_boundaries_should_not_have_forbidden_imports() -> None:
    checks: list[tuple[Path, list[str]]] = [
        (
            ROOT / "service" / "api",
            [
                r"from\s+\.\.(templates|slides)\b",
                r"from\s+service\.(templates|slides)\b",
            ],
        ),
        (
            ROOT / "service" / "design",
            [
                r"from\s+\.\.(run|api|templates|slides)\b",
                r"from\s+service\.(run|api|templates|slides)\b",
            ],
        ),
        (
            ROOT / "service" / "models",
            [
                r"from\s+\.\.(run|api|templates|slides)\b",
                r"from\s+service\.(run|api|templates|slides)\b",
            ],
        ),
        (
            ROOT / "service" / "infra",
            [
                r"from\s+\.\.(api|run|slides|templates)\b",
                r"from\s+service\.(api|run|slides|templates)\b",
            ],
        ),
    ]
    violations: list[str] = []
    for base, patterns in checks:
        for path in _iter_py_files(base):
            text = path.read_text(encoding="utf-8")
            for pattern in patterns:
                if re.search(pattern, text):
                    rel = path.relative_to(ROOT).as_posix()
                    violations.append(f"{rel} matches forbidden pattern: {pattern}")
    assert not violations, "Forbidden imports found:\n" + "\n".join(violations)


def test_internal_service_modules_should_not_import_legacy_shims() -> None:
    service_root = ROOT / "service"
    shim_roots = {
        service_root / "app.py",
        service_root / "orchestrator.py",
        service_root / "llm_client.py",
        service_root / "store.py",
        service_root / "skill_profile.py",
        service_root / "style_catalog.py",
        service_root / "_compat.py",
        service_root / "__init__.py",
    }
    patterns = [
        r"from\s+\.{2,}(app|orchestrator|llm_client|store|skill_profile|style_catalog)\s+import\b",
        r"from\s+service\.(app|orchestrator|llm_client|store|skill_profile|style_catalog)\s+import\b",
        r"import\s+service\.(app|orchestrator|llm_client|store|skill_profile|style_catalog)\b",
    ]
    violations: list[str] = []
    for path in _iter_py_files(service_root):
        if path in shim_roots:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            if re.search(pattern, text):
                rel = path.relative_to(ROOT).as_posix()
                violations.append(f"{rel} matches forbidden pattern: {pattern}")
    assert not violations, "Legacy shim imports found in internal modules:\n" + "\n".join(violations)
