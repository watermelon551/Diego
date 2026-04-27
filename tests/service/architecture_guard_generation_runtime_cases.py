from __future__ import annotations

from tests.service.architecture_guard_support import ROOT


def test_run_factory_boundary_should_remain_explicit() -> None:
    factory_path = ROOT / "service" / "run" / "factory.py"
    orchestrator_path = ROOT / "service" / "run" / "orchestrator.py"
    factory_text = factory_path.read_text(encoding="utf-8")
    orchestrator_text = orchestrator_path.read_text(encoding="utf-8")

    assert "def build_orchestrator" in factory_text
    assert "OpenAICompatibleLLMClient" in factory_text
    assert "PostgresRunStore" in factory_text
    assert "RunStore" in factory_text
    assert "def build_orchestrator" not in orchestrator_text


def test_orchestrator_bootstrap_package_should_remain_explicit() -> None:
    run_dir = ROOT / "service" / "run"
    facade_path = run_dir / "orchestrator_bootstrap_mixin.py"
    package_dir = run_dir / "orchestrator_bootstrap"

    facade_text = facade_path.read_text(encoding="utf-8")
    facade_lines = facade_text.count("\n") + 1
    assert facade_lines <= 80, (
        "service/run/orchestrator_bootstrap_mixin.py should remain a thin facade"
    )
    for marker in [
        "RunRuntimeConfigMixin",
        "RunRuntimeGatesMixin",
        "RunRuntimeStateMixin",
        "RunRuntimeServicesMixin",
        "def _initialize_runtime(",
    ]:
        assert marker in facade_text

    required_package_files = {
        "__init__.py",
        "runtime_config_mixin.py",
        "runtime_gates_mixin.py",
        "runtime_state_mixin.py",
        "runtime_services_mixin.py",
        "js_contract.py",
    }
    existing_package_files = {path.name for path in package_dir.glob("*.py")}
    missing = sorted(required_package_files - existing_package_files)
    assert not missing, (
        "service/run/orchestrator_bootstrap missing expected package modules: "
        f"{missing}"
    )

    js_contract_text = (package_dir / "js_contract.py").read_text(encoding="utf-8")
    assert "def load_js_api_contract" in js_contract_text


def test_orchestrator_api_package_should_remain_explicit() -> None:
    run_dir = ROOT / "service" / "run"
    facade_path = run_dir / "orchestrator_api_mixin.py"
    package_dir = run_dir / "orchestrator_api"

    facade_text = facade_path.read_text(encoding="utf-8")
    facade_lines = facade_text.count("\n") + 1
    assert facade_lines <= 50, (
        "service/run/orchestrator_api_mixin.py should remain a thin facade"
    )
    for marker in [
        "RunApplicationApiMixin",
        "RunSlideSceneApiMixin",
        "RunFlowApiMixin",
        "RunQualityTemplateApiMixin",
    ]:
        assert marker in facade_text

    required_package_files = {
        "__init__.py",
        "application_mixin.py",
        "slide_scene_mixin.py",
        "flow_mixin.py",
        "quality_template_mixin.py",
    }
    existing_package_files = {path.name for path in package_dir.glob("*.py")}
    missing = sorted(required_package_files - existing_package_files)
    assert not missing, (
        "service/run/orchestrator_api missing expected package modules: "
        f"{missing}"
    )


