from __future__ import annotations

from ....models import OutlineNode


class SlideRegenerationReviewedScratchMixin:
    async def _regenerate_reviewed_scratch_slide(
        self,
        *,
        run_id: str,
        slide_no: int,
        run,
        node: OutlineNode,
        slide,
        design,
        effective_template_style: str,
        rule_violations: list[str],
    ):
        orch = self.orch
        candidate = orch.quality_engine.extract_candidate_from_js(
            js_code=slide.js_code,
            fallback_node=node,
            citations=slide.citations,
        )
        reviewed = await orch._call_llm_with_timeout_retry(
            run_id=run_id,
            phase=f"slide.{slide_no}.regenerate.review",
            action=lambda: orch.llm_client.review_slide(
                topic=run.input.topic,
                template_style=effective_template_style,
                slide_no=slide_no,
                target_slide_count=run.input.target_slide_count,
                outline_node=node,
                candidate=candidate,
                rule_violations=rule_violations,
            ),
        )
        js_code = orch._render_skill_slide_js(
            slide_no=slide_no,
            total=run.input.target_slide_count,
            node=node,
            generated=reviewed,
            design=design,
            chart_plan=orch._build_chart_plan_from_bullets(
                node=OutlineNode(
                    title=reviewed.title,
                    bullets=list(reviewed.bullets),
                    page_type=node.page_type,
                    layout_hint=reviewed.layout_hint or node.layout_hint,
                ),
                source_refs=slide.citations,
            ),
            outline_nodes=list(run.outline.nodes) if run.outline is not None else [],
        )
        return reviewed, js_code
