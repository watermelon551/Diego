from __future__ import annotations

from tests.service.architecture_guard_support import ROOT


def test_js_quality_rule_modules_should_remain_explicit() -> None:
    slides_dir = ROOT / "service" / "slides"
    quality_dir = slides_dir / "js_quality"
    required_quality_files = {
        "__init__.py",
        "asset_contract.py",
        "call_parsing.py",
        "canonicalization.py",
        "contract_validation.py",
        "failure_artifacts.py",
        "failure_diagnostics.py",
        "guardrails.py",
        "issue_resolution.py",
        "layout_analysis.py",
        "mixin.py",
        "normalization.py",
        "parsing_runtime.py",
    }
    existing_quality_files = {path.name for path in quality_dir.glob("*.py")}
    missing_quality = sorted(required_quality_files - existing_quality_files)
    assert not missing_quality, (
        "service/slides/js_quality missing expected package modules: "
        f"{missing_quality}"
    )

    facade_text = (slides_dir / "js_quality_mixin.py").read_text(encoding="utf-8")
    assert "from .js_quality.mixin import SlideJsQualityMixin" in facade_text

    runtime_dir = quality_dir / "runtime"
    required_runtime_files = {
        "__init__.py",
        "normalization_runtime_mixin.py",
        "diagnostics_runtime_mixin.py",
        "validation_runtime_mixin.py",
    }
    existing_runtime_files = {path.name for path in runtime_dir.glob("*.py")}
    missing_runtime = sorted(required_runtime_files - existing_runtime_files)
    assert not missing_runtime, (
        "service/slides/js_quality/runtime missing expected package modules: "
        f"{missing_runtime}"
    )

    quality_facade_text = (quality_dir / "mixin.py").read_text(encoding="utf-8")
    assert "from .runtime import SlideJsQualityMixin" in quality_facade_text


def test_design_resolution_boundary_should_remain_explicit() -> None:
    design_resolution_path = ROOT / "service" / "design" / "design_resolution.py"
    style_selection_path = ROOT / "service" / "design" / "style_selection.py"
    design_report_path = ROOT / "service" / "design" / "design_report_resolution.py"
    skill_profile_dir = ROOT / "service" / "design" / "skill_profile"
    orchestrator_path = ROOT / "service" / "run" / "orchestrator.py"
    design_mixin_path = ROOT / "service" / "run" / "design_resolution_mixin.py"
    design_text = design_resolution_path.read_text(encoding="utf-8")
    style_selection_text = style_selection_path.read_text(encoding="utf-8")
    design_report_text = design_report_path.read_text(encoding="utf-8")
    orchestrator_text = orchestrator_path.read_text(encoding="utf-8")
    design_mixin_text = design_mixin_path.read_text(encoding="utf-8")

    assert "from .style_selection import (" in design_text
    assert "from .design_report_resolution import (" in design_text
    for marker in [
        "def selected_style_preset",
        "def selected_style_dna",
        "def resolved_style_dna_id",
        "def requested_template_style",
    ]:
        assert marker in style_selection_text
    for marker in [
        "def apply_style_preset_to_requirements",
        "def compose_requirements_report",
        "def normalize_hex6",
        "def resolve_design_profile",
    ]:
        assert marker in design_report_text

    forbidden_orchestrator_defs = [
        "def _selected_style_preset",
        "def _selected_style_dna",
        "def _resolved_style_dna_id",
        "def _requested_template_style",
        "def _apply_style_preset_to_requirements",
        "def _compose_requirements_report",
        "def _normalize_hex6",
        "def _resolve_design_profile",
    ]
    for marker in forbidden_orchestrator_defs:
        assert marker in orchestrator_text or marker in design_mixin_text, (
            "thin compatibility wrappers may remain in orchestrator or explicit run-owned mixins, "
            f"but {marker} should delegate into service/design/design_resolution.py"
        )

    required_skill_profile_files = {
        "__init__.py",
        "contracts.py",
        "catalog.py",
        "layout_rules.py",
    }
    existing_skill_profile_files = {
        path.name for path in skill_profile_dir.glob("*.py")
    }
    missing_skill_profile = sorted(
        required_skill_profile_files - existing_skill_profile_files
    )
    assert not missing_skill_profile, (
        "service/design/skill_profile missing expected package modules: "
        f"{missing_skill_profile}"
    )

    skill_profile_init_text = (skill_profile_dir / "__init__.py").read_text(
        encoding="utf-8"
    )
    for marker in [
        "from .catalog import",
        "from .contracts import",
        "from .layout_rules import",
        "__all__",
    ]:
        assert marker in skill_profile_init_text, (
            "service/design/skill_profile/__init__.py missing " + marker
        )
