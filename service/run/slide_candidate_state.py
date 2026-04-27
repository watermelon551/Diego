from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .types import ChartPlan


@dataclass
class AgenticSlideCandidateState:
    best_js: str = ""
    best_chart_plan: ChartPlan | None = None
    best_citations: list[str] = field(default_factory=list)
    best_variant: dict[str, Any] = field(default_factory=dict)
    last_major_issues: list[str] = field(default_factory=list)
    last_warnings: list[str] = field(default_factory=list)
    last_failure_context: dict[str, Any] = field(default_factory=dict)
    selected_repair_directives: list[str] = field(default_factory=list)
    selected_preview_text: str = ""
    quality_score: int = 0
    round_passed: int = 0
    degraded_accept: bool = False
    best_compile_ok: bool = False


def build_candidate_variant(
    *,
    slide_no: int,
    repair_round: int,
    slide_plan: dict[str, Any],
) -> dict[str, Any]:
    return {
        "mode": "scratch_llm_js",
        "worker": 1,
        "round": repair_round,
        "layout_anchor": str(slide_plan.get("layout", "")),
        "seed": f"s{slide_no}-r{repair_round}-scratch-llm-js",
    }


def build_candidate_plan(
    *,
    slide_plan: dict[str, Any],
    variant: dict[str, Any],
    repair_round: int,
    previous_issues: list[str],
) -> dict[str, Any]:
    candidate_plan = dict(slide_plan)
    candidate_plan["candidate_worker"] = 1
    candidate_plan["variant"] = variant
    candidate_plan["repair_round"] = repair_round
    candidate_plan["previous_issues"] = previous_issues[:8]
    return candidate_plan


def record_build_failure(
    *,
    state: AgenticSlideCandidateState,
    classified: dict[str, list[str]],
    quality_score: int,
    repair_directives: list[str],
    failure_context: dict[str, Any],
) -> None:
    state.selected_repair_directives = list(repair_directives)
    state.quality_score = quality_score
    state.last_failure_context = dict(failure_context)
    state.last_major_issues = list(classified.get("blocking", []) + classified.get("high_risk", []))
    state.last_warnings = list(classified.get("warnings", []))


def record_candidate_review(
    *,
    state: AgenticSlideCandidateState,
    js_code: str,
    chart_plan: ChartPlan,
    citations: list[str],
    variant: dict[str, Any],
    preview_text: str,
    compile_ok: bool,
    blocking: list[str],
    high_risk: list[str],
    degraded_notes: list[str],
    quality_score: int,
    repair_directives: list[str],
) -> None:
    state.best_js = js_code
    state.best_chart_plan = chart_plan
    state.best_citations = list(citations)
    state.best_variant = dict(variant)
    state.selected_preview_text = preview_text
    state.last_major_issues = list(blocking + high_risk)
    state.last_warnings = list(degraded_notes)
    state.best_compile_ok = compile_ok
    state.quality_score = quality_score
    state.selected_repair_directives = list(repair_directives)


def mark_round_accepted(
    *,
    state: AgenticSlideCandidateState,
    repair_round: int,
    degraded_accept: bool,
    clear_failure_context: bool = False,
) -> None:
    state.round_passed = repair_round
    state.degraded_accept = degraded_accept
    if clear_failure_context:
        state.last_failure_context = {}


def final_slide_status(*, state: AgenticSlideCandidateState) -> str:
    if state.degraded_accept:
        return f"ok_agentic_degraded_round_{state.round_passed}"
    return f"ok_agentic_round_{state.round_passed}"
