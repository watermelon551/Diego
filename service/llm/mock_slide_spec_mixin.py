from __future__ import annotations

from typing import Any

from ..models import OutlineNode, SlidePageType, VisualPolicy
from .types import SlideSpec


class MockSlideSpecMixin:
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
