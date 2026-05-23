from __future__ import annotations

import json
from typing import Any

from ..design.skill_profile import DesignProfile, StyleRecipe
from ..llm import GeneratedSlide
from ..models import OutlineNode, SlidePageType
from ..run.types import ChartPlan
from .skill_slide_blocks import slide_content_block


def build_page_badge_js(*, slide_no: int, style: StyleRecipe) -> str:
    return f"  addPageBadge(pres, slide, theme, {slide_no});"


def theme_js_literal(theme: dict[str, str]) -> str:
    safe = {k: v.replace("#", "") for k, v in theme.items()}
    return (
        "{ "
        + ", ".join(
            f"{k}: '{safe[k]}'"
            for k in ("primary", "secondary", "accent", "light", "bg")
        )
        + " }"
    )


def build_compile_script(*, total: int, theme: dict[str, str]) -> str:
    return "\n".join(
        [
            "const pptxgen = require('pptxgenjs');",
            "const pres = new pptxgen();",
            "pres.layout = 'LAYOUT_16x9';",
            f"const theme = {theme_js_literal(theme)};",
            "",
            f"for (let i = 1; i <= {total}; i++) {{",
            "  const num = String(i).padStart(2, '0');",
            "  const mod = require(`./slide-${num}.js`);",
            "  mod.createSlide(pres, theme);",
            "}",
            "",
            "pres.writeFile({ fileName: './output/presentation.pptx' });",
        ]
    )


def build_toc_items(
    *, node: OutlineNode, outline_nodes: list[OutlineNode] | None = None
) -> list[dict[str, Any]]:
    """Project sibling outline nodes into render-only TOC card details."""
    if node.page_type != SlidePageType.TOC:
        return []

    def normalize(value: str) -> str:
        return " ".join(str(value).strip().lower().split())

    siblings = [
        candidate
        for candidate in (outline_nodes or [])
        if candidate.page_type not in {SlidePageType.COVER, SlidePageType.TOC}
    ]
    items: list[dict[str, Any]] = []
    for raw_title in node.bullets:
        title = str(raw_title).strip()
        if not title:
            continue
        normalized_title = normalize(title)
        matched = next(
            (
                candidate
                for candidate in siblings
                if normalize(candidate.title) == normalized_title
            ),
            None,
        )
        if matched is None:
            matched = next(
                (
                    candidate
                    for candidate in siblings
                    if normalize(candidate.title) in normalized_title
                    or normalized_title in normalize(candidate.title)
                ),
                None,
            )
        details = [
            str(item).strip()
            for item in (matched.bullets if matched is not None else [])
            if str(item).strip() and normalize(str(item)) != normalized_title
        ][:2]
        items.append({"title": title, "details": details})
    return items


