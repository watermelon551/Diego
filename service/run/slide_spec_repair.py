from __future__ import annotations

import re

from ..design.skill_profile import allowed_layouts_for
from ..llm import SlideSpec
from ..models import OutlineNode, SlidePageType, VisualPolicy
from .slide_plan_rules import layout_supports_image


def apply_local_spec_repairs(
    *,
    spec: SlideSpec,
    node: OutlineNode,
    repair_round: int,
    issues: list[str],
    visual_policy: VisualPolicy,
) -> SlideSpec:
    page_type = spec.page_type or node.page_type
    repaired = SlideSpec(
        title=spec.title or node.title,
        subtitle=spec.subtitle,
        bullets=list(spec.bullets or node.bullets),
        page_type=page_type,
        layout_hint=spec.layout_hint or node.layout_hint,
        visual_kind=spec.visual_kind or "shape",
        emphasis=spec.emphasis,
        citations=list(spec.citations),
    )
    lowered_issues = [str(item).lower() for item in issues if str(item).strip()]
    has_geometry_issue = any(
        any(marker in item for marker in ("out of slide bounds", "overlaps box", "gap too tight", "margin too tight"))
        for item in lowered_issues
    )
    has_fit_issue = any(
        any(marker in item for marker in ("fit:'shrink'", "title/body size contrast", "title font too small"))
        for item in lowered_issues
    )
    has_visual_missing = any(
        any(marker in item for marker in ("visual_policy violation", "content slide missing non-text visual element"))
        for item in lowered_issues
    )

    if repaired.page_type == SlidePageType.CONTENT:
        if visual_policy == VisualPolicy.MEDIA_REQUIRED:
            repaired.visual_kind = "image"
            if not layout_supports_image(repaired.layout_hint):
                repaired.layout_hint = "content-showcase"
        elif visual_policy == VisualPolicy.BASIC_GRAPHICS_ONLY and repaired.visual_kind == "image":
            repaired.visual_kind = "chart"
        if has_visual_missing and repaired.visual_kind not in {"image", "chart"}:
            repaired.visual_kind = "chart"

    if has_geometry_issue:
        repaired.layout_hint = rotate_layout_hint(
            layout_hint=repaired.layout_hint,
            page_type=repaired.page_type,
            repair_round=repair_round,
            prefer_image_layout=(
                visual_policy == VisualPolicy.MEDIA_REQUIRED
                and repaired.page_type == SlidePageType.CONTENT
            ),
        )
    if has_fit_issue or has_geometry_issue:
        repaired.bullets = trim_spec_bullets(
            bullets=repaired.bullets,
            page_type=repaired.page_type,
        )
    return repaired


def rotate_layout_hint(
    *,
    layout_hint: str | None,
    page_type: SlidePageType,
    repair_round: int,
    prefer_image_layout: bool,
    style_dna_id: str | None = None,
) -> str | None:
    allowed = allowed_layouts_for(page_type, style_dna_id=style_dna_id)
    if not allowed:
        return layout_hint
    preferred = (
        [name for name in allowed if layout_supports_image(name, style_dna_id=style_dna_id)]
        if prefer_image_layout
        else []
    )
    if preferred:
        current = str(layout_hint or "").strip()
        if current in preferred:
            return preferred[(preferred.index(current) + repair_round) % len(preferred)]
        return preferred[(repair_round - 1) % len(preferred)]
    current = str(layout_hint or "").strip()
    if current in allowed:
        return allowed[(allowed.index(current) + repair_round) % len(allowed)]
    return allowed[(repair_round - 1) % len(allowed)]


def trim_spec_bullets(*, bullets: list[str], page_type: SlidePageType) -> list[str]:
    src = [str(item).strip() for item in bullets if str(item).strip()]
    if not src:
        return src
    max_items = 4 if page_type == SlidePageType.CONTENT else 3
    max_len = 90 if page_type == SlidePageType.CONTENT else 80
    out: list[str] = []
    for item in src[:max_items]:
        cleaned = re.sub(r"\s+", " ", item).strip()
        if len(cleaned) > max_len:
            cleaned = cleaned[: max_len - 3].rstrip(" ,;:.") + "..."
        out.append(cleaned)
    return out
