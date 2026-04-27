from __future__ import annotations

from service.run.slide_candidate_state import (
    AgenticSlideCandidateState,
    build_candidate_plan,
    build_candidate_variant,
    final_slide_status,
    mark_round_accepted,
    record_build_failure,
    record_candidate_review,
)
from service.run.types import ChartPlan


def test_candidate_variant_and_plan_should_stay_deterministic() -> None:
    slide_plan = {"layout": "content-two-column", "other": 1}
    variant = build_candidate_variant(
        slide_no=3,
        repair_round=2,
        slide_plan=slide_plan,
    )
    assert variant["layout_anchor"] == "content-two-column"
    assert variant["seed"] == "s3-r2-scratch-llm-js"

    plan = build_candidate_plan(
        slide_plan=slide_plan,
        variant=variant,
        repair_round=2,
        previous_issues=["a", "b", "c"],
    )
    assert plan["candidate_worker"] == 1
    assert plan["variant"] == variant
    assert plan["repair_round"] == 2
    assert plan["previous_issues"] == ["a", "b", "c"]


def test_candidate_state_recorders_should_track_best_and_failure_context() -> None:
    state = AgenticSlideCandidateState()
    record_build_failure(
        state=state,
        classified={
            "blocking": ["preview compile failed"],
            "high_risk": ["title font too small"],
            "warnings": ["minor note"],
        },
        quality_score=61,
        repair_directives=["fix preview", "increase title size"],
        failure_context={"phase": "candidate.preview"},
    )
    assert state.quality_score == 61
    assert state.last_major_issues == [
        "preview compile failed",
        "title font too small",
    ]
    assert state.last_warnings == ["minor note"]
    assert state.selected_repair_directives == ["fix preview", "increase title size"]
    assert state.last_failure_context == {"phase": "candidate.preview"}

    chart_plan = ChartPlan(
        has_verified_data=False,
        mode="qualitative_fallback",
        labels=[],
        values=[],
        unit="",
        note="No verified data",
        source="",
    )
    record_candidate_review(
        state=state,
        js_code="module.exports = { createSlide, slideConfig };",
        chart_plan=chart_plan,
        citations=["r1", "r2"],
        variant={"round": 2},
        preview_text="preview body",
        compile_ok=True,
        blocking=["blocking"],
        high_risk=["high risk"],
        degraded_notes=["warn a"],
        quality_score=88,
        repair_directives=["tighten spacing"],
    )
    assert state.best_js.startswith("module.exports")
    assert state.best_chart_plan is chart_plan
    assert state.best_citations == ["r1", "r2"]
    assert state.best_variant == {"round": 2}
    assert state.selected_preview_text == "preview body"
    assert state.best_compile_ok is True
    assert state.quality_score == 88
    assert state.selected_repair_directives == ["tighten spacing"]


def test_candidate_state_acceptance_helpers_should_shape_final_status() -> None:
    state = AgenticSlideCandidateState(
        last_failure_context={"phase": "candidate.preview"}
    )
    mark_round_accepted(
        state=state,
        repair_round=3,
        degraded_accept=True,
        clear_failure_context=True,
    )
    assert state.round_passed == 3
    assert state.degraded_accept is True
    assert state.last_failure_context == {}
    assert final_slide_status(state=state) == "ok_agentic_degraded_round_3"

    state.degraded_accept = False
    assert final_slide_status(state=state) == "ok_agentic_round_3"
