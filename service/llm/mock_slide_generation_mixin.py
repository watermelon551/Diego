from __future__ import annotations

import json
from typing import Any

from ..models import OutlineNode, VisualPolicy
from .types import GeneratedSlide


class MockSlideGenerationMixin:
    async def generate_slide(
        self,
        *,
        topic: str,
        project_id: str,
        template_style: str,
        slide_no: int,
        target_slide_count: int,
        outline_node: OutlineNode,
        rag_source_ids: list[str],
    ) -> GeneratedSlide:
        return GeneratedSlide(
            title=outline_node.title,
            bullets=outline_node.bullets or [f"Point {slide_no}.1", f"Point {slide_no}.2"],
            citations=rag_source_ids[:2],
            page_type=outline_node.page_type,
            layout_hint=outline_node.layout_hint,
        )

    async def review_slide(
        self,
        *,
        topic: str,
        template_style: str,
        slide_no: int,
        target_slide_count: int,
        outline_node: OutlineNode,
        candidate: GeneratedSlide,
        rule_violations: list[str],
    ) -> GeneratedSlide:
        if not candidate.bullets:
            candidate.bullets = [f"Point {slide_no}.1"]
        return candidate

    async def generate_slide_js(
        self,
        *,
        topic: str,
        template_style: str,
        slide_no: int,
        target_slide_count: int,
        outline_node: OutlineNode,
        theme: dict[str, str],
        title_font: str,
        body_font: str,
        rag_source_ids: list[str],
        visual_policy: VisualPolicy = VisualPolicy.AUTO,
        slide_plan: dict[str, Any] | None = None,
        slide_brief: dict[str, Any] | None = None,
    ) -> str:
        title = json.dumps(outline_node.title, ensure_ascii=False)
        bullets = json.dumps(outline_node.bullets or [f"Point {slide_no}.1", f"Point {slide_no}.2"], ensure_ascii=False)
        return "\n".join(
            [
                "const pptxgen = require('pptxgenjs');",
                "const slideConfig = {",
                f"  type: {json.dumps(outline_node.page_type.value)},",
                f"  index: {slide_no},",
                f"  total: {target_slide_count},",
                f"  title: {title},",
                f"  layoutHint: {json.dumps(outline_node.layout_hint or 'content-two-column')},",
                f"  bullets: {bullets},",
                "};",
                "function createSlide(pres, theme) {",
                "  const slide = pres.addSlide();",
                "  slide.background = { color: theme.bg };",
                f"  slide.addText(slideConfig.title, {{ x: 0.6, y: 0.4, w: 8.8, h: 0.7, fontSize: 34, fontFace: {json.dumps(title_font)}, color: theme.primary, bold: true, fit: 'shrink' }});",
                "  const rows = (slideConfig.bullets || []).map((text, idx) => ({ text, options: { bullet: true, breakLine: idx < (slideConfig.bullets || []).length - 1 } }));",
                f"  slide.addText(rows, {{ x: 0.9, y: 1.4, w: 8.0, h: 3.5, fontSize: 16, fontFace: {json.dumps(body_font)}, color: theme.secondary, margin: 0 }});",
                "  if (slideConfig.type !== 'cover') {",
                "    slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.accent }, line: { color: theme.accent } });",
                "    slide.addText(String(slideConfig.index), { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 10, color: 'FFFFFF', bold: true, align: 'center', valign: 'mid', margin: 0 });",
                "  }",
                "  return slide;",
                "}",
                "if (require.main === module) {",
                "  const pres = new pptxgen();",
                "  pres.layout = 'LAYOUT_16x9';",
                f"  const theme = {json.dumps(theme, ensure_ascii=False)};",
                "  createSlide(pres, theme);",
                f"  pres.writeFile({{ fileName: 'slide-{slide_no:02d}-preview.pptx' }});",
                "}",
                "module.exports = { createSlide, slideConfig };",
            ]
        )

    async def critique_slide_js(
        self,
        *,
        topic: str,
        template_style: str,
        slide_no: int,
        target_slide_count: int,
        outline_node: OutlineNode,
        candidate_js: str,
        issues: list[str],
        failure_context: dict[str, Any] | None = None,
        visual_policy: VisualPolicy = VisualPolicy.AUTO,
        slide_plan: dict[str, Any] | None = None,
        repair_directives: list[str] | None = None,
        preview_text: str = "",
        slide_brief: dict[str, Any] | None = None,
    ) -> str:
        return candidate_js

    async def evaluate_slide_quality(
        self,
        *,
        topic: str,
        template_style: str,
        slide_no: int,
        target_slide_count: int,
        outline_node: OutlineNode,
        candidate_js: str,
        preview_text: str,
        hard_issues: list[str],
        visual_policy: VisualPolicy = VisualPolicy.AUTO,
        slide_brief: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if hard_issues:
            return {
                "score": 60,
                "issues": list(hard_issues),
                "repair_directives": ["Fix all hard issues before polishing visual quality."],
            }
        return {"score": 90, "issues": [], "repair_directives": []}
