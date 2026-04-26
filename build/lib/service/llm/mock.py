from __future__ import annotations

import json
from typing import Any

from ..models import (
    ContentBlock,
    LongFormDraftSection,
    LongFormPlan,
    LongFormPlanSection,
    OutlineDocument,
    OutlineNode,
    SlidePageType,
    VisualPolicy,
)
from ..design.skill_profile import enforce_layout_variety
from ..design.style_catalog import resolve_style_dna_choice
from .types import GeneratedSlide, SlideSpec, TokenCallback

class MockLLMClient:
    async def generate_research_brief(
        self,
        *,
        topic: str,
        project_id: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, Any]],
        template_style: str,
        target_slide_count: int,
    ) -> dict[str, Any]:
        return {
            "audience": "general",
            "purpose": "explain topic clearly",
            "tone": "professional",
            "narrative_arc": "context -> core points -> implications -> summary",
            "page_focus": [f"Slide {idx}: focus on key point {idx}" for idx in range(1, target_slide_count + 1)],
            "design_notes": [
                f"Prefer {template_style} style.",
                "Maintain strong hierarchy and spacing.",
                "Use non-text visual on content slides.",
            ],
        }

    async def generate_design_intent(
        self,
        *,
        topic: str,
        template_style: str,
        target_slide_count: int,
        research_brief: dict[str, Any],
    ) -> dict[str, Any]:
        style = template_style.strip().lower()
        if "brutal" in style:
            return {
                "palette_name": "Platinum White Gold",
                "style_recipe": "sharp",
                "title_font": "Arial Black",
                "body_font": "Arial",
                "visual_strategy": "bold geometric contrast",
                "density": "medium",
                "rationale": "high-contrast, blocky composition for brutalist tone",
            }
        return {
            "palette_name": "Pure Tech Blue",
            "style_recipe": "soft",
            "title_font": "Cambria",
            "body_font": "Calibri",
            "visual_strategy": "balanced text and visual anchors",
            "density": "medium",
            "rationale": "stable default design intent for deterministic tests",
        }

    async def generate_longform_research_brief(
        self,
        *,
        topic: str,
        project_id: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, Any]],
        audience: str,
        purpose: str,
        tone: str,
        target_section_count: int,
    ) -> dict[str, Any]:
        return {
            "audience": audience,
            "purpose": purpose,
            "tone": tone,
            "narrative_arc": "context -> key ideas -> evidence -> synthesis",
            "section_focus": [
                f"Section {idx}: focus on {topic} theme {idx}"
                for idx in range(1, target_section_count + 1)
            ],
            "source_themes": [
                str(item.get("excerpt") or item.get("text", "")).strip()[:120]
                for item in rag_context_snippets[: min(3, len(rag_context_snippets))]
                if str(item.get("excerpt") or item.get("text", "")).strip()
            ],
        }
    async def generate_outline(
        self,
        *,
        topic: str,
        project_id: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, Any]],
        template_style: str,
        target_slide_count: int,
        on_token: TokenCallback,
    ) -> OutlineDocument:
        for token in ["生成", "大纲", "中", "...", topic]:
            await on_token(token)
        nodes: list[OutlineNode] = []
        for i in range(1, target_slide_count + 1):
            nodes.append(
                OutlineNode(
                    title=f"{topic} - Section {i}",
                    bullets=[f"Point {i}.1", f"Point {i}.2"],
                    page_type=self._page_type_for_index(i, target_slide_count),
                    layout_hint="content-two-column" if i % 2 == 0 else "content-icon-rows",
                )
            )
        style_dna = resolve_style_dna_choice("auto", template_style=template_style, seed=f"{topic}|mock")
        enforce_layout_variety(nodes=nodes, seed=f"{topic}|mock", style_dna_id=style_dna.id)
        return OutlineDocument(version=1, summary=f"Auto outline for {topic}", nodes=nodes)

    async def repair_outline(
        self,
        *,
        topic: str,
        project_id: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, Any]],
        template_style: str,
        target_slide_count: int,
        previous_response: str,
        error_category: str,
        error_details: list[str],
    ) -> OutlineDocument:
        async def noop(_: str) -> None:
            return

        return await self.generate_outline(
            topic=topic,
            project_id=project_id,
            rag_source_ids=rag_source_ids,
            rag_context_snippets=rag_context_snippets,
            template_style=template_style,
            target_slide_count=target_slide_count,
            on_token=noop,
        )

    async def critique_outline(
        self,
        *,
        topic: str,
        template_style: str,
        target_slide_count: int,
        outline: OutlineDocument,
    ) -> OutlineDocument:
        return outline

    async def generate_longform_plan(
        self,
        *,
        topic: str,
        project_id: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, Any]],
        audience: str,
        purpose: str,
        tone: str,
        target_section_count: int,
        on_token: TokenCallback,
    ) -> LongFormPlan:
        for token in ["planning", "content", topic]:
            await on_token(token + " ")
        source_refs = [
            str(item.get("chunk_id") or item.get("source_id") or f"src-{idx}")
            for idx, item in enumerate(rag_context_snippets[:2], start=1)
        ]
        sections = [
            LongFormPlanSection(
                section_id=f"section-{idx}",
                title=f"{topic} - Section {idx}",
                summary=f"Explain the {idx}th aspect of {topic}.",
                key_points=[f"{topic} point {idx}.1", f"{topic} point {idx}.2"],
                intent=f"clarify theme {idx} for {audience}",
                source_refs=list(source_refs),
            )
            for idx in range(1, target_section_count + 1)
        ]
        return LongFormPlan(
            version=1,
            title=topic,
            summary=f"Structured draft plan for {topic}",
            sections=sections,
        )

    async def repair_longform_plan(
        self,
        *,
        topic: str,
        project_id: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, Any]],
        audience: str,
        purpose: str,
        tone: str,
        target_section_count: int,
        previous_response: str,
        error_category: str,
        error_details: list[str],
    ) -> LongFormPlan:
        async def noop(_: str) -> None:
            return

        return await self.generate_longform_plan(
            topic=topic,
            project_id=project_id,
            rag_source_ids=rag_source_ids,
            rag_context_snippets=rag_context_snippets,
            audience=audience,
            purpose=purpose,
            tone=tone,
            target_section_count=target_section_count,
            on_token=noop,
        )

    async def critique_longform_plan(
        self,
        *,
        topic: str,
        audience: str,
        purpose: str,
        tone: str,
        target_section_count: int,
        plan: LongFormPlan,
    ) -> LongFormPlan:
        return plan

    async def generate_section_draft(
        self,
        *,
        topic: str,
        project_id: str,
        audience: str,
        purpose: str,
        tone: str,
        plan: LongFormPlan,
        section_id: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, Any]],
    ) -> LongFormDraftSection:
        section = next(item for item in plan.sections if item.section_id == section_id)
        citations = list(section.source_refs or rag_source_ids[:2])
        return LongFormDraftSection(
            section_id=section.section_id,
            heading=section.title,
            blocks=[
                ContentBlock(kind="heading", text=section.title),
                ContentBlock(
                    kind="paragraph",
                    text=f"This section explains {section.summary or section.title} for {audience}.",
                ),
                ContentBlock(kind="bullet_list", items=list(section.key_points or [section.title])),
            ],
            citations=citations,
            revision=1,
        )

    async def revise_section_draft(
        self,
        *,
        topic: str,
        project_id: str,
        audience: str,
        purpose: str,
        tone: str,
        plan: LongFormPlan,
        current_section: LongFormDraftSection,
        instruction: str,
        preserve_structure: bool,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, Any]],
    ) -> LongFormDraftSection:
        blocks = list(current_section.blocks)
        if preserve_structure:
            rewritten: list[ContentBlock] = []
            for block in blocks:
                if block.kind == "paragraph":
                    rewritten.append(
                        ContentBlock(
                            kind="paragraph",
                            text=f"{block.text} Revision focus: {instruction.strip()}",
                        )
                    )
                else:
                    rewritten.append(block)
            blocks = rewritten
        else:
            blocks = [
                ContentBlock(kind="heading", text=current_section.heading),
                ContentBlock(
                    kind="paragraph",
                    text=f"{current_section.heading} rewritten with instruction: {instruction.strip()}",
                ),
            ]
        return LongFormDraftSection(
            section_id=current_section.section_id,
            heading=current_section.heading,
            blocks=blocks,
            citations=list(current_section.citations or rag_source_ids[:2]),
            revision=current_section.revision + 1,
        )

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

    async def generate_slide_spec(
        self,
        *,
        topic: str,
        template_style: str,
        slide_no: int,
        target_slide_count: int,
        outline_node: OutlineNode,
        rag_source_ids: list[str],
        visual_policy: VisualPolicy = VisualPolicy.AUTO,
        slide_plan: dict[str, Any] | None = None,
        slide_brief: dict[str, Any] | None = None,
    ) -> SlideSpec:
        visual_kind = "shape"
        if outline_node.page_type == SlidePageType.CONTENT:
            visual_kind = "image" if visual_policy == VisualPolicy.MEDIA_REQUIRED else "chart"
        return SlideSpec(
            title=outline_node.title,
            subtitle="",
            bullets=list(outline_node.bullets or [f"Point {slide_no}.1", f"Point {slide_no}.2"]),
            page_type=outline_node.page_type,
            layout_hint=outline_node.layout_hint,
            visual_kind=visual_kind,
            emphasis="",
            citations=list(rag_source_ids[:2]),
        )

    async def repair_slide_spec(
        self,
        *,
        topic: str,
        template_style: str,
        slide_no: int,
        target_slide_count: int,
        outline_node: OutlineNode,
        previous_spec: SlideSpec,
        issues: list[str],
        repair_directives: list[str] | None = None,
        visual_policy: VisualPolicy = VisualPolicy.AUTO,
        slide_plan: dict[str, Any] | None = None,
        slide_brief: dict[str, Any] | None = None,
    ) -> SlideSpec:
        fixed = SlideSpec(
            title=previous_spec.title or outline_node.title,
            subtitle=previous_spec.subtitle,
            bullets=list(previous_spec.bullets or outline_node.bullets),
            page_type=outline_node.page_type,
            layout_hint=outline_node.layout_hint or previous_spec.layout_hint,
            visual_kind=previous_spec.visual_kind or "shape",
            emphasis=previous_spec.emphasis,
            citations=list(previous_spec.citations),
        )
        if len(fixed.bullets) < 2:
            fixed.bullets = list(outline_node.bullets or [f"Point {slide_no}.1", f"Point {slide_no}.2"])
        return fixed

    def _page_type_for_index(self, index: int, total: int) -> SlidePageType:
        if index == 1:
            return SlidePageType.COVER
        if index == 2:
            return SlidePageType.TOC
        if index == total:
            return SlidePageType.SUMMARY
        if index % 4 == 0:
            return SlidePageType.SECTION
        return SlidePageType.CONTENT
