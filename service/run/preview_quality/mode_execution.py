from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from ...models import SlideArtifact
from .sampling import PreviewCandidateRef
from .sampling import decide_preview_check, should_sample_unchanged_preview
from .reporting import (
    build_preview_cache_entry,
    merge_sampled_preview_cache_entry,
)
from .static_checks import evaluate_scratch_slide_static


@dataclass
class QaExecutionResult:
    issues: list[str] = field(default_factory=list)
    preview_cache_out: dict[str, Any] = field(default_factory=dict)


async def run_scratch_qa(
    *,
    run_id: str,
    slides_dir: Path,
    pptx_path: str | None,
    verification_cycles: int,
    preview_cache_in: dict[str, Any],
    visual_policy: Any,
    run_slide_preview_qa: Callable[..., Awaitable[list[str]]],
    markitdown_check: Callable[[Path], Awaitable[tuple[bool, str | None]]],
    has_valid_page_badge: Callable[[str, int], bool],
    extract_method_call_args: Callable[[str, str], list[list[str]]],
    dedupe_preserve_order: Callable[[list[str]], list[str]],
) -> QaExecutionResult:
    issues: list[str] = []
    preview_cache_out: dict[str, Any] = {}
    slide_files = sorted(
        [
            path
            for path in slides_dir.glob("slide-*.js")
            if path.name.startswith("slide-") and path.suffix == ".js" and len(path.stem) == 8
        ]
    )
    if not slide_files:
        issues.append("no slide js files generated")

    observed_layouts: list[str] = []
    unchanged_preview_candidates: list[PreviewCandidateRef] = []
    preview_runs = 0

    for idx, path in enumerate(slide_files, start=1):
        text = path.read_text(encoding="utf-8")
        static_eval = evaluate_scratch_slide_static(
            slide_js_path=path,
            slide_no=idx,
            text=text,
            visual_policy=visual_policy,
            preview_cache_in=preview_cache_in,
            has_valid_page_badge=has_valid_page_badge,
            extract_method_call_args=extract_method_call_args,
            dedupe_preserve_order=dedupe_preserve_order,
        )
        if static_eval.observed_layout:
            observed_layouts.append(static_eval.observed_layout)

        preview_checked = False
        preview_decision = decide_preview_check(
            verification_cycles=verification_cycles,
            has_static_issues=bool(static_eval.static_issues),
            slide_path=path,
            slide_no=idx,
            checksum=static_eval.checksum,
            unchanged_preview=static_eval.unchanged_preview,
            cached_preview_issues=static_eval.cached_preview_issues,
        )
        if preview_decision.should_preview:
            preview_issues = await run_slide_preview_qa(
                run_id=run_id,
                slide_js=path,
                slide_no=idx,
            )
            preview_checked = True
            preview_runs += 1
        else:
            if preview_decision.queued_candidate is not None:
                unchanged_preview_candidates.append(preview_decision.queued_candidate)
            preview_issues = list(preview_decision.preview_issues)

        all_slide_issues = static_eval.static_issues + preview_issues
        issues.extend(all_slide_issues)
        preview_cache_out[path.name] = build_preview_cache_entry(
            checksum=static_eval.checksum,
            issues=all_slide_issues if preview_checked else preview_issues,
            checked=preview_checked,
        )

    if should_sample_unchanged_preview(
        verification_cycles=verification_cycles,
        preview_runs=preview_runs,
        unchanged_preview_candidates=unchanged_preview_candidates,
    ):
        sample_ref = unchanged_preview_candidates[0]
        sample_issues = await run_slide_preview_qa(
            run_id=run_id,
            slide_js=sample_ref.path,
            slide_no=sample_ref.slide_no,
        )
        cached = preview_cache_out.get(sample_ref.path.name, {})
        prev_cached_issues = (
            [str(item) for item in cached.get("issues", [])]
            if isinstance(cached.get("issues", []), list)
            else []
        )
        if sample_issues:
            issues.extend(sample_issues)
        preview_cache_out[sample_ref.path.name] = merge_sampled_preview_cache_entry(
            checksum=sample_ref.checksum,
            cached_issues=prev_cached_issues,
            sample_issues=sample_issues,
        )

    for i in range(1, len(observed_layouts)):
        if observed_layouts[i] == observed_layouts[i - 1]:
            issues.append(f"adjacent layout repetition: {observed_layouts[i]}")
            break

    if pptx_path:
        markitdown_ok, extract_issue = await markitdown_check(Path(pptx_path))
        if not markitdown_ok and extract_issue:
            issues.append(extract_issue)
    else:
        issues.append("scratch mode output pptx missing")

    return QaExecutionResult(
        issues=issues,
        preview_cache_out=preview_cache_out,
    )


async def run_template_qa(
    *,
    run_id: str,
    slides: list[SlideArtifact],
    pptx_path: str | None,
    run_slide_preview_qa: Callable[..., Awaitable[list[str]]],
    markitdown_check: Callable[[Path], Awaitable[tuple[bool, str | None]]],
) -> QaExecutionResult:
    issues: list[str] = []
    template_slides = sorted(slides, key=lambda x: x.slide_no)
    if not template_slides:
        issues.append("template mode slide js artifacts missing")
    for artifact in template_slides:
        if not artifact.js_path:
            issues.append(f"slide-{artifact.slide_no:02d}: js_path missing")
            continue
        slide_js = Path(artifact.js_path)
        if not slide_js.exists():
            issues.append(f"slide-{artifact.slide_no:02d}: js file missing")
            continue
        issues.extend(
            await run_slide_preview_qa(
                run_id=run_id,
                slide_js=slide_js,
                slide_no=artifact.slide_no,
            )
        )

    if not pptx_path or not Path(pptx_path).exists():
        issues.append("template mode output pptx missing")
    else:
        markitdown_ok, extract_issue = await markitdown_check(Path(pptx_path))
        if not markitdown_ok and extract_issue:
            issues.append(extract_issue)

    return QaExecutionResult(
        issues=issues,
        preview_cache_out={},
    )
