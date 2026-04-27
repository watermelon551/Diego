from __future__ import annotations

import asyncio

from service.models import EventType
from service.run.slide_candidate_finalize import (
    build_chart_truth_entry,
    build_chart_truth_payload,
    build_codegen_completed_payload,
    build_missing_output_details,
    build_rounds_exhausted_details,
    candidate_issue_excerpt,
    publish_candidate_repair_cycle,
    resolve_final_citations,
)
from service.run.slide_candidate_state import AgenticSlideCandidateState
from service.run.types import ChartPlan


def _state() -> AgenticSlideCandidateState:
    return AgenticSlideCandidateState(
        best_citations=["r1", "r2"],
        best_variant={"round": 2},
        last_major_issues=["preview compile failed"],
        last_warnings=["title font too small"],
        last_failure_context={"phase": "candidate.preview"},
        selected_repair_directives=["fix preview", "increase title size"],
        round_passed=2,
        degraded_accept=True,
        best_chart_plan=ChartPlan(
            has_verified_data=False,
            mode="qualitative_fallback",
            labels=["A"],
            values=[1.0],
            unit="",
            note="No verified data",
            source="src-1",
        ),
    )


def test_finalize_helpers_should_build_deterministic_payloads() -> None:
    state = _state()
    assert candidate_issue_excerpt(state=state) == [
        "preview compile failed",
        "title font too small",
    ]
    assert build_rounds_exhausted_details(state=state) == {
        "issues": ["preview compile failed", "title font too small"],
        "failure_context": {"phase": "candidate.preview"},
    }
    assert build_missing_output_details(state=state) == {
        "issues": ["preview compile failed", "title font too small"],
    }
    assert build_chart_truth_entry(slide_no=3, state=state) == {
        "slide_no": 3,
        "has_verified_data": False,
        "mode": "qualitative_fallback",
        "source": "src-1",
        "note": "No verified data",
        "labels": ["A"],
    }
    assert build_chart_truth_payload(slide_no=3, state=state) == {
        "slide_no": 3,
        "has_verified_data": False,
        "mode": "qualitative_fallback",
        "source": "src-1",
    }
    assert build_codegen_completed_payload(slide_no=3, state=state) == {
        "slide_no": 3,
        "rounds": 2,
        "degraded_accept": True,
    }


def test_resolve_final_citations_should_fall_back_to_normalizer() -> None:
    state = AgenticSlideCandidateState()
    assert resolve_final_citations(
        state=state,
        rag_source_ids=["a", "b"],
        slide_no=2,
        normalize_citations=lambda _c, rag_ids, slide_no: [rag_ids[slide_no - 1]],
    ) == ["b"]
    state.best_citations = ["r1"]
    assert resolve_final_citations(
        state=state,
        rag_source_ids=["a", "b"],
        slide_no=2,
        normalize_citations=lambda *_args: ["x"],
    ) == ["r1"]


def test_publish_candidate_repair_cycle_should_emit_three_events() -> None:
    events: list[tuple[str, EventType, dict]] = []

    async def publish(run_id: str, event_type: EventType, payload: dict) -> None:
        events.append((run_id, event_type, payload))

    asyncio.run(
        publish_candidate_repair_cycle(
            run_id="run-1",
            slide_no=4,
            repair_round=3,
            state=_state(),
            publish=publish,
        )
    )
    assert [event_type for _, event_type, _ in events] == [
        EventType.SLIDE_CRITIC_COMPLETED,
        EventType.SLIDE_REPAIR_DIRECTIVES_GENERATED,
        EventType.SLIDE_REPAIR_COMPLETED,
    ]
    assert events[0][2]["issues"] == ["preview compile failed"]
    assert events[1][2]["directives"] == ["fix preview", "increase title size"]
    assert events[1][2]["variant"] == {"round": 2}
