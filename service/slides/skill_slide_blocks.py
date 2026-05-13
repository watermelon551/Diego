from __future__ import annotations

from ..design.skill_profile import StyleRecipe
from ..models import SlidePageType


def slide_content_block(
    *,
    page_type: SlidePageType,
    layout_hint: str,
    style: StyleRecipe,
    visual_kind: str = "shape",
) -> str:
    if page_type == SlidePageType.COVER:
        return slide_block_cover(layout_hint)
    if page_type == SlidePageType.TOC:
        return slide_block_toc(layout_hint)
    if page_type == SlidePageType.SECTION:
        return slide_block_section(layout_hint)
    if page_type == SlidePageType.SUMMARY:
        return slide_block_summary(layout_hint)
    return slide_block_content(layout_hint, visual_kind=visual_kind)


def slide_block_cover(layout_hint: str) -> str:
    if layout_hint == "cover-center":
        return "\n".join(
            [
                "  slide.addShape(pres.shapes.RECTANGLE, { x: 0.0, y: 1.35, w: 10.0, h: 2.95, fill: { color: theme.light, transparency: 18 }, line: { color: theme.light } });",
                "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 2.1, y: 1.75, w: 5.8, h: 1.9, fill: { color: theme.bg, transparency: 8 }, line: { color: theme.secondary }, rectRadius: style.cornerLarge });",
                "  slide.addText((bullets[0] || 'Presentation opening statement').slice(0, 120), { x: 2.4, y: 2.4, w: 5.2, h: 0.7, fontSize: 22, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'center', margin: 0, fit: 'shrink' });",
            ]
        )
    return "\n".join(
        [
            "  slide.addShape(pres.shapes.RECTANGLE, { x: 5.3, y: 0.0, w: 4.7, h: 5.625, fill: { color: theme.light, transparency: 14 }, line: { color: theme.light } });",
            "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.7, y: 1.4, w: 4.5, h: 2.5, fill: { color: theme.primary, transparency: 10 }, line: { color: theme.primary }, rectRadius: style.cornerLarge });",
            "  slide.addText((bullets[0] || 'Audience, objective, and context').slice(0, 120), { x: 0.95, y: 3.15, w: 4.05, h: 0.75, fontSize: 20, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'left', margin: 0, fit: 'shrink' });",
        ]
    )


