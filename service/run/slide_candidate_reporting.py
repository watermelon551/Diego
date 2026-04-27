from __future__ import annotations

from typing import Any


def build_gate_counts(
    *,
    blocking: list[str],
    high_risk: list[str],
    warnings: list[str],
) -> dict[str, int]:
    return {
        "blocking": len(blocking),
        "high_risk": len(high_risk),
        "warnings": len(warnings),
    }


def build_failure_diagnostics_payload(
    *,
    slide_no: int,
    repair_round: int,
    phase: str,
    context: dict[str, Any],
    repair_directives: list[str],
) -> dict[str, Any]:
    return {
        "slide_no": slide_no,
        "round": repair_round,
        "candidate": 1,
        "phase": phase,
        "context": context,
        "error_type": str(context.get("error_class", "")),
        "stderr_excerpt": context.get("stderr_excerpt", ""),
        "error_location": context.get("error_location", {}),
        "repair_hint": repair_directives[:5],
    }


def build_candidate_generated_payload(
    *,
    slide_no: int,
    repair_round: int,
    quality_score: int,
    passed: bool,
    blocking: list[str],
    high_risk: list[str],
    warnings: list[str],
    variant: dict[str, Any],
    preview_mode: str | None = None,
    error: str | None = None,
    phase: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "slide_no": slide_no,
        "round": repair_round,
        "candidate": 1,
        "score": quality_score,
        "passed": passed,
        "hard_issue_count": len(blocking) + len(high_risk),
        "llm_issue_count": 0,
        "variant": variant,
        "gate": build_gate_counts(
            blocking=blocking,
            high_risk=high_risk,
            warnings=warnings,
        ),
    }
    if preview_mode is not None:
        payload["preview_mode"] = preview_mode
    if error:
        payload["error"] = error
    if phase:
        payload["phase"] = phase
    return payload


def build_candidate_selection_entry(
    *,
    slide_no: int,
    repair_round: int,
    quality_score: int,
    passed: bool,
    degraded: bool,
    blocking: list[str],
    high_risk: list[str],
    variant: dict[str, Any],
    preview_mode: str,
) -> dict[str, Any]:
    return {
        "slide_no": slide_no,
        "round": repair_round,
        "selected_candidate": 1,
        "selected_score": quality_score,
        "selected_passed": passed,
        "selected_degraded": degraded,
        "selected_variant": variant,
        "degraded_accept": degraded,
        "candidates": [
            {
                "candidate": 1,
                "mode": "scratch_llm_js",
                "variant": variant,
                "score": quality_score,
                "passed": passed,
                "degraded": degraded,
                "hard_issue_count": len(blocking) + len(high_risk),
                "llm_issue_count": 0,
                "preview_mode": preview_mode,
            }
        ],
    }


def build_selection_completed_payload(
    *,
    slide_no: int,
    repair_round: int,
    quality_score: int,
    passed: bool,
    degraded: bool,
    variant: dict[str, Any],
) -> dict[str, Any]:
    return {
        "slide_no": slide_no,
        "round": repair_round,
        "selected_candidate": 1,
        "score": quality_score,
        "passed": passed,
        "degraded": degraded,
        "variant": variant,
    }


def build_quality_gate_entry(
    *,
    slide_no: int,
    repair_round: int,
    visual_policy: str,
    quality_score: int,
    blocking: list[str],
    high_risk: list[str],
    warnings: list[str],
    repair_directives: list[str],
    passed: bool,
) -> dict[str, Any]:
    return {
        "slide_no": slide_no,
        "round": repair_round,
        "visual_policy": visual_policy,
        "gate_mode": "hard_only_v2",
        "score": quality_score,
        "threshold": 0,
        "hard_issues": list(blocking + high_risk),
        "llm_issues": [],
        "repair_directives": list(repair_directives),
        "blocking_issues": list(blocking),
        "high_risk_issues": list(high_risk),
        "warnings": list(warnings),
        "passed": passed,
    }


def build_quality_gate_completed_payload(
    *,
    slide_no: int,
    repair_round: int,
    quality_score: int,
    passed: bool,
    blocking: list[str],
    high_risk: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "slide_no": slide_no,
        "round": repair_round,
        "score": quality_score,
        "threshold": 0,
        "gate_mode": "hard_only_v2",
        "passed": passed,
        "hard_issue_count": len(blocking) + len(high_risk),
        "llm_issue_count": 0,
        "gate": build_gate_counts(
            blocking=blocking,
            high_risk=high_risk,
            warnings=warnings,
        ),
    }


def build_quality_entry(
    *,
    slide_no: int,
    round_passed: int,
    last_major_issues: list[str],
    last_warnings: list[str],
    engine: str,
    quality_score: int,
    visual_policy: str,
    selected_variant: dict[str, Any],
    degraded_accept: bool,
    preview_text: str,
    repair_directives: list[str],
) -> dict[str, Any]:
    return {
        "slide_no": slide_no,
        "passed_round": round_passed,
        "issues_last_round": list(last_major_issues + last_warnings),
        "engine": engine,
        "quality_score": quality_score,
        "visual_policy": visual_policy,
        "selected_variant": selected_variant,
        "degraded_accept": degraded_accept,
        "preview_text_excerpt": preview_text[:300],
        "repair_directives": repair_directives[:8],
        "llm_issues": [],
    }
