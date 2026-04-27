from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..design.skill_profile import DesignProfile
from ..models import EventType, OutlineNode
from .agentic_slide_preparation import PreparedAgenticSlideContext
from .slide_candidate_execution import execute_agentic_candidate_build
from .slide_candidate_reporting import (
    build_candidate_generated_payload,
    build_failure_diagnostics_payload,
)
from .slide_candidate_state import record_build_failure


@dataclass
class AgenticRoundBuildResult:
    llm_phase: str
    js_code: str
    citations: list[str]
    chart_plan: Any


async def execute_agentic_round_build(
    orch: Any,
    *,
    run_id: str,
    slide_no: int,
    repair_round: int,
    node: OutlineNode,
    design: DesignProfile,
    context: PreparedAgenticSlideContext,
    candidate_plan: dict[str, Any],
) -> AgenticRoundBuildResult:
    run = context.run
    build_result = await execute_agentic_candidate_build(
        run_id=run_id,
        slide_no=slide_no,
        repair_round=repair_round,
        target_slide_count=run.input.target_slide_count,
        node=node,
        rag_source_ids=run.input.rag_source_ids,
        best_js=context.candidate_state.best_js,
        auto_canonicalize_enabled=orch.slide_auto_canonicalize,
        call_build=lambda: orch._call_llm_with_timeout_retry(
            run_id=run_id,
            phase=f"slide.{slide_no}.round.{repair_round}.candidate.1.build",
            action=lambda: orch.llm_client.generate_slide_js(
                topic=run.input.topic,
                template_style=context.effective_template_style,
                slide_no=slide_no,
                target_slide_count=run.input.target_slide_count,
                outline_node=node,
                theme=design.theme,
                title_font=design.title_font,
                body_font=design.body_font,
                rag_source_ids=run.input.rag_source_ids,
                visual_policy=run.input.visual_policy,
                slide_plan=candidate_plan,
                slide_brief=context.slide_brief,
            ),
        ),
        call_repair=lambda: orch._call_llm_with_timeout_retry(
            run_id=run_id,
            phase=f"slide.{slide_no}.round.{repair_round}.candidate.1.repair",
            action=lambda: orch.llm_client.critique_slide_js(
                topic=run.input.topic,
                template_style=context.effective_template_style,
                slide_no=slide_no,
                target_slide_count=run.input.target_slide_count,
                outline_node=node,
                candidate_js=context.candidate_state.best_js,
                issues=orch._dedupe_preserve_order(
                    context.candidate_state.last_major_issues + context.candidate_state.last_warnings
                ),
                failure_context=context.candidate_state.last_failure_context,
                visual_policy=run.input.visual_policy,
                slide_plan=candidate_plan,
                repair_directives=context.candidate_state.selected_repair_directives,
                preview_text=context.candidate_state.selected_preview_text,
                slide_brief=context.slide_brief,
            ),
        ),
        normalize_citations=orch._normalize_citations,
        normalize_generated_js=lambda raw_js, raw_slide_no, raw_node, raw_target_slide_count: orch._normalize_generated_slide_js(
            raw_js,
            slide_no=raw_slide_no,
            node=raw_node,
            target_slide_count=raw_target_slide_count,
        ),
        auto_canonicalize_js=lambda raw_js, raw_slide_no, raw_node, raw_target_slide_count: orch._auto_canonicalize_slide_js(
            raw_js,
            slide_no=raw_slide_no,
            node=raw_node,
            target_slide_count=raw_target_slide_count,
        ),
        dedupe_preserve_order=orch._dedupe_preserve_order,
        publish=orch._publish,
        apply_local_js_guardrails=lambda raw_js, raw_slide_no, raw_page_type: orch._apply_local_js_guardrails(
            js_code=raw_js,
            slide_no=raw_slide_no,
            page_type=raw_page_type,
        ),
        extract_candidate_from_js=lambda raw_js, raw_node, raw_citations: orch.quality_engine.extract_candidate_from_js(
            js_code=raw_js,
            fallback_node=raw_node,
            citations=raw_citations,
        ),
        build_chart_plan_from_bullets=lambda raw_node, raw_citations: orch._build_chart_plan_from_bullets(
            node=raw_node,
            source_refs=raw_citations,
        ),
    )
    return AgenticRoundBuildResult(
        llm_phase=build_result.llm_phase,
        js_code=build_result.js_code,
        citations=build_result.citations,
        chart_plan=build_result.chart_plan,
    )


async def publish_agentic_build_failure(
    orch: Any,
    *,
    run_id: str,
    slide_no: int,
    repair_round: int,
    context: PreparedAgenticSlideContext,
    variant: dict[str, Any],
    llm_phase: str,
    exc: Exception,
) -> None:
    build_issue = f"candidate build failed: {orch._exception_reason(exc)}"
    classified = orch._classify_slide_issues([build_issue])
    quality_score = orch._local_quality_score(classified=classified)
    failure_context = orch._build_slide_failure_context(
        phase=llm_phase,
        slide_js_path=context.candidate_path,
        candidate_js=(context.candidate_state.best_js or ""),
        issues=[build_issue],
        diagnostics={
            "error_class": type(exc).__name__,
            "error_message": orch._exception_reason(exc),
            "attempt": repair_round,
            "gate_summary": {
                "blocking": len(classified["blocking"]),
                "high_risk": len(classified["high_risk"]),
                "warnings": len(classified["warnings"]),
            },
        },
    )
    record_build_failure(
        state=context.candidate_state,
        classified=classified,
        quality_score=quality_score,
        repair_directives=orch._build_local_repair_directives(classified=classified),
        failure_context=failure_context,
    )
    await orch._publish(
        run_id,
        EventType.SLIDE_FAILURE_DIAGNOSTICS,
        build_failure_diagnostics_payload(
            slide_no=slide_no,
            repair_round=repair_round,
            phase=llm_phase,
            context=context.candidate_state.last_failure_context,
            repair_directives=context.candidate_state.selected_repair_directives,
        ),
    )
    await orch._publish_retry_context_event(
        run_id=run_id,
        slide_no=slide_no,
        repair_round=repair_round,
        candidate_no=1,
        phase=llm_phase,
        issues=[build_issue],
        context=context.candidate_state.last_failure_context,
    )
    await orch._publish(
        run_id,
        EventType.SLIDE_CANDIDATE_GENERATED,
        build_candidate_generated_payload(
            slide_no=slide_no,
            repair_round=repair_round,
            quality_score=context.candidate_state.quality_score,
            passed=False,
            blocking=classified["blocking"],
            high_risk=classified["high_risk"],
            warnings=classified["warnings"],
            variant=variant,
            error=orch._exception_reason(exc),
            phase=llm_phase,
        ),
    )
