from __future__ import annotations

from typing import Any

from ..models import EventType
from .slide_candidate_reporting import (
    build_candidate_generated_payload,
    build_candidate_selection_entry,
    build_quality_gate_completed_payload,
    build_quality_gate_entry,
    build_selection_completed_payload,
)


async def publish_agentic_review_events(
    orch: Any,
    run_id: str,
    *,
    slide_no: int,
    repair_round: int,
    review_result: Any,
    variant: dict[str, Any],
    visual_policy: str,
) -> None:
    await orch._publish(
        run_id,
        EventType.SLIDE_CANDIDATE_GENERATED,
        build_candidate_generated_payload(
            slide_no=slide_no,
            repair_round=repair_round,
            quality_score=review_result.quality_score,
            passed=not review_result.needs_repair,
            blocking=review_result.blocking,
            high_risk=review_result.high_risk,
            warnings=review_result.warnings,
            variant=variant,
            preview_mode=review_result.preview_mode,
        ),
    )
    await orch._append_candidate_selection_entry(
        run_id=run_id,
        entry=build_candidate_selection_entry(
            slide_no=slide_no,
            repair_round=repair_round,
            quality_score=review_result.quality_score,
            passed=not review_result.needs_repair,
            degraded=bool(review_result.degraded_notes) and not review_result.needs_repair,
            blocking=review_result.blocking,
            high_risk=review_result.high_risk,
            variant=variant,
            preview_mode=review_result.preview_mode,
        ),
    )
    await orch._publish(
        run_id,
        EventType.SLIDE_SELECTION_COMPLETED,
        build_selection_completed_payload(
            slide_no=slide_no,
            repair_round=repair_round,
            quality_score=review_result.quality_score,
            passed=not review_result.needs_repair,
            degraded=bool(review_result.degraded_notes) and not review_result.needs_repair,
            variant=variant,
        ),
    )
    await orch._append_quality_gate_entry(
        run_id=run_id,
        entry=build_quality_gate_entry(
            slide_no=slide_no,
            repair_round=repair_round,
            visual_policy=visual_policy,
            quality_score=review_result.quality_score,
            blocking=review_result.blocking,
            high_risk=review_result.high_risk,
            warnings=review_result.warnings,
            repair_directives=review_result.repair_directives,
            passed=not review_result.needs_repair,
        ),
    )
    await orch._publish(
        run_id,
        EventType.SLIDE_QUALITY_GATE_COMPLETED,
        build_quality_gate_completed_payload(
            slide_no=slide_no,
            repair_round=repair_round,
            quality_score=review_result.quality_score,
            passed=not review_result.needs_repair,
            blocking=review_result.blocking,
            high_risk=review_result.high_risk,
            warnings=review_result.warnings,
        ),
    )
