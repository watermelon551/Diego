from __future__ import annotations

from tests.service.architecture_guard_support import ROOT


def test_docs_should_describe_generation_and_external_compile_boundary() -> None:
    checks = {
        ROOT / "README.md": [
            "Diego 负责生成",
            "外部 compile provider 负责渲染/编译/导出",
            "Pagevra` 是当前支持的 provider 之一",
            "host-agnostic 的 long-form drafting primitive",
        ],
        ROOT / "docs" / "PROJECT_GOALS.md": [
            "compile bundle",
            "不依赖特定上游系统实现细节",
            "source-aware long-form drafting",
        ],
        ROOT / "docs" / "ARCHITECTURE.md": [
            "generation truth",
            "external compile provider",
            "drafting truth",
        ],
    }
    missing: list[str] = []
    for path, patterns in checks.items():
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            if pattern not in text:
                missing.append(f"{path.relative_to(ROOT).as_posix()} missing {pattern!r}")
    assert not missing, "Docs boundary contract drift found:\n" + "\n".join(missing)


def test_orchestrator_hotspot_note_should_keep_transition_direction_explicit() -> None:
    path = ROOT / "docs" / "RUN_ORCHESTRATOR_HOTSPOT_NOTE.md"
    text = path.read_text(encoding="utf-8").lower()
    required = [
        "transitional hotspot",
        "transition facade",
        "lifecycle orchestration",
        "flow delegation",
        "failure convergence",
        "run/flows",
        "run/services",
        "run/engines",
        "run/factory.py",
        "runtime_support.py",
        "compatibility aliases",
        "forbidden growth pattern",
        "shell/workbench semantics",
    ]
    for marker in required:
        assert marker in text, f"RUN_ORCHESTRATOR_HOTSPOT_NOTE.md missing {marker!r}"


def test_capability_note_should_keep_generic_structure_language() -> None:
    path = ROOT / "docs" / "CAPABILITY_NOTES.md"
    text = path.read_text(encoding="utf-8").lower()
    assert "source-conditioned structure expansion" in text
    assert "do not add public api" in text
    forbidden = [
        "knowledge_mindmap",
        "studio-card",
        "graph editor",
        "node anchor",
        "neo",
        "spectra",
    ]
    for term in forbidden:
        assert term not in text


def test_compile_provider_default_should_not_point_to_external_service() -> None:
    text = (ROOT / "service" / "config.py").read_text(encoding="utf-8")
    assert 'compile_provider: str = "none"' in text
    assert 'os.getenv("COMPILE_PROVIDER", "none")' in text
    assert 'pagevra_preview_enabled: bool = False' in text
    assert 'pagevra_preview_enabled=_env_bool("PAGEVRA_PREVIEW_ENABLED", False)' in text
