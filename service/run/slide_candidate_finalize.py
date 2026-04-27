from __future__ import annotations

from typing import Any, Awaitable, Callable

from ..models import EventType
from .slide_candidate_state import AgenticSlideCandidateState


async def publish_candidate_repair_cycle(
    *,
    run_id: str,
    slide_no: int,
    repair_round: int,
    state: AgenticSlideCandidateState,
    publish: Callable[[str, EventType, dict[str, Any]], Awaitable[None]],
) -> None:
    await publish(
        run_id,
        EventType.SLIDE_CRITIC_COMPLETED,
        {
            "slide_no": slide_no,
            "round": repair_round,
            "issues": list(state.last_major_issues),
        },
    )
    await publish(
        run_id,
        EventType.SLIDE_REPAIR_DIRECTIVES_GENERATED,
        {
            "slide_no": slide_no,
            "round": repair_round,
            "directives": list(state.selected_repair_directives),
            "variant": dict(state.best_variant),
        },
    )
    await publish(
        run_id,
        EventType.SLIDE_REPAIR_COMPLETED,
        {"slide_no": slide_no, "round": repair_round},
    )


def candidate_issue_excerpt(*, state: AgenticSlideCandidateState, limit: int = 20) -> list[str]:
    return list(state.last_major_issues + state.last_warnings)[:limit]


def build_rounds_exhausted_details(
    *,
    state: AgenticSlideCandidateState,
) -> dict[str, Any]:
    return {
        "issues": candidate_issue_excerpt(state=state),
        "failure_context": dict(state.last_failure_context),
    }


def build_missing_output_details(
    *,
    state: AgenticSlideCandidateState,
) -> dict[str, Any]:
    return {
        "issues": candidate_issue_excerpt(state=state),
    }


def resolve_final_citations(
    *,
    state: AgenticSlideCandidateState,
    rag_source_ids: list[str],
    slide_no: int,
    normalize_citations: Callable[[list[str], list[str], int], list[str]],
) -> list[str]:
    if state.best_citations:
        return list(state.best_citations)
    return normalize_citations([], rag_source_ids, slide_no)


def build_chart_truth_entry(
    *,
    slide_no: int,
    state: AgenticSlideCandidateState,
) -> dict[str, Any]:
    chart_plan = state.best_chart_plan
    assert chart_plan is not None
    return {
        "slide_no": slide_no,
        "has_verified_data": chart_plan.has_verified_data,
        "mode": chart_plan.mode,
        "source": chart_plan.source,
        "note": chart_plan.note,
        "labels": chart_plan.labels,
    }


def build_chart_truth_payload(
    *,
    slide_no: int,
    state: AgenticSlideCandidateState,
) -> dict[str, Any]:
    chart_plan = state.best_chart_plan
    assert chart_plan is not None
    return {
        "slide_no": slide_no,
        "has_verified_data": chart_plan.has_verified_data,
        "mode": chart_plan.mode,
        "source": chart_plan.source,
    }


def build_codegen_completed_payload(
    *,
    slide_no: int,
    state: AgenticSlideCandidateState,
) -> dict[str, Any]:
    return {
        "slide_no": slide_no,
        "rounds": state.round_passed,
        "degraded_accept": state.degraded_accept,
    }