def test_slide_generation_execution_modules_should_remain_explicit() -> None:
    run_dir = ROOT / "service" / "run"
    required_files = {
        "agentic_slide_generation.py",
        "agentic_slide_candidate_rounds.py",
        "agentic_slide_finalization.py",
        "legacy_slide_generation.py",
    }
    existing_files = {path.name for path in run_dir.glob("*slide_generation*.py")} | {
        path.name for path in run_dir.glob("agentic_slide_finalization.py")
    } | {
        path.name for path in run_dir.glob("agentic_slide_candidate_rounds.py")
    }
    missing = sorted(required_files - existing_files)
    assert not missing, f"service/run missing expected slide generation modules: {missing}"

    facade_text = (run_dir / "agentic_slide_candidate_rounds.py").read_text(
        encoding="utf-8"
    )
    facade_lines = facade_text.count("\n") + 1
    assert facade_lines <= 20, (
        "service/run/agentic_slide_candidate_rounds.py should remain a thin facade"
    )
    assert (
        "from .agentic_slide_candidate_rounds.runtime import run_agentic_candidate_rounds"
        in facade_text
    )

    package_dir = run_dir / "agentic_slide_candidate_rounds"
    required_package_files = {
        "__init__.py",
        "runtime.py",
        "build_failure.py",
        "review_cycle.py",
        "rounds_exhausted.py",
    }
    existing_package_files = {path.name for path in package_dir.glob("*.py")}
    missing_package = sorted(required_package_files - existing_package_files)
    assert not missing_package, (
        "service/run/agentic_slide_candidate_rounds missing expected package modules: "
        f"{missing_package}"
    )


