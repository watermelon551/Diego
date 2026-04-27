from __future__ import annotations

from typing import Any

from ..agentic_slide_round_building import execute_agentic_round_build
from ..slide_candidate_state import build_candidate_plan, build_candidate_variant
from .build_failure import handle_candidate_build_failure
from .review_cycle import review_candidate_cycle
from .rounds_exhausted import raise_if_rounds_exhausted


async def run_agentic_candidate_rounds(
    orch: Any,
    *,
    run_id: str,
    slide_no: int,
    node,
    design,
    context,
) -> None:
    run = context.run
    candidate_state = context.candidate_state
    for repair_round in range(1, context.hard_round_limit + 1):
        variant = build_candidate_variant(
            slide_no=slide_no, repair_round=repair_round, slide_plan=context.slide_plan
        )
        candidate_plan = build_candidate_plan(
            slide_plan=context.slide_plan,
            variant=variant,
            repair_round=repair_round,
            previous_issues=candidate_state.last_major_issues,
        )
        llm_phase = "candidate.build"
        try:
            build_result = await execute_agentic_round_build(
                orch,
                run_id=run_id,
                slide_no=slide_no,
                repair_round=repair_round,
                node=node,
                design=design,
                context=context,
                candidate_plan=candidate_plan,
            )
            llm_phase = build_result.llm_phase
        except Exception as exc:
            accepted = await handle_candidate_build_failure(
                orch,
                run_id=run_id,
                slide_no=slide_no,
                repair_round=repair_round,
                context=context,
                candidate_state=candidate_state,
                variant=variant,
                llm_phase=llm_phase,
                exc=exc,
            )
            if accepted:
                break
            continue

        context.candidate_path.write_text(build_result.js_code, encoding="utf-8")
        cycle_result = await review_candidate_cycle(
            orch,
            run_id=run_id,
            slide_no=slide_no,
            repair_round=repair_round,
            run=run,
            node=node,
            context=context,
            candidate_state=candidate_state,
            variant=variant,
            candidate_plan=candidate_plan,
            js_code=build_result.js_code,
            citations=build_result.citations,
            chart_plan=build_result.chart_plan,
        )
        if cycle_result == "accepted":
            break
        raise_if_rounds_exhausted(
            orch,
            slide_no=slide_no,
            repair_round=repair_round,
            context=context,
            candidate_state=candidate_state,
        )
