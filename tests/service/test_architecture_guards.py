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
                r"from\s+\.\.(templates|slides|design)\b",
                r"from\s+service\.(templates|slides|design)\b",
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


def test_runtime_kernel_and_engines_should_keep_explicit_boundaries() -> None:
    checks: list[tuple[Path, list[str]]] = [
        (
            ROOT / "service" / "run" / "kernel.py",
            [
                r"from\s+\.\.(app|orchestrator|llm_client|store)\b",
                r"from\s+service\.(app|orchestrator|llm_client|store)\b",
            ],
        ),
        (
            ROOT / "service" / "run" / "engines" / "template_engine.py",
            [
                r"from\s+.+scratch_engine\b",
            ],
        ),
        (
            ROOT / "service" / "run" / "engines" / "scratch_engine.py",
            [
                r"from\s+.+template_engine\b",
            ],
        ),
        (
            ROOT / "service" / "run" / "engines" / "quality_engine.py",
            [
                r"RunStatus",
                r"setattr\(.*status",
                r"status\s*=",
            ],
        ),
    ]
    violations: list[str] = []
    for path, patterns in checks:
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            if re.search(pattern, text):
                rel = path.relative_to(ROOT).as_posix()
                violations.append(f"{rel} matches forbidden pattern: {pattern}")
    assert not violations, "Runtime boundary violations found:\n" + "\n".join(violations)


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


def test_core_files_should_respect_size_guards() -> None:
    exempt_over_500 = {
        "service/run/orchestrator.py": "transition facade while legacy helper methods are still migrating",
        "service/slides/js_quality_mixin.py": "legacy quality logic migration in progress",
        "service/templates/template_ops_mixin.py": "legacy template logic migration in progress",
        "service/run/slide_scene.py": "editable slide scene parsing and transform migration is still consolidated here",
        "service/design/style_catalog.py": "catalog data and normalization rules intentionally centralized",
        "service/llm/client.py": "provider client and parsing compatibility surface intentionally centralized",
    }
    exempt_over_300 = {
        "service/run/flows/outline_flow.py",
        "service/run/services/compile_service.py",
        "service/run/services/quality_repair_service.py",
        "service/run/slide_preview.py",
        "service/run/flows/scratch_flow.py",
        "service/templates/asset_search_mixin.py",
        "service/design/skill_profile.py",
        "service/models/contracts.py",
        "service/llm/mock.py",
        "service/llm/types.py",
        "service/config.py",
        "service/infra/store.py",
        "service/application/slides.py",
    }
    violations: list[str] = []
    for path in _iter_py_files(ROOT / "service"):
        rel = path.relative_to(ROOT).as_posix()
        lines = path.read_text(encoding="utf-8").count("\n") + 1
        if lines > 500 and rel not in exempt_over_500:
            violations.append(f"{rel} is {lines} lines and has no >500 exemption")
        elif lines > 300 and rel not in exempt_over_500 and rel not in exempt_over_300:
            violations.append(f"{rel} is {lines} lines and has no >300 exemption")
    assert not violations, "Core file size guard violations found:\n" + "\n".join(violations)


def test_docs_should_describe_generation_and_external_compile_boundary() -> None:
    checks = {
        ROOT / "README.md": [
            "Diego 负责生成",
            "外部 compile provider 负责渲染/编译/导出",
            "Pagevra` 是当前支持的 provider 之一",
        ],
        ROOT / "docs" / "PROJECT_GOALS.md": [
            "compile bundle",
            "不依赖特定上游系统实现细节",
        ],
        ROOT / "docs" / "ARCHITECTURE.md": [
            "generation truth",
            "external compile provider",
        ],
    }
    missing: list[str] = []
    for path, patterns in checks.items():
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            if pattern not in text:
                missing.append(f"{path.relative_to(ROOT).as_posix()} missing {pattern!r}")
    assert not missing, "Docs boundary contract drift found:\n" + "\n".join(missing)


def test_compile_provider_default_should_not_point_to_external_service() -> None:
    text = (ROOT / "service" / "config.py").read_text(encoding="utf-8")
    assert 'compile_provider: str = "none"' in text
    assert 'os.getenv("COMPILE_PROVIDER", "none")' in text
    assert 'pagevra_preview_enabled: bool = False' in text
    assert 'pagevra_preview_enabled=_env_bool("PAGEVRA_PREVIEW_ENABLED", False)' in text
