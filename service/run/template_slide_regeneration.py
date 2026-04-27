from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..models import EventType, OutlineNode, RunRecord, RunStatus


async def regenerate_single_template_slide(
    *,
    orchestrator: Any,
    run_id: str,
    slide_no: int,
    instruction: str,
    preserve_style: bool,
    run: RunRecord,
    rule_violations: list[str],
) -> None:
    artifact_dir = Path(run.artifact_dir)
    _, _, _, unpacked, edited, template_slides_dir, template_compile_js, _ = (
        orchestrator.template_engine.template_work_paths(artifact_dir)
    )
    if not unpacked.exists():
        raise FileNotFoundError("template working directory missing")
    slide_files = orchestrator._rebuild_template_structure(
        unpacked=unpacked,
        target_count=len(run.outline.nodes),
    )
    if slide_no > len(slide_files):
        raise ValueError("template slide xml missing")

    design = orchestrator._resolve_run_design(run)
    node = run.outline.nodes[slide_no - 1]
    slide = next(
        item for item in run.slides if int(getattr(item, "slide_no", 0) or 0) == slide_no
    )
    citations = orchestrator._normalize_citations(slide.citations, run.input.rag_source_ids, slide_no)
    candidate = orchestrator.template_engine.extract_candidate_from_template_slide(
        unpacked=unpacked,
        slide_xml=slide_files[slide_no - 1],
        fallback_node=node,
        citations=citations,
    )
    reviewed = await orchestrator._call_llm_with_timeout_retry(
        run_id=run_id,
        phase=f"template.slide.{slide_no}.regenerate.review",
        action=lambda: orchestrator.llm_client.review_slide(
            topic=run.input.topic,
            template_style=orchestrator._resolved_template_style(run),
            slide_no=slide_no,
            target_slide_count=run.input.target_slide_count,
            outline_node=node,
            candidate=candidate,
            rule_violations=rule_violations,
        ),
    )
    updated_node = OutlineNode(
        title=reviewed.title,
        bullets=list(reviewed.bullets),
        page_type=node.page_type,
        layout_hint=reviewed.layout_hint or node.layout_hint,
    )

    def apply_outline_update(r: RunRecord) -> None:
        r.status = RunStatus.COMPILING
        r.outline.nodes[slide_no - 1] = updated_node

    await orchestrator.store.update_run(run_id, apply_outline_update)
    artifacts = await orchestrator.template_engine.apply_template_nodes_once(
        run_id=run_id,
        unpacked=unpacked,
        design=design,
        use_review=False,
        forced_issues=None,
    )
    if not artifacts:
        raise RuntimeError("template slide regeneration did not produce artifacts")
    orchestrator.template_engine.pack_template_unpacked(unpacked=unpacked, edited=edited)
    compile_start = time.perf_counter()
    compiled = await orchestrator.template_engine.compile_template_js(
        template_slides_dir=template_slides_dir
    )
    if not compiled:
        raise RuntimeError("template slide regenerate compile failed")
    artifact = next(
        item for item in artifacts if int(getattr(item, "slide_no", 0) or 0) == slide_no
    )
    preview = await orchestrator.render_slide_preview_or_fallback(
        run_id=run_id,
        slide_no=slide_no,
        slide_js_path=Path(str(artifact.js_path or "")),
        theme=design.theme,
    )

    def apply_compile(r: RunRecord) -> None:
        r.compile_js_path = str(template_compile_js)
        r.pptx_path = str(edited)
        r.stage_timings.compile_ms = int((time.perf_counter() - compile_start) * 1000)
        r.citation_map = {item.slide_no: list(item.citations) for item in artifacts}
        r.slides = artifacts
        r.status = RunStatus.SUCCEEDED
        r.render_version += 1

    await orchestrator.store.update_run(run_id, apply_compile)
    await orchestrator.slide_regeneration_service.publish_slide_generated_preview(
        run_id=run_id,
        slide_no=slide_no,
        status=str(getattr(artifact, "status", "ok") or "ok"),
        preview=preview,
    )
    await orchestrator._publish(
        run_id,
        EventType.COMPILE_COMPLETED,
        {
            "file": str(edited),
            "mode": "template-regenerate",
            "compile_js": str(template_compile_js),
            "reason": "single_slide_regenerate",
        },
    )
