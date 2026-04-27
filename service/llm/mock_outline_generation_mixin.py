from __future__ import annotations

from typing import Any

from ..design.skill_profile import enforce_layout_variety
from ..design.style_catalog import resolve_style_dna_choice
from ..models import OutlineDocument, OutlineNode, SlidePageType
from .types import TokenCallback


class MockOutlineGenerationMixin:
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
