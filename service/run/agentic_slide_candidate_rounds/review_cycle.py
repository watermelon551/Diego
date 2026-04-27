from __future__ import annotations

from typing import Any

from ...models import EventType
from ..agentic_slide_round_reporting import publish_agentic_review_events
from ..slide_candidate_decisions import (
    should_accept_candidate_result,
    should_accept_degraded_after_quality_gate,
    should_raise_visual_policy_unsatisfied,
)
from ..slide_candidate_finalize import publish_candidate_repair_cycle
from ..slide_candidate_reporting import build_failure_diagnostics_payload
from ..slide_candidate_state import mark_round_accepted, record_candidate_review
from ..types import VisualPolicyUnsatisfiedError


async def review_candidate_cycle(
    orch: Any,
    *,
    run_id: str,
    slide_no: int,
    repair_round: int,
    run,
    node,
    context,
    candidate_state,
    variant: dict[str, Any],
    candidate_plan: dict[str, Any],
    js_code: str,
    citations: list[str],
    chart_plan,
):
    from ..slide_candidate_review import review_agentic_candidate_quality

    review_result = await review_agentic_candidate_quality(
        run_id=run_id,
        slide_no=slide_no,
        repair_round=repair_round,
        candidate_path=context.candidate_path,
        js_code=js_code,
        page_type=node.page_type.value,
        visual_policy=run.input.visual_policy,
        slide_plan=candidate_plan,
        compile_failure_markers=context.compile_failure_markers,
        validate_slide_js_contract=orch._validate_slide_js_contract,
        run_slide_preview_qa_with_text=orch._run_slide_preview_qa_with_text,
        dedupe_preserve_order=orch._dedupe_preserve_order,
        classify_slide_issues=orch._classify_slide_issues,
        local_quality_score=orch._local_quality_score,
        build_local_repair_directives=orch._build_local_repair_directives,
        build_slide_failure_context=orch._build_slide_failure_context,
    )
    if review_result.needs_repair:
        candidate_state.last_failure_context = dict(review_result.failure_context)
        await orch._publish(
            run_id,
            EventType.SLIDE_FAILURE_DIAGNOSTICS,
            build_failure_diagnostics_payload(
                slide_no=slide_no,
                repair_round=repair_round,
                phase=str(review_result.failure_phase or ""),
                context=candidate_state.last_failure_context,
                repair_directives=review_result.repair_directives,
            ),
        )
        await orch._publish_retry_context_event(
            run_id=run_id,
            slide_no=slide_no,
            repair_round=repair_round,
            candidate_no=1,
            phase=str(review_result.failure_phase or ""),
            issues=review_result.all_issues,
            context=candidate_state.last_failure_context,
        )
    await publish_agentic_review_events(
        orch,
        run_id=run_id,
        slide_no=slide_no,
        repair_round=repair_round,
        review_result=review_result,
        variant=variant,
        visual_policy=run.input.visual_policy.value,
    )
    record_candidate_review(
        state=candidate_state,
        js_code=js_code,
        chart_plan=chart_plan,
        citations=citations,
        variant=variant,
        preview_text=review_result.preview_text,
        compile_ok=review_result.compile_ok,
        blocking=review_result.blocking,
        high_risk=review_result.high_risk,
        degraded_notes=review_result.degraded_notes,
        quality_score=review_result.quality_score,
        repair_directives=review_result.repair_directives,
    )
    context.candidate_path.unlink(missing_ok=True)
    accepted, accepted_as_degraded = should_accept_candidate_result(
        needs_repair=review_result.needs_repair,
        degraded_notes=review_result.degraded_notes,
    )
    if accepted:
        context.slide_path.write_text(candidate_state.best_js, encoding="utf-8")
        mark_round_accepted(
            state=candidate_state,
            repair_round=repair_round,
            degraded_accept=accepted_as_degraded,
            clear_failure_context=True,
        )
        return "accepted"
    if should_raise_visual_policy_unsatisfied(
        repair_round=repair_round,
        soft_round_limit=context.soft_round_limit,
        issues=(candidate_state.last_major_issues + candidate_state.last_warnings),
    ):
        raise VisualPolicyUnsatisfiedError(
            f"slide {slide_no} cannot satisfy visual policy: {'; '.join((candidate_state.last_major_issues + candidate_state.last_warnings)[:3])}"
        )
    if should_accept_degraded_after_quality_gate(
        repair_round=repair_round,
        soft_round_limit=context.soft_round_limit,
        best_compile_ok=candidate_state.best_compile_ok,
    ):
        context.slide_path.write_text(candidate_state.best_js, encoding="utf-8")
        mark_round_accepted(
            state=candidate_state, repair_round=repair_round, degraded_accept=True
        )
        return "accepted"
    await publish_candidate_repair_cycle(
        run_id=run_id,
        slide_no=slide_no,
        repair_round=repair_round,
        state=candidate_state,
        publish=orch._publish,
    )
    return "continue"
