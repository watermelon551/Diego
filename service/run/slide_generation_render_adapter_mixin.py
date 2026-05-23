from __future__ import annotations

from typing import Any

from ..design.skill_profile import DesignProfile, StyleRecipe
from ..llm import GeneratedSlide
from ..models import OutlineNode, SlidePageType
from ..slides.skill_slide_blocks import (
    slide_block_content,
    slide_block_cover,
    slide_block_section,
    slide_block_summary,
    slide_block_toc,
    slide_content_block,
)
from ..slides.skill_slide_renderer import (
    build_compile_script,
    build_page_badge_js,
    render_skill_slide_js,
    theme_js_literal,
)
from .types import ChartPlan


class SlideGenerationRenderAdapterMixin:
    def _render_skill_slide_js(
        self,
        *,
        slide_no: int,
        total: int,
        node: OutlineNode,
        generated: GeneratedSlide,
        design: DesignProfile,
        chart_plan: ChartPlan,
        visual_kind: str | None = None,
        visual_assets: list[dict[str, Any]] | None = None,
        outline_nodes: list[OutlineNode] | None = None,
    ) -> str:
        return render_skill_slide_js(
            slide_no=slide_no,
            total=total,
            node=node,
            generated=generated,
            design=design,
            chart_plan=chart_plan,
            visual_kind=visual_kind,
            visual_assets=visual_assets,
            outline_nodes=outline_nodes,
        )

    def _slide_content_block(
        self,
        *,
        page_type: SlidePageType,
        layout_hint: str,
        style: StyleRecipe,
        visual_kind: str = "shape",
    ) -> str:
        return slide_content_block(
            page_type=page_type,
            layout_hint=layout_hint,
            style=style,
            visual_kind=visual_kind,
        )

    def _build_page_badge_js(self, *, slide_no: int, style: StyleRecipe) -> str:
        return build_page_badge_js(slide_no=slide_no, style=style)

    def _build_compile_script(self, *, total: int, theme: dict[str, str]) -> str:
        return build_compile_script(total=total, theme=theme)

    def _theme_js_literal(self, theme: dict[str, str]) -> str:
        return theme_js_literal(theme)

    def _slide_block_cover(self, layout_hint: str) -> str:
        return slide_block_cover(layout_hint)

    def _slide_block_toc(self, layout_hint: str) -> str:
        return slide_block_toc(layout_hint)

    def _slide_block_section(self, layout_hint: str) -> str:
        return slide_block_section(layout_hint)

    def _slide_block_content(
        self, layout_hint: str, *, visual_kind: str = "shape"
    ) -> str:
        return slide_block_content(layout_hint, visual_kind=visual_kind)

    def _slide_block_summary(self, layout_hint: str) -> str:
        return slide_block_summary(layout_hint)
