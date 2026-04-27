from __future__ import annotations

from ..design.skill_profile import DesignProfile, allowed_layouts_for
from ..design.style_catalog import get_style_dna_by_id
from ..models import OutlineNode, SlidePageType, VisualPolicy


def build_slide_plan(
    *,
    node: OutlineNode,
    design: DesignProfile,
    slide_no: int,
    style_dna_id: str | None = None,
) -> dict[str, Any]:
    allowed = allowed_layouts_for(node.page_type, style_dna_id=style_dna_id)
    layout = (
        node.layout_hint
        if node.layout_hint in allowed
        else (allowed[0] if allowed else (node.layout_hint or "content-two-column"))
    )
    style_dna = get_style_dna_by_id(style_dna_id)
    density_profile = str(
        style_dna.density_profile if style_dna is not None else "balanced"
    ).strip().lower()
    if density_profile == "dense":
        min_margin_in = 0.42 if node.page_type == SlidePageType.CONTENT else 0.32
        min_block_gap_in = 0.2 if node.page_type == SlidePageType.CONTENT else 0.16
        body_preferred_size = "13-15"
    elif density_profile == "airy":
        min_margin_in = 0.58 if node.page_type == SlidePageType.CONTENT else 0.4
        min_block_gap_in = 0.28 if node.page_type == SlidePageType.CONTENT else 0.2
        body_preferred_size = "15-17"
    else:
        min_margin_in = 0.5 if node.page_type == SlidePageType.CONTENT else 0.35
        min_block_gap_in = 0.22 if node.page_type == SlidePageType.CONTENT else 0.18
        body_preferred_size = "14-16"
    visual_kind = "shape_chart"
    if node.page_type == SlidePageType.CONTENT:
        if layout in {"content-showcase", "content-two-column"}:
            visual_kind = "image_or_showcase"
        elif layout == "content-stat-callout":
            visual_kind = "chart_callout"
        elif layout == "content-icon-rows":
            visual_kind = "icon_rows"
        elif layout in {"content-timeline", "content-comparison"}:
            visual_kind = "shape_flow"

    image_slots = (
        2
        if (
            node.page_type == SlidePageType.CONTENT
            and visual_kind in {"image_or_showcase", "icon_rows"}
        )
        else 0
    )
    return {
        "slide_no": slide_no,
        "page_type": node.page_type.value,
        "layout": layout,
        "visual_plan": {
            "kind": visual_kind,
            "must_have_badge": node.page_type != SlidePageType.COVER,
            "image_slots": image_slots,
            "chart_preferred": visual_kind in {"chart_callout"},
        },
        "constraints": {
            "min_margin_in": min_margin_in,
            "min_block_gap_in": min_block_gap_in,
            "body_align": "left",
            "title_min_size": 36,
            "body_preferred_size": body_preferred_size,
            "title_body_min_delta": 18,
            "must_use_shrink": True,
        },
        "design_tokens": {
            "palette": design.palette_name,
            "style": design.style.name,
            "title_font": design.title_font,
            "body_font": design.body_font,
            "style_dna_id": style_dna_id or "",
            "layout_family": str(style_dna.layout_family if style_dna is not None else ""),
            "density_profile": str(style_dna.density_profile if style_dna is not None else ""),
        },
        "content_blocks": {
            "title": node.title,
            "bullets_count": len(node.bullets),
        },
    }


def layout_supports_image(
    layout_hint: str | None, *, style_dna_id: str | None = None
) -> bool:
    layout = str(layout_hint or "").strip()
    if not layout:
        return False
    if layout not in {
        "content-two-column",
        "content-showcase",
        "content-icon-rows",
    }:
        return False
    allowed_content = set(
        allowed_layouts_for(SlidePageType.CONTENT, style_dna_id=style_dna_id)
    )
    if allowed_content:
        return layout in allowed_content
    return True


def apply_visual_policy_to_slide_plan(
    *,
    slide_plan: dict[str, Any],
    page_type: SlidePageType,
    visual_policy: VisualPolicy,
) -> None:
    if page_type != SlidePageType.CONTENT:
        return
    visual_plan = slide_plan.get("visual_plan")
    if not isinstance(visual_plan, dict):
        visual_plan = {}
        slide_plan["visual_plan"] = visual_plan
    if visual_policy == VisualPolicy.MEDIA_REQUIRED:
        layout = str(slide_plan.get("layout", "")).strip()
        style_dna_id = ""
        tokens = slide_plan.get("design_tokens", {})
        if isinstance(tokens, dict):
            style_dna_id = str(tokens.get("style_dna_id", "")).strip()
        if not layout_supports_image(layout, style_dna_id=style_dna_id or None):
            allowed_content = allowed_layouts_for(
                SlidePageType.CONTENT, style_dna_id=style_dna_id or None
            )
            image_candidates = [
                item
                for item in allowed_content
                if layout_supports_image(item, style_dna_id=style_dna_id or None)
            ]
            slide_plan["layout"] = (
                image_candidates[0] if image_candidates else "content-showcase"
            )
        visual_plan["kind"] = "image_or_showcase"
        visual_plan["image_slots"] = max(1, int(visual_plan.get("image_slots", 0) or 0))
        visual_plan["chart_preferred"] = False
    elif visual_policy == VisualPolicy.BASIC_GRAPHICS_ONLY:
        visual_plan["image_slots"] = 0


def extract_slide_plan_assets(slide_plan: dict[str, Any]) -> list[dict[str, Any]]:
    visual_plan = slide_plan.get("visual_plan")
    if not isinstance(visual_plan, dict):
        return []
    assets = visual_plan.get("assets", [])
    if not isinstance(assets, list):
        return []
    out: list[dict[str, Any]] = []
    for item in assets:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).strip()
        if not path:
            continue
        out.append(
            {
                "path": path,
                "slot": str(item.get("slot", "")).strip(),
                "type": str(item.get("type", "")).strip(),
            }
        )
    return out
