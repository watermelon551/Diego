from __future__ import annotations

from typing import Any

from ..design.skill_profile import DesignProfile
from ..llm import GeneratedSlide, SlideSpec
from ..models import OutlineNode, RunRecord, SlidePageType, VisualPolicy
from .slide_generation_briefs import (
    build_slide_brief,
    candidate_variant_specs,
    fallback_research_brief,
    generated_from_slide_spec,
    slide_spec_from_generated,
)
from .slide_plan_rules import (
    apply_visual_policy_to_slide_plan,
    build_slide_plan,
    extract_slide_plan_assets,
    layout_supports_image,
)
from .slide_spec_repair import (
    apply_local_spec_repairs,
    rotate_layout_hint,
    trim_spec_bullets,
)


class SlideGenerationPlanAdapterMixin:
    def _build_slide_plan(
        self,
        *,
        node: OutlineNode,
        design: DesignProfile,
        slide_no: int,
        style_dna_id: str | None = None,
    ) -> dict[str, Any]:
        return build_slide_plan(
            node=node,
            design=design,
            slide_no=slide_no,
            style_dna_id=style_dna_id,
        )

    def _layout_supports_image(
        self, layout_hint: str | None, *, style_dna_id: str | None = None
    ) -> bool:
        return layout_supports_image(layout_hint, style_dna_id=style_dna_id)

    def _apply_visual_policy_to_slide_plan(
        self,
        *,
        slide_plan: dict[str, Any],
        page_type: SlidePageType,
        visual_policy: VisualPolicy,
    ) -> None:
        apply_visual_policy_to_slide_plan(
            slide_plan=slide_plan,
            page_type=page_type,
            visual_policy=visual_policy,
        )

    def _extract_slide_plan_assets(
        self, slide_plan: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return extract_slide_plan_assets(slide_plan)

    def _apply_local_spec_repairs(
        self,
        *,
        spec: SlideSpec,
        node: OutlineNode,
        repair_round: int,
        issues: list[str],
        visual_policy: VisualPolicy,
    ) -> SlideSpec:
        return apply_local_spec_repairs(
            spec=spec,
            node=node,
            repair_round=repair_round,
            issues=issues,
            visual_policy=visual_policy,
        )

    def _rotate_layout_hint(
        self,
        *,
        layout_hint: str | None,
        page_type: SlidePageType,
        repair_round: int,
        prefer_image_layout: bool,
        style_dna_id: str | None = None,
    ) -> str | None:
        return rotate_layout_hint(
            layout_hint=layout_hint,
            page_type=page_type,
            repair_round=repair_round,
            prefer_image_layout=prefer_image_layout,
            style_dna_id=style_dna_id,
        )

    def _trim_spec_bullets(
        self, *, bullets: list[str], page_type: SlidePageType
    ) -> list[str]:
        return trim_spec_bullets(bullets=bullets, page_type=page_type)

    def _build_slide_brief(
        self,
        *,
        run: RunRecord,
        node: OutlineNode,
        slide_no: int,
        slide_plan: dict[str, Any],
    ) -> dict[str, Any]:
        return build_slide_brief(
            run=run,
            node=node,
            slide_no=slide_no,
            slide_plan=slide_plan,
        )

    def _candidate_variant_specs(
        self,
        *,
        slide_no: int,
        round_no: int,
        worker_count: int,
        layout: str,
    ) -> list[dict[str, Any]]:
        return candidate_variant_specs(
            slide_no=slide_no,
            round_no=round_no,
            worker_count=worker_count,
            layout=layout,
        )

    def _fallback_research_brief(
        self, *, topic: str, template_style: str, target_slide_count: int
    ) -> dict[str, Any]:
        return fallback_research_brief(
            topic=topic,
            template_style=template_style,
            target_slide_count=target_slide_count,
        )

    def _slide_spec_from_generated(
        self, *, generated: GeneratedSlide, node: OutlineNode
    ) -> SlideSpec:
        return slide_spec_from_generated(generated=generated, node=node)

    def _generated_from_slide_spec(
        self, *, spec: SlideSpec, node: OutlineNode
    ) -> GeneratedSlide:
        return generated_from_slide_spec(spec=spec, node=node)