def slide_block_toc(layout_hint: str) -> str:
    if layout_hint == "toc-grid":
        return "\n".join(
            [
                "  const items = bullets.slice(0, 6);",
                "  items.forEach((item, idx) => {",
                "    const col = idx % 2;",
                "    const row = Math.floor(idx / 2);",
                "    const x = 0.8 + col * 4.5;",
                "    const y = 1.3 + row * 1.2;",
                "    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 4.0, h: 0.95, fill: { color: theme.light, transparency: 12 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                "    slide.addText(String(idx + 1).padStart(2, '0'), { x: x + 0.2, y: y + 0.2, w: 0.7, h: 0.5, fontSize: 20, fontFace: fonts.title, color: theme.accent, bold: true, margin: 0 });",
                "    slide.addText(item, { x: x + 1.0, y: y + 0.24, w: 2.8, h: 0.48, fontSize: 16, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'left', margin: 0, fit: 'shrink' });",
                "  });",
            ]
        )
    if layout_hint == "toc-sidebar":
        return "\n".join(
            [
                "  const items = bullets.slice(0, 5);",
                "  slide.addShape(pres.shapes.RECTANGLE, { x: 0.55, y: 1.2, w: 1.0, h: 3.8, fill: { color: theme.primary, transparency: 8 }, line: { color: theme.primary } });",
                "  items.forEach((item, idx) => {",
                "    const y = 1.4 + idx * 0.72;",
                "    slide.addShape(pres.shapes.OVAL, { x: 0.85, y: y + 0.1, w: 0.3, h: 0.3, fill: { color: theme.accent }, line: { color: theme.accent } });",
                "    slide.addText(String(idx + 1), { x: 0.85, y: y + 0.1, w: 0.3, h: 0.3, fontSize: 11, fontFace: fonts.body, color: 'FFFFFF', bold: true, align: 'center', valign: 'mid', margin: 0 });",
                "    slide.addText(item, { x: 1.8, y, w: 7.7, h: 0.44, fontSize: 18, fontFace: fonts.body, color: theme.secondary, bold: false, margin: 0, fit: 'shrink' });",
                "  });",
            ]
        )
    if layout_hint == "toc-cards":
        return "\n".join(
            [
                "  const items = bullets.slice(0, 4);",
                "  items.forEach((item, idx) => {",
                "    const x = 0.8 + idx * 2.25;",
                "    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 2.0, w: 2.0, h: 1.7, fill: { color: theme.light, transparency: 10 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerLarge });",
                "    slide.addText(String(idx + 1).padStart(2, '0'), { x: x + 0.1, y: 2.18, w: 1.8, h: 0.48, fontSize: 28, fontFace: fonts.title, color: theme.accent, bold: true, align: 'center', margin: 0 });",
                "    slide.addText(item, { x: x + 0.15, y: 2.72, w: 1.7, h: 0.8, fontSize: 13, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'center', margin: 0, fit: 'shrink' });",
                "  });",
            ]
        )
    return "\n".join(
        [
            "  const items = bullets.slice(0, 6);",
            "  items.forEach((item, idx) => {",
            "    const y = 1.35 + idx * 0.6;",
            "    slide.addText(String(idx + 1).padStart(2, '0'), { x: 0.9, y, w: 0.8, h: 0.45, fontSize: 24, fontFace: fonts.title, color: theme.accent, bold: true, margin: 0 });",
            "    slide.addText(item, { x: 1.9, y: y + 0.03, w: 7.6, h: 0.42, fontSize: 17, fontFace: fonts.body, color: theme.secondary, bold: false, margin: 0, fit: 'shrink' });",
            "  });",
        ]
    )


def slide_block_section(layout_hint: str) -> str:
    if layout_hint == "section-accent-block":
        return "\n".join(
            [
                "  slide.addShape(pres.shapes.RECTANGLE, { x: 0.0, y: 1.1, w: 1.4, h: 3.8, fill: { color: theme.primary }, line: { color: theme.primary } });",
                "  slide.addText(String(slideConfig.index).padStart(2, '0'), { x: 1.75, y: 1.8, w: 2.4, h: 1.1, fontSize: 86, fontFace: fonts.title, color: theme.accent, bold: true, margin: 0 });",
                "  slide.addText((bullets[0] || 'Section transition').slice(0, 100), { x: 1.9, y: 3.25, w: 6.8, h: 0.55, fontSize: 18, fontFace: fonts.body, color: theme.secondary, bold: false, margin: 0, fit: 'shrink' });",
            ]
        )
    if layout_hint == "section-split":
        return "\n".join(
            [
                "  slide.addShape(pres.shapes.RECTANGLE, { x: 0.0, y: 1.2, w: 4.8, h: 3.6, fill: { color: theme.primary, transparency: 10 }, line: { color: theme.primary } });",
                "  slide.addShape(pres.shapes.RECTANGLE, { x: 4.8, y: 1.2, w: 5.2, h: 3.6, fill: { color: theme.light, transparency: 12 }, line: { color: theme.light } });",
                "  slide.addText(String(slideConfig.index).padStart(2, '0'), { x: 1.25, y: 2.05, w: 2.6, h: 1.2, fontSize: 96, fontFace: fonts.title, color: theme.bg, bold: true, align: 'center', margin: 0 });",
                "  slide.addText((bullets[0] || 'Context and objective').slice(0, 120), { x: 5.2, y: 2.35, w: 4.2, h: 0.9, fontSize: 20, fontFace: fonts.body, color: theme.secondary, bold: false, margin: 0, fit: 'shrink' });",
            ]
        )
    return "\n".join(
        [
            "  slide.addText(String(slideConfig.index).padStart(2, '0'), { x: 3.8, y: 1.3, w: 2.4, h: 1.4, fontSize: 96, fontFace: fonts.title, color: theme.accent, bold: true, align: 'center', margin: 0 });",
            "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 2.2, y: 2.95, w: 5.6, h: 1.3, fill: { color: theme.light, transparency: 10 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerLarge });",
            "  slide.addText((bullets[0] || 'Transition summary').slice(0, 120), { x: 2.5, y: 3.28, w: 5.0, h: 0.66, fontSize: 19, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'center', margin: 0, fit: 'shrink' });",
        ]
    )


