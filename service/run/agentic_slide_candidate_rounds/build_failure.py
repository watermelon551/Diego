from __future__ import annotations

from typing import Any

from ...models import EventType
from ..slide_candidate_decisions import (
    should_accept_degraded_after_build_failure,
    should_raise_rounds_exhausted,
)
from ..slide_candidate_state import mark_round_accepted
from ..types import SlideGenerationError


async def handle_candidate_build_failure(
    orch: Any,
    *,
    run_id: str,
    slide_no: int,
    repair_round: int,
    context,
    candidate_state,
    variant: dict[str, Any],
    llm_phase: str,
    exc: Exception,
) -> bool:
    from ..agentic_slide_round_building import publish_agentic_build_failure

    await publish_agentic_build_failure(
        orch,
        run_id=run_id,
        slide_no=slide_no,
        repair_round=repair_round,
        context=context,
        variant=variant,
        llm_phase=llm_phase,
        exc=exc,
    )
    if should_accept_degraded_after_build_failure(
        repair_round=repair_round,
        soft_round_limit=context.soft_round_limit,
        has_best_js=bool(candidate_state.best_js),
        best_compile_ok=candidate_state.best_compile_ok,
    ):
        context.slide_path.write_text(candidate_state.best_js, encoding="utf-8")
        mark_round_accepted(
            state=candidate_state, repair_round=repair_round, degraded_accept=True
        )
        return True
    if should_raise_rounds_exhausted(
        repair_round=repair_round, hard_round_limit=context.hard_round_limit
    ):
        raise SlideGenerationError(
            slide_no=slide_no,
            phase=llm_phase,
            reason=orch._exception_reason(exc),
            round_no=repair_round,
            details={"issues": [f"candidate build failed: {orch._exception_reason(exc)}"]},
        ) from exc
    return False