def render_skill_slide_js(
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
    page_type = node.page_type
    title = json.dumps(generated.title, ensure_ascii=False)
    bullets_literal = json.dumps(generated.bullets, ensure_ascii=False)
    selected_layout = generated.layout_hint or node.layout_hint or "content-two-column"
    layout_hint = json.dumps(selected_layout, ensure_ascii=False)
    visual_kind_literal = json.dumps(
        (visual_kind or "shape").strip().lower(), ensure_ascii=False
    )
    visual_assets_literal = json.dumps(visual_assets or [], ensure_ascii=False)
    toc_items_literal = json.dumps(
        build_toc_items(node=node, outline_nodes=outline_nodes),
        ensure_ascii=False,
    )
    chart_plan_literal = json.dumps(
        {
            "hasVerifiedData": chart_plan.has_verified_data,
            "mode": chart_plan.mode,
            "labels": chart_plan.labels,
            "values": chart_plan.values,
            "unit": chart_plan.unit,
            "note": chart_plan.note,
            "source": chart_plan.source,
        },
        ensure_ascii=False,
    )
    badge = (
        build_page_badge_js(slide_no=slide_no, style=design.style)
        if page_type != SlidePageType.COVER
        else ""
    )
    content_block = slide_content_block(
        page_type=page_type,
        layout_hint=selected_layout,
        style=design.style,
        visual_kind=(visual_kind or "shape").strip().lower(),
    )
    preview_theme = theme_js_literal(design.theme)
    return "\n".join(
        [
            "const pptxgen = require('pptxgenjs');",
            "",
            "const slideConfig = {",
            f"  type: {json.dumps(page_type.value)},",
            f"  index: {slide_no},",
            f"  total: {total},",
            f"  title: {title},",
            f"  layoutHint: {layout_hint},",
            f"  bullets: {bullets_literal},",
            f"  tocItems: {toc_items_literal},",
            f"  visualKind: {visual_kind_literal},",
            f"  assets: {visual_assets_literal},",
            f"  chartPlan: {chart_plan_literal},",
            "};",
            "",
            f"const fonts = {{ title: {json.dumps(design.title_font)}, body: {json.dumps(design.body_font)} }};",
            f"const style = {{ cornerSmall: {design.style.corner_small}, cornerMedium: {design.style.corner_medium}, cornerLarge: {design.style.corner_large}, pageMargin: {design.style.page_margin}, blockGap: {design.style.block_gap}, elementGap: {design.style.element_gap}, badgePill: {str(design.style.badge_pill).lower()} }};",
            "",
            "function addBulletList(slide, items, opts, theme) {",
            "  const maxItems = opts.maxItems || 6;",
            "  const prepared = (items || []).map((x) => String(x || '').trim()).filter(Boolean).slice(0, maxItems);",
            "  const payload = prepared.length ? prepared : [(slideConfig.title || 'Core takeaway')];",
            "  const rows = payload.map((item, idx) => ({ text: item, options: { bullet: true, breakLine: idx < payload.length - 1 } }));",
            "  slide.addText(rows, { x: opts.x, y: opts.y, w: opts.w, h: opts.h, fontSize: opts.fontSize || 15, fontFace: fonts.body, color: opts.color || theme.secondary, bold: false, align: 'left', margin: 0, paraSpaceAfterPt: 7, fit: 'shrink' });",
            "}",
            "",
            "function addPageBadge(pres, slide, theme, n) {",
            "  if (style.badgePill) {",
            "    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 9.3, y: 5.1, w: 0.45, h: 0.32, fill: { color: theme.accent }, line: { color: theme.accent }, rectRadius: 0.15 });",
            "    slide.addText(String(n).padStart(2, '0'), { x: 9.3, y: 5.1, w: 0.45, h: 0.32, fontSize: 10, fontFace: fonts.body, color: 'FFFFFF', bold: true, align: 'center', valign: 'mid', margin: 0 });",
            "    return;",
            "  }",
            "  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.accent }, line: { color: theme.accent } });",
            "  slide.addText(String(n), { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 10, fontFace: fonts.body, color: 'FFFFFF', bold: true, align: 'center', valign: 'mid', margin: 0 });",
            "}",
            "",
            "function createSlide(pres, theme) {",
            "  const slide = pres.addSlide();",
            "  const bullets = Array.isArray(slideConfig.bullets) ? slideConfig.bullets : [];",
            "  slide.background = { color: theme.bg };",
            "  const titleSize = slideConfig.type === 'cover' ? 56 : (slideConfig.type === 'section' ? 46 : (slideConfig.type === 'summary' ? 42 : 38));",
            "  const titleAlign = slideConfig.type === 'cover' && slideConfig.layoutHint === 'cover-center' ? 'center' : 'left';",
            "  slide.addText(slideConfig.title, { x: style.pageMargin, y: 0.28, w: 10 - style.pageMargin * 2, h: 0.82, fontSize: titleSize, fontFace: fonts.title, color: theme.primary, bold: true, margin: 0, align: titleAlign, fit: 'shrink' });",
            content_block,
            badge,
            "  return slide;",
            "}",
            "",
            "if (require.main === module) {",
            "  const pres = new pptxgen();",
            "  pres.layout = 'LAYOUT_16x9';",
            f"  const theme = {preview_theme};",
            "  createSlide(pres, theme);",
            f"  pres.writeFile({{ fileName: 'slide-{slide_no:02d}-preview.pptx' }});",
            "}",
            "",
            "module.exports = { createSlide, slideConfig };",
        ]
    )