def test_slide_plan_and_repair_rules_should_not_drift_back_into_orchestrator() -> None:
    orchestrator_text = (ROOT / "service" / "run" / "orchestrator.py").read_text(
        encoding="utf-8"
    )
    slide_generation_mixin_text = (
        ROOT / "service" / "run" / "slide_generation_primitives_mixin.py"
    ).read_text(encoding="utf-8")
    slide_plan_text = (ROOT / "service" / "run" / "slide_plan_rules.py").read_text(
        encoding="utf-8"
    )
    slide_briefs_text = (
        ROOT / "service" / "run" / "slide_generation_briefs.py"
    ).read_text(encoding="utf-8")
    candidate_reporting_text = (
        ROOT / "service" / "run" / "slide_candidate_reporting.py"
    ).read_text(encoding="utf-8")
    candidate_decisions_text = (
        ROOT / "service" / "run" / "slide_candidate_decisions.py"
    ).read_text(encoding="utf-8")
    candidate_state_text = (
        ROOT / "service" / "run" / "slide_candidate_state.py"
    ).read_text(encoding="utf-8")
    candidate_execution_text = (
        ROOT / "service" / "run" / "slide_candidate_execution.py"
    ).read_text(encoding="utf-8")
    candidate_review_text = (
        ROOT / "service" / "run" / "slide_candidate_review.py"
    ).read_text(encoding="utf-8")
    candidate_finalize_text = (
        ROOT / "service" / "run" / "slide_candidate_finalize.py"
    ).read_text(encoding="utf-8")
    qa_reporting_text = (
        ROOT / "service" / "run" / "qa_reporting.py"
    ).read_text(encoding="utf-8")
    qa_reporting_impl_text = (
        ROOT / "service" / "run" / "preview_quality" / "reporting.py"
    ).read_text(encoding="utf-8")
    qa_static_checks_text = (
        ROOT / "service" / "run" / "qa_static_checks.py"
    ).read_text(encoding="utf-8")
    qa_static_checks_impl_text = (
        ROOT / "service" / "run" / "preview_quality" / "static_checks.py"
    ).read_text(encoding="utf-8")
    qa_preview_sampling_text = (
        ROOT / "service" / "run" / "qa_preview_sampling.py"
    ).read_text(encoding="utf-8")
    qa_preview_sampling_impl_text = (
        ROOT / "service" / "run" / "preview_quality" / "sampling.py"
    ).read_text(encoding="utf-8")
    qa_mode_execution_text = (
        ROOT / "service" / "run" / "qa_mode_execution.py"
    ).read_text(encoding="utf-8")
    qa_mode_execution_impl_text = (
        ROOT / "service" / "run" / "preview_quality" / "mode_execution.py"
    ).read_text(encoding="utf-8")
    repair_round_reporting_text = (
        ROOT / "service" / "run" / "repair_round_reporting.py"
    ).read_text(encoding="utf-8")
    repair_mode_execution_text = (
        ROOT / "service" / "run" / "repair_mode_execution.py"
    ).read_text(encoding="utf-8")
    slide_regeneration_text = (
        ROOT / "service" / "run" / "services" / "slide_regeneration_service.py"
    ).read_text(encoding="utf-8")
    scene_recompile_text = (
        ROOT / "service" / "run" / "scene_recompile.py"
    ).read_text(encoding="utf-8")
    slide_regeneration_reporting_text = (
        ROOT / "service" / "run" / "slide_regeneration_reporting.py"
    ).read_text(encoding="utf-8")
    template_slide_regeneration_text = (
        ROOT / "service" / "run" / "template_slide_regeneration.py"
    ).read_text(encoding="utf-8")
    outline_reporting_text = (
        ROOT / "service" / "run" / "outline_reporting.py"
    ).read_text(encoding="utf-8")
    template_apply_reporting_text = (
        ROOT / "service" / "run" / "template_apply_reporting.py"
    ).read_text(encoding="utf-8")
    slide_repair_text = (
        ROOT / "service" / "run" / "slide_spec_repair.py"
    ).read_text(encoding="utf-8")

    for marker in [
        "def build_slide_plan",
        "def layout_supports_image",
        "def apply_visual_policy_to_slide_plan",
        "def extract_slide_plan_assets",
    ]:
        assert marker in slide_plan_text
    for marker in [
        "def build_slide_brief",
        "def candidate_variant_specs",
        "def fallback_research_brief",
        "def slide_spec_from_generated",
        "def generated_from_slide_spec",
    ]:
        assert marker in slide_briefs_text
    for marker in [
        "def apply_local_spec_repairs",
        "def rotate_layout_hint",
        "def trim_spec_bullets",
    ]:
        assert marker in slide_repair_text
    for marker in [
        "def build_failure_diagnostics_payload",
        "def build_candidate_generated_payload",
        "def build_candidate_selection_entry",
        "def build_quality_gate_entry",
        "def build_quality_entry",
    ]:
        assert marker in candidate_reporting_text
    for marker in [
        "def resolve_round_limits",
        "def should_accept_degraded_after_build_failure",
        "def should_accept_candidate_result",
        "def should_raise_visual_policy_unsatisfied",
        "def should_raise_rounds_exhausted",
    ]:
        assert marker in candidate_decisions_text
    for marker in [
        "class AgenticSlideCandidateState",
        "def build_candidate_variant",
        "def build_candidate_plan",
        "def record_build_failure",
        "def record_candidate_review",
        "def final_slide_status",
    ]:
        assert marker in candidate_state_text
    for marker in [
        "class CandidateExecutionResult",
        "def execute_agentic_candidate_build",
    ]:
        assert marker in candidate_execution_text
    for marker in [
        "class CandidateQualityReviewResult",
        "def review_agentic_candidate_quality",
    ]:
        assert marker in candidate_review_text
    for marker in [
        "def publish_candidate_repair_cycle",
        "def build_rounds_exhausted_details",
        "def resolve_final_citations",
        "def build_chart_truth_entry",
        "def build_codegen_completed_payload",
    ]:
        assert marker in candidate_finalize_text
    for marker in [
        "def resolve_qa_history",
        "def build_preview_cache_entry",
        "def merge_sampled_preview_cache_entry",
        "def build_qa_report",
    ]:
        assert marker in qa_reporting_impl_text
    for marker in [
        "class ScratchSlideStaticEvaluation",
        "def evaluate_scratch_slide_static",
    ]:
        assert marker in qa_static_checks_impl_text
    for marker in [
        "class PreviewCandidateRef",
        "class PreviewDecision",
        "def decide_preview_check",
        "def should_sample_unchanged_preview",
    ]:
        assert marker in qa_preview_sampling_impl_text
    for marker in [
        "class QaExecutionResult",
        "def run_scratch_qa",
        "def run_template_qa",
    ]:
        assert marker in qa_mode_execution_impl_text
    for marker in [
        "class RepairModeExecutionResult",
        "def execute_repair_round_mode",
    ]:
        assert marker in repair_mode_execution_text
    for marker in [
        "class SlideRegenerationService",
        "def recompile_run_after_scene_save",
        "def regenerate_single_slide_task",
        "def publish_slide_generated_preview",
    ]:
        assert marker in slide_regeneration_text
    for marker in ["def recompile_run_after_scene_save"]:
        assert marker in scene_recompile_text
    for marker in [
        "def build_slide_generated_preview_payload",
        "def build_regeneration_rule_violations",
    ]:
        assert marker in slide_regeneration_reporting_text
    for marker in ["def regenerate_single_template_slide"]:
        assert marker in template_slide_regeneration_text
    for marker in [
        "def build_outline_rag_degraded_payload",
        "def build_requirements_analyzed_payload",
        "def build_outline_repair_started_payload",
        "def build_plan_completed_payload",
    ]:
        assert marker in outline_reporting_text
    for marker in [
        "def build_template_mapping_report",
        "def build_slot_mapping_entry",
        "def build_template_layout_completed_payload",
        "def build_chart_truth_checked_payload",
    ]:
        assert marker in template_apply_reporting_text
    for marker in [
        "def build_repair_started_payload",
        "def build_repair_history_entry",
        "def build_repair_round_completed_payload",
        "def increment_verification_cycles",
    ]:
        assert marker in repair_round_reporting_text

    for forbidden in [
        "def _build_slide_plan",
        "def _apply_local_spec_repairs",
        "def _rotate_layout_hint",
        "def _trim_spec_bullets",
        "def _build_slide_brief",
        "def _candidate_variant_specs",
        "def _fallback_research_brief",
        "def _slide_spec_from_generated",
        "def _generated_from_slide_spec",
    ]:
        assert forbidden in orchestrator_text or forbidden in slide_generation_mixin_text, (
            "thin compatibility wrappers may remain in orchestrator or explicit run-owned mixins, "
            f"but {forbidden} should delegate into explicit run-owned rule modules"
        )

    assert "from .preview_quality.reporting import (" in qa_reporting_text
    assert "from .preview_quality.static_checks import (" in qa_static_checks_text
    assert "from .preview_quality.sampling import (" in qa_preview_sampling_text
    assert "from .preview_quality.mode_execution import (" in qa_mode_execution_text


