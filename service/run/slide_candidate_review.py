from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable


@dataclass
class CandidateQualityReviewResult:
    preview_mode: str
    preview_text: str
    preview_issues: list[str] = field(default_factory=list)
    preview_diag: dict[str, Any] = field(default_factory=dict)
    all_issues: list[str] = field(default_factory=list)
    compile_ok: bool = False
    blocking: list[str] = field(default_factory=list)
    high_risk: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    needs_repair: bool = False
    degraded_notes: list[str] = field(default_factory=list)
    quality_score: int = 0
    repair_directives: list[str] = field(default_factory=list)
    failure_phase: str | None = None
    failure_context: dict[str, Any] = field(default_factory=dict)


async def review_agentic_candidate_quality(
    *,
    run_id: str,
    slide_no: int,
    repair_round: int,
    candidate_path: Path,
    js_code: str,
    page_type: str,
    visual_policy: Any,
    slide_plan: dict[str, Any],
    compile_failure_markers: tuple[str, ...],
    validate_slide_js_contract: Callable[..., list[str]],
    run_slide_preview_qa_with_text: Callable[..., Awaitable[tuple[list[str], str, dict[str, Any]]]],
    dedupe_preserve_order: Callable[[list[str]], list[str]],
    classify_slide_issues: Callable[[list[str]], dict[str, list[str]]],
    local_quality_score: Callable[..., int],
    build_local_repair_directives: Callable[..., list[str]],
    build_slide_failure_context: Callable[..., dict[str, Any]],
) -> CandidateQualityReviewResult:
    hard_issues = validate_slide_js_contract(
        js_code,
        slide_no=slide_no,
        page_type=page_type,
        visual_policy=visual_policy,
        slide_plan=slide_plan,
    )
    fatal_contract = any(
        issue
        in {
            "missing export contract",
            "createSlide signature invalid",
            "createSlide must be synchronous",
        }
        for issue in hard_issues
    )

    preview_mode = "full"
    preview_text = ""
    preview_issues: list[str] = []
    preview_diag: dict[str, Any] = {}
    if fatal_contract:
        preview_mode = "skip_contract_failure"
        preview_issues.append("preview skipped due to fatal contract issue")
    else:
        preview_issues, preview_text, preview_diag = await run_slide_preview_qa_with_text(
            run_id=run_id,
            slide_js=candidate_path,
            slide_no=slide_no,
        )

    all_issues = dedupe_preserve_order(list(hard_issues) + list(preview_issues))
    compile_ok = not any(
        any(marker in str(issue).lower() for marker in compile_failure_markers)
        for issue in all_issues
    )
    classified = classify_slide_issues(all_issues)
    blocking = list(classified["blocking"])
    high_risk = list(classified["high_risk"])
    warnings = list(classified["warnings"])
    needs_repair = bool(blocking)
    degraded_notes = dedupe_preserve_order(high_risk + warnings)
    quality_score = local_quality_score(classified=classified)
    repair_directives = build_local_repair_directives(classified=classified)

    failure_phase: str | None = None
    failure_context: dict[str, Any] = {}
    if needs_repair:
        diagnostics = dict(preview_diag or {})
        diagnostics.setdefault("preview_mode", preview_mode)
        diagnostics["attempt"] = repair_round
        diagnostics["gate_summary"] = {
            "blocking": len(blocking),
            "high_risk": len(high_risk),
            "warnings": len(warnings),
        }
        failure_phase = "candidate.contract" if fatal_contract else "candidate.preview"
        failure_context = build_slide_failure_context(
            phase=failure_phase,
            slide_js_path=candidate_path,
            candidate_js=js_code,
            issues=all_issues,
            diagnostics=diagnostics,
        )

    return CandidateQualityReviewResult(
        preview_mode=preview_mode,
        preview_text=preview_text,
        preview_issues=preview_issues,
        preview_diag=preview_diag,
        all_issues=all_issues,
        compile_ok=compile_ok,
        blocking=blocking,
        high_risk=high_risk,
        warnings=warnings,
        needs_repair=needs_repair,
        degraded_notes=degraded_notes,
        quality_score=quality_score,
        repair_directives=repair_directives,
        failure_phase=failure_phase,
        failure_context=failure_context,
    )
