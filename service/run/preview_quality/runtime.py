from __future__ import annotations

from pathlib import Path
from typing import Any

from ...models import EventType, GenerationMode
from .mode_execution import run_scratch_qa, run_template_qa
from .reporting import build_qa_report, resolve_qa_history


async def run_skill_qa(orch: Any, run_id: str, *, mode: GenerationMode) -> bool:
    run = await orch.store.get_run(run_id)
    assert run is not None
    artifact_dir = Path(run.artifact_dir)
    issues: list[str] = []
    previous_report = run.qa_report if isinstance(run.qa_report, dict) else {}
    verification_cycles, preview_cache_in = resolve_qa_history(previous_report=previous_report)
    if mode == GenerationMode.SCRATCH:
        mode_result = await run_scratch_qa(
            run_id=run_id,
            slides_dir=artifact_dir / "slides",
            pptx_path=run.pptx_path,
            verification_cycles=verification_cycles,
            preview_cache_in=preview_cache_in,
            visual_policy=run.input.visual_policy,
            run_slide_preview_qa=orch._run_slide_preview_qa,
            markitdown_check=orch._markitdown_check,
            has_valid_page_badge=lambda raw_js, raw_slide_no: orch._has_valid_page_badge(
                js_code=raw_js,
                slide_no=raw_slide_no,
            ),
            extract_method_call_args=lambda payload, method_expr: orch._extract_method_call_args(
                payload,
                method_expr=method_expr,
            ),
            dedupe_preserve_order=orch._dedupe_preserve_order,
        )
    else:
        mode_result = await run_template_qa(
            run_id=run_id,
            slides=run.slides,
            pptx_path=run.pptx_path,
            run_slide_preview_qa=orch._run_slide_preview_qa,
            markitdown_check=orch._markitdown_check,
        )

    issues.extend(mode_result.issues)
    deduped_issues = orch._dedupe_preserve_order([str(item) for item in issues if str(item).strip()])
    report = build_qa_report(
        deduped_issues=deduped_issues,
        verification_cycles=verification_cycles,
        preview_cache_out=mode_result.preview_cache_out,
        split_qa_issues_by_slide=orch._split_qa_issues_by_slide,
    )
    await orch.store.update_run(run_id, lambda r: setattr(r, "qa_report", report))
    await orch._publish(run_id, EventType.QA_COMPLETED, report)
    return not deduped_issues
