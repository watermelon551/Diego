from __future__ import annotations

from typing import Any

from ..models import EventType, SlideArtifact
from .slide_candidate_finalize import (
    build_chart_truth_entry,
    build_chart_truth_payload,
    build_codegen_completed_payload,
    resolve_final_citations,
)
from .slide_candidate_reporting import build_quality_entry
from .slide_candidate_state import final_slide_status


async def finalize_agentic_slide(
    orch: Any,
    *,
    run_id: str,
    slide_no: int,
    run: Any,
    slide_path: Any,
    candidate_state: Any,
) -> SlideArtifact:
    final_js = slide_path.read_text(encoding="utf-8")
    citations = resolve_final_citations(
        state=candidate_state,
        rag_source_ids=run.input.rag_source_ids,
        slide_no=slide_no,
        normalize_citations=orch._normalize_citations,
    )
    if candidate_state.best_chart_plan is not None:
        await orch._append_chart_truth_report(
            run_id=run_id,
            entry=build_chart_truth_entry(slide_no=slide_no, state=candidate_state),
        )
        await orch._publish(
            run_id,
            EventType.CHART_TRUTH_CHECKED,
            build_chart_truth_payload(slide_no=slide_no, state=candidate_state),
        )

    await orch._append_quality_entry(
        run_id=run_id,
        entry=build_quality_entry(
            slide_no=slide_no,
            round_passed=candidate_state.round_passed,
            last_major_issues=candidate_state.last_major_issues,
            last_warnings=candidate_state.last_warnings,
            engine=orch.settings.generation_engine,
            quality_score=candidate_state.quality_score,
            visual_policy=run.input.visual_policy.value,
            selected_variant=candidate_state.best_variant,
            degraded_accept=candidate_state.degraded_accept,
            preview_text=candidate_state.selected_preview_text,
            repair_directives=candidate_state.selected_repair_directives,
        ),
    )
    await orch._publish(
        run_id,
        EventType.SLIDE_CODEGEN_COMPLETED,
        build_codegen_completed_payload(slide_no=slide_no, state=candidate_state),
    )
    return SlideArtifact(
        slide_no=slide_no,
        js_path=str(slide_path),
        js_code=final_js,
        status=final_slide_status(state=candidate_state),
        citations=citations,
    )
