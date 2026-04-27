from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..design.skill_profile import DesignProfile
from ..models import EventType, OutlineNode, SlideArtifact
from .types import SlideGenerationError


async def generate_legacy_skill_slide(
    orch: Any,
    *,
    run_id: str,
    slide_no: int,
    node: OutlineNode,
    design: DesignProfile,
) -> SlideArtifact:
    run = await orch.store.get_run(run_id)
    assert run is not None
    effective_template_style = orch._resolved_template_style(run)
    artifact_dir = Path(run.artifact_dir)
    slides_dir = artifact_dir / "slides"
    retries = 0
    while True:
        try:
            generated = await orch._call_llm_with_timeout_retry(
                run_id=run_id,
                phase=f"slide.{slide_no}.legacy.generate",
                action=lambda: orch.llm_client.generate_slide(
                    topic=run.input.topic,
                    project_id=run.input.project_id,
                    template_style=effective_template_style,
                    slide_no=slide_no,
                    target_slide_count=run.input.target_slide_count,
                    outline_node=node,
                    rag_source_ids=run.input.rag_source_ids,
                ),
            )
            rule_violations = orch.quality_engine.check_slide_content_rules(generated, node)
            reviewed = await orch._call_llm_with_timeout_retry(
                run_id=run_id,
                phase=f"slide.{slide_no}.legacy.review",
                action=lambda: orch.llm_client.review_slide(
                    topic=run.input.topic,
                    template_style=effective_template_style,
                    slide_no=slide_no,
                    target_slide_count=run.input.target_slide_count,
                    outline_node=node,
                    candidate=generated,
                    rule_violations=rule_violations,
                ),
            )
            await orch._publish(run_id, EventType.SLIDE_REVIEWED, {"slide_no": slide_no, "violations": rule_violations})
            citations = orch._normalize_citations(reviewed.citations, run.input.rag_source_ids, slide_no)
            chart_plan = orch._build_chart_plan_from_bullets(
                node=OutlineNode(
                    title=reviewed.title,
                    bullets=list(reviewed.bullets),
                    page_type=node.page_type,
                    layout_hint=reviewed.layout_hint or node.layout_hint,
                ),
                source_refs=citations,
            )
            js_code = orch._render_skill_slide_js(
                slide_no=slide_no,
                total=run.input.target_slide_count,
                node=node,
                generated=reviewed,
                design=design,
                chart_plan=chart_plan,
            )
            slide_path = slides_dir / f"slide-{slide_no:02d}.js"
            slide_path.write_text(js_code, encoding="utf-8")
            await orch._append_chart_truth_report(
                run_id=run_id,
                entry={
                    "slide_no": slide_no,
                    "has_verified_data": chart_plan.has_verified_data,
                    "mode": chart_plan.mode,
                    "source": chart_plan.source,
                    "note": chart_plan.note,
                    "labels": chart_plan.labels,
                },
            )
            await orch._publish(
                run_id,
                EventType.CHART_TRUTH_CHECKED,
                {
                    "slide_no": slide_no,
                    "has_verified_data": chart_plan.has_verified_data,
                    "mode": chart_plan.mode,
                    "source": chart_plan.source,
                },
            )
            status = "ok" if retries == 0 else f"ok_after_retry_{retries}"
            return SlideArtifact(
                slide_no=slide_no,
                js_path=str(slide_path),
                js_code=js_code,
                status=status,
                citations=citations,
            )
        except Exception as exc:
            retries += 1
            if retries >= orch.slide_retry:
                raise SlideGenerationError(
                    slide_no=slide_no,
                    phase="slide.content.generate",
                    reason=orch._exception_reason(exc),
                    details={"error_type": type(exc).__name__, "retries": retries},
                ) from exc
            await asyncio.sleep(0.05 * retries)