def slide_block_content(layout_hint: str, *, visual_kind: str = "shape") -> str:
    visual_header = [
        "  const visualKind = String(slideConfig.visualKind || 'shape').toLowerCase();",
        "  const visualAssets = Array.isArray(slideConfig.assets) ? slideConfig.assets.filter((item) => item && typeof item.path === 'string' && item.path.trim()) : [];",
        "  const visualAssetMain = visualAssets.find((item) => String(item.slot || '').toLowerCase() === 'main') || visualAssets[0] || null;",
        "  const visualAssetSecondary = visualAssets.find((item) => String(item.slot || '').toLowerCase() === 'secondary') || (visualAssets.length > 1 ? visualAssets[1] : null);",
    ]
    if layout_hint == "content-icon-rows":
        body = "\n".join(
            [
                "  if (visualKind === 'image' && visualAssetMain && visualAssetMain.path) {",
                "    slide.addImage({ path: visualAssetMain.path, x: 6.75, y: 1.05, w: 2.15, h: 1.25 });",
                "  }",
                "  bullets.slice(0, 5).forEach((item, idx) => {",
                "    const y = 1.35 + idx * 0.72;",
                "    slide.addShape(pres.shapes.OVAL, { x: 0.85, y: y + 0.08, w: 0.32, h: 0.32, fill: { color: theme.accent }, line: { color: theme.accent } });",
                "    slide.addText(String(idx + 1), { x: 0.85, y: y + 0.08, w: 0.32, h: 0.32, fontSize: 11, fontFace: fonts.body, color: 'FFFFFF', bold: true, align: 'center', valign: 'mid', margin: 0 });",
                "    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 1.35, y, w: 8.0, h: 0.52, fill: { color: theme.light, transparency: 11 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerSmall });",
                "    slide.addText(item, { x: 1.58, y: y + 0.11, w: 7.5, h: 0.35, fontSize: 15, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'left', margin: 0, fit: 'shrink' });",
                "  });",
            ]
        )
        return "\n".join(visual_header + [body])
    if layout_hint == "content-comparison":
        body = "\n".join(
            [
                "  const left = bullets.filter((_, idx) => idx % 2 === 0).slice(0, 3);",
                "  const right = bullets.filter((_, idx) => idx % 2 === 1).slice(0, 3);",
                "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.8, y: 1.25, w: 4.1, h: 3.7, fill: { color: theme.light, transparency: 12 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 5.1, y: 1.25, w: 4.1, h: 3.7, fill: { color: theme.bg }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                "  slide.addText('Track A', { x: 1.1, y: 1.53, w: 3.3, h: 0.45, fontSize: 20, fontFace: fonts.title, color: theme.primary, bold: true, margin: 0 });",
                "  slide.addText('Track B', { x: 5.4, y: 1.53, w: 3.3, h: 0.45, fontSize: 20, fontFace: fonts.title, color: theme.primary, bold: true, margin: 0 });",
                "  addBulletList(slide, left, { x: 1.1, y: 2.05, w: 3.5, h: 2.7, maxItems: 3, fontSize: 14 }, theme);",
                "  addBulletList(slide, right, { x: 5.4, y: 2.05, w: 3.5, h: 2.7, maxItems: 3, fontSize: 14 }, theme);",
            ]
        )
        return "\n".join(visual_header + [body])
    if layout_hint == "content-timeline":
        body = "\n".join(
            [
                "  const steps = bullets.slice(0, 5);",
                "  slide.addShape(pres.shapes.LINE, { x: 1.0, y: 2.45, w: 8.0, h: 0.01, line: { color: theme.secondary, pt: 1 } });",
                "  steps.forEach((item, idx) => {",
                "    const x = 1.0 + idx * (8.0 / Math.max(steps.length - 1, 1));",
                "    slide.addShape(pres.shapes.OVAL, { x: x - 0.16, y: 2.27, w: 0.32, h: 0.32, fill: { color: theme.accent }, line: { color: theme.accent } });",
                "    slide.addText(String(idx + 1), { x: x - 0.16, y: 2.27, w: 0.32, h: 0.32, fontSize: 10, fontFace: fonts.body, color: 'FFFFFF', bold: true, align: 'center', valign: 'mid', margin: 0 });",
                "    slide.addText(item, { x: x - 0.7, y: 2.7, w: 1.4, h: 0.8, fontSize: 12, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'center', margin: 0, fit: 'shrink' });",
                "  });",
            ]
        )
        return "\n".join(visual_header + [body])
    if layout_hint == "content-stat-callout":
        body = "\n".join(
            [
                "  const cp = slideConfig.chartPlan || { hasVerifiedData: false, labels: [], values: [], unit: '', note: '' };",
                "  const metricRaw = cp.hasVerifiedData && cp.values.length ? String(cp.values[0]) : 'N/A';",
                "  const metricValue = cp.hasVerifiedData ? `${metricRaw}${cp.unit || ''}` : 'N/A';",
                "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.8, y: 1.25, w: 3.6, h: 3.75, fill: { color: theme.primary, transparency: 6 }, line: { color: theme.primary }, rectRadius: style.cornerLarge });",
                "  slide.addText(metricValue, { x: 1.2, y: 2.08, w: 2.8, h: 1.2, fontSize: 76, fontFace: fonts.title, color: theme.bg, bold: true, align: 'center', margin: 0, fit: 'shrink' });",
                "  slide.addText('Key Metric', { x: 1.3, y: 3.35, w: 2.6, h: 0.45, fontSize: 16, fontFace: fonts.body, color: theme.bg, bold: false, align: 'center', margin: 0 });",
                "  if (cp.hasVerifiedData && cp.labels.length > 1 && cp.values.length > 1) {",
                "    const labels = cp.labels.slice(0, 5);",
                "    const values = cp.values.slice(0, labels.length);",
                "    slide.addChart(pres.ChartType.bar, [{ name: 'Verified', labels, values }], { x: 4.9, y: 1.45, w: 4.2, h: 2.1, barDir: 'col', catAxisLabelRotate: 315, showLegend: false, showValue: true, chartColors: [theme.accent] });",
                "    slide.addText((cp.note || '').slice(0, 120), { x: 4.95, y: 3.7, w: 4.1, h: 0.5, fontSize: 11, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'left', margin: 0, fit: 'shrink' });",
                "  } else {",
                "    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 4.9, y: 1.45, w: 4.2, h: 2.1, fill: { color: theme.light, transparency: 12 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                "    slide.addText((cp.note || 'Qualitative trend summary.').slice(0, 160), { x: 5.15, y: 1.92, w: 3.7, h: 1.0, fontSize: 13, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'left', margin: 0, fit: 'shrink' });",
                "  }",
                "  addBulletList(slide, bullets.slice(0, 5), { x: 4.9, y: 3.95, w: 4.2, h: 1.2, maxItems: 4, fontSize: 12 }, theme);",
            ]
        )
        return "\n".join(visual_header + [body])
    if layout_hint == "content-showcase":
        body = "\n".join(
            [
                "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.8, y: 1.25, w: 8.4, h: 2.55, fill: { color: theme.light, transparency: 6 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                "  if (visualKind === 'image' && visualAssetMain && visualAssetMain.path) {",
                "    slide.addImage({ path: visualAssetMain.path, x: 1.0, y: 1.42, w: 7.95, h: 2.2 });",
                "    if (visualAssetSecondary && visualAssetSecondary.path) {",
                "      slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 7.45, y: 3.25, w: 1.4, h: 0.88, fill: { color: theme.bg, transparency: 6 }, line: { color: theme.bg, pt: 1 }, rectRadius: style.cornerSmall });",
                "      slide.addImage({ path: visualAssetSecondary.path, x: 7.52, y: 3.32, w: 1.25, h: 0.74 });",
                "    }",
                "  } else {",
                "    const panelItems = bullets.slice(0, 4);",
                "    panelItems.forEach((item, idx) => {",
                "      const x = 1.05 + idx * 1.95;",
                "      const h = 0.55 + (idx % 3) * 0.22;",
                "      slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 2.72 - h, w: 1.35, h, fill: { color: idx % 2 === 0 ? theme.primary : theme.accent, transparency: 12 }, line: { color: theme.bg, pt: 1 }, rectRadius: style.cornerSmall });",
                "      slide.addShape(pres.shapes.OVAL, { x: x + 0.45, y: 1.58 + idx * 0.04, w: 0.44, h: 0.44, fill: { color: theme.bg, transparency: 8 }, line: { color: theme.secondary, pt: 1 } });",
                "      slide.addText(String(idx + 1), { x: x + 0.45, y: 1.66 + idx * 0.04, w: 0.44, h: 0.18, fontSize: 9, fontFace: fonts.body, color: theme.secondary, bold: true, align: 'center', margin: 0 });",
                "      slide.addText(item.slice(0, 28), { x: x - 0.08, y: 2.9, w: 1.5, h: 0.35, fontSize: 9, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'center', margin: 0, fit: 'shrink' });",
                "    });",
                "    slide.addShape(pres.shapes.LINE, { x: 1.0, y: 2.74, w: 7.85, h: 0.01, line: { color: theme.secondary, pt: 1 } });",
                "  }",
                "  addBulletList(slide, bullets.slice(0, 3), { x: 1.1, y: 4.02, w: 7.8, h: 0.95, maxItems: 3, fontSize: 13 }, theme);",
            ]
        )
        return "\n".join(visual_header + [body])
    body = "\n".join(
        [
            "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.7, y: 1.25, w: 4.2, h: 3.75, fill: { color: theme.light, transparency: 12 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
            "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 5.1, y: 1.25, w: 4.2, h: 3.75, fill: { color: theme.bg }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
            "  if (visualKind === 'image' && visualAssetMain && visualAssetMain.path) {",
            "    slide.addImage({ path: visualAssetMain.path, x: 1.0, y: 1.55, w: 3.6, h: 3.05 });",
            "    if (visualAssetSecondary && visualAssetSecondary.path) {",
            "      slide.addImage({ path: visualAssetSecondary.path, x: 3.65, y: 3.88, w: 1.05, h: 0.7 });",
            "    }",
            "  } else {",
            "    const diagramItems = bullets.slice(0, 3);",
            "    diagramItems.forEach((item, idx) => {",
            "      const y = 1.62 + idx * 0.9;",
            "      slide.addShape(pres.shapes.OVAL, { x: 1.15, y, w: 0.58, h: 0.58, fill: { color: idx === 1 ? theme.accent : theme.primary, transparency: 8 }, line: { color: theme.bg, pt: 1 } });",
            "      slide.addText(String(idx + 1), { x: 1.15, y: y + 0.16, w: 0.58, h: 0.18, fontSize: 10, fontFace: fonts.body, color: theme.bg, bold: true, align: 'center', margin: 0 });",
            "      slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 1.95, y: y + 0.05, w: 2.25, h: 0.48, fill: { color: theme.bg, transparency: 3 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerSmall });",
            "      slide.addText(item.slice(0, 36), { x: 2.12, y: y + 0.17, w: 1.9, h: 0.2, fontSize: 9, fontFace: fonts.body, color: theme.secondary, bold: false, margin: 0, fit: 'shrink' });",
            "      if (idx < diagramItems.length - 1) {",
            "        slide.addShape(pres.shapes.LINE, { x: 1.44, y: y + 0.58, w: 0.01, h: 0.32, line: { color: theme.secondary, pt: 1 } });",
            "      }",
            "    });",
            "    if (diagramItems.length === 0) {",
            "      slide.addShape(pres.shapes.OVAL, { x: 1.35, y: 2.1, w: 1.05, h: 1.05, fill: { color: theme.primary, transparency: 8 }, line: { color: theme.bg, pt: 1 } });",
            "      slide.addShape(pres.shapes.OVAL, { x: 2.35, y: 2.1, w: 1.05, h: 1.05, fill: { color: theme.accent, transparency: 8 }, line: { color: theme.bg, pt: 1 } });",
            "      slide.addShape(pres.shapes.OVAL, { x: 1.85, y: 2.95, w: 1.05, h: 1.05, fill: { color: theme.secondary, transparency: 8 }, line: { color: theme.bg, pt: 1 } });",
            "    }",
            "  }",
            "  addBulletList(slide, bullets.slice(0, 6), { x: 5.35, y: 1.6, w: 3.75, h: 3.1, maxItems: 6, fontSize: 14 }, theme);",
        ]
    )
    return "\n".join(visual_header + [body])


def slide_block_summary(layout_hint: str) -> str:
    if layout_hint == "summary-cta":
        return "\n".join(
            [
                "  const items = bullets.slice(0, 4);",
                "  items.forEach((item, idx) => {",
                "    const y = 1.35 + idx * 0.82;",
                "    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.9, y, w: 8.2, h: 0.62, fill: { color: theme.light, transparency: 12 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                "    slide.addText(String(idx + 1), { x: 1.1, y: y + 0.14, w: 0.5, h: 0.32, fontSize: 14, fontFace: fonts.title, color: theme.accent, bold: true, margin: 0 });",
                "    slide.addText(item, { x: 1.8, y: y + 0.12, w: 6.9, h: 0.38, fontSize: 16, fontFace: fonts.body, color: theme.secondary, bold: false, margin: 0, fit: 'shrink' });",
                "  });",
            ]
        )
    if layout_hint == "summary-thankyou":
        return "\n".join(
            [
                "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 1.8, y: 1.6, w: 6.4, h: 2.5, fill: { color: theme.light, transparency: 8 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerLarge });",
                "  slide.addText((bullets[0] || 'Thank you for your attention').slice(0, 120), { x: 2.2, y: 2.35, w: 5.6, h: 0.65, fontSize: 24, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'center', margin: 0, fit: 'shrink' });",
                "  slide.addText((bullets[1] || 'Contact details and next steps').slice(0, 120), { x: 2.2, y: 3.08, w: 5.6, h: 0.45, fontSize: 16, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'center', margin: 0, fit: 'shrink' });",
            ]
        )
    if layout_hint == "summary-split":
        return "\n".join(
            [
                "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.7, y: 1.25, w: 4.2, h: 3.75, fill: { color: theme.light, transparency: 10 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 5.1, y: 1.25, w: 4.2, h: 3.75, fill: { color: theme.bg }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                "  slide.addText('Summary', { x: 1.0, y: 1.5, w: 3.6, h: 0.45, fontSize: 22, fontFace: fonts.title, color: theme.primary, bold: true, margin: 0 });",
                "  slide.addText('Next Steps', { x: 5.4, y: 1.5, w: 3.6, h: 0.45, fontSize: 22, fontFace: fonts.title, color: theme.primary, bold: true, margin: 0 });",
                "  addBulletList(slide, bullets.slice(0, 3), { x: 1.0, y: 2.05, w: 3.3, h: 2.6, maxItems: 3, fontSize: 14 }, theme);",
                "  addBulletList(slide, bullets.slice(3, 6), { x: 5.4, y: 2.05, w: 3.3, h: 2.6, maxItems: 3, fontSize: 14 }, theme);",
            ]
        )
    return "\n".join(
        [
            "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.7, y: 1.25, w: 8.6, h: 3.8, fill: { color: theme.light, transparency: 9 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
            "  addBulletList(slide, bullets.slice(0, 5), { x: 1.0, y: 1.68, w: 8.0, h: 2.95, maxItems: 5, fontSize: 17 }, theme);",
        ]
    )
