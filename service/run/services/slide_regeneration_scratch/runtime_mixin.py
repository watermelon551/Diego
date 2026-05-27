from __future__ import annotations

from pathlib import Path

from ....models import OutlineNode, RunRecord, SlideArtifact
from ...slide_regeneration_reporting import build_regeneration_rule_violations


class SlideRegenerationScratchRuntimeMixin:
    async def regenerate_single_scratch_slide(
        self,
        *,
        run_id: str,
        slide_no: int,
        instruction: str,
        preserve_style: bool,
        run: RunRecord,
    ) -> None:
        orch = self.orch
        design = orch._resolve_run_design(run)
        effective_template_style = orch._resolved_template_style(run)
        node = run.outline.nodes[slide_no - 1]
        slide = next(
            item
            for item in run.slides
            if int(getattr(item, "slide_no", 0) or 0) == slide_no
        )
        slide_path = self._require_slide_js_artifact(slide)
        rule_violations = build_regeneration_rule_violations(
            instruction=instruction,
            preserve_style=preserve_style,
        )
        reviewed, js_code = await self._regenerate_agentic_scratch_slide(
            run_id=run_id,
            slide_no=slide_no,
            run=run,
            node=node,
            slide=slide,
            effective_template_style=effective_template_style,
            rule_violations=rule_violations,
        )
        citations = orch._normalize_citations(
            reviewed.citations, run.input.rag_source_ids, slide_no
        )
        updated_node = OutlineNode(
            title=reviewed.title,
            bullets=list(reviewed.bullets),
            page_type=node.page_type,
            layout_hint=reviewed.layout_hint or node.layout_hint,
        )
        chart_plan = orch._build_chart_plan_from_bullets(
            node=updated_node,
            source_refs=citations,
        )
        slide_path.write_text(js_code, encoding="utf-8")
        artifact = SlideArtifact(
            slide_no=slide_no,
            js_path=str(slide_path),
            js_code=js_code,
            status="ok",
            citations=citations,
        )
        preview = await orch.render_slide_preview_or_fallback(
            run_id=run_id,
            slide_no=slide_no,
            slide_js_path=slide_path,
            theme=design.theme,
        )
        await self._finalize_scratch_regenerated_slide(
            run_id=run_id,
            run=run,
            slide_no=slide_no,
            updated_node=updated_node,
            artifact=artifact,
            citations=citations,
            chart_plan=chart_plan,
            preview=preview,
            design=design,
        )

    def _require_slide_js_artifact(self, slide: SlideArtifact) -> Path:
        slide_path = Path(str(getattr(slide, "js_path", "") or "").strip())
        if not str(slide_path):
            raise FileNotFoundError("slide js artifact missing")
        if not slide_path.exists():
            inline_js = str(getattr(slide, "js_code", "") or "")
            if inline_js.strip():
                slide_path.parent.mkdir(parents=True, exist_ok=True)
                slide_path.write_text(inline_js, encoding="utf-8")
        if not slide_path.exists() or not slide_path.is_file():
            raise FileNotFoundError("slide js artifact missing")
        return slide_path