def test_skill_slide_rendering_should_live_under_slides_modules() -> None:
    orchestrator_text = (ROOT / "service" / "run" / "orchestrator.py").read_text(
        encoding="utf-8"
    )
    slide_generation_mixin_text = (
        ROOT / "service" / "run" / "slide_generation_primitives_mixin.py"
    ).read_text(encoding="utf-8")
    renderer_text = (
        ROOT / "service" / "slides" / "skill_slide_renderer.py"
    ).read_text(encoding="utf-8")
    blocks_text = (
        ROOT / "service" / "slides" / "skill_slide_blocks.py"
    ).read_text(encoding="utf-8")

    for marker in [
        "def render_skill_slide_js",
        "def build_compile_script",
        "def theme_js_literal",
    ]:
        assert marker in renderer_text
    for marker in [
        "def slide_content_block",
        "def slide_block_cover",
        "def slide_block_toc",
        "def slide_block_section",
        "def slide_block_content",
        "def slide_block_summary",
    ]:
        assert marker in blocks_text
    for wrapper in [
        "def _render_skill_slide_js",
        "def _build_compile_script",
        "def _slide_content_block",
        "def _slide_block_cover",
        "def _slide_block_toc",
        "def _slide_block_section",
        "def _slide_block_content",
        "def _slide_block_summary",
    ]:
        assert wrapper in orchestrator_text or wrapper in slide_generation_mixin_text, (
            "thin compatibility wrappers may remain in orchestrator or explicit run-owned mixins, "
            f"but {wrapper} should delegate into service/slides modules"
        )
