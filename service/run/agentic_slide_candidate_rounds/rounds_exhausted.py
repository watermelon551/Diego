from __future__ import annotations

from typing import Any

from ..slide_candidate_decisions import (
    build_rounds_exhausted_reason,
    should_raise_rounds_exhausted,
)
from ..slide_candidate_finalize import (
    build_rounds_exhausted_details,
    candidate_issue_excerpt,
)
from ..types import SlideGenerationError, VisualPolicyUnsatisfiedError


def raise_if_rounds_exhausted(
    orch: Any,
    *,
    slide_no: int,
    repair_round: int,
    context,
    candidate_state,
) -> None:
    if not should_raise_rounds_exhausted(
        repair_round=repair_round, hard_round_limit=context.hard_round_limit
    ):
        return
    if orch.keep_failed_candidate_js and candidate_state.best_js:
        orch._persist_failed_candidate_js(
            slides_dir=context.slide_path.parent,
            slide_no=slide_no,
            js_code=candidate_state.best_js,
            round_no=repair_round,
            issues=candidate_issue_excerpt(state=candidate_state),
        )
    all_issues = orch._dedupe_preserve_order(
        candidate_state.last_major_issues + candidate_state.last_warnings
    )
    if any("visual_policy violation" in item.lower() for item in all_issues):
        raise VisualPolicyUnsatisfiedError(
            f"slide {slide_no} cannot satisfy visual policy: {'; '.join(all_issues[:3])}"
        )
    raise SlideGenerationError(
        slide_no=slide_no,
        phase="candidate.rounds_exhausted",
        reason=build_rounds_exhausted_reason(
            soft_round_limit=context.soft_round_limit,
            hard_round_limit=context.hard_round_limit,
        ),
        round_no=repair_round,
        details=build_rounds_exhausted_details(state=candidate_state),
    )
