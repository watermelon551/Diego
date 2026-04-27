from __future__ import annotations

import re
from pathlib import Path
from typing import Callable


def load_js_api_contract(
    *,
    dedupe_preserve_order: Callable[[list[str]], list[str]],
) -> dict[str, object]:
    default_shapes = [
        "RECTANGLE",
        "ROUNDED_RECTANGLE",
        "OVAL",
        "LINE",
        "RIGHT_TRIANGLE",
        "DIAMOND",
        "CHEVRON",
        "HEXAGON",
        "PARALLELOGRAM",
        "PENTAGON",
        "PIE",
    ]
    default_charts = [
        "BAR",
        "LINE",
        "PIE",
        "DOUGHNUT",
        "SCATTER",
        "BUBBLE",
        "RADAR",
    ]
    shapes = list(default_shapes)
    charts = list(default_charts)
    types_path = Path.cwd() / "node_modules" / "pptxgenjs" / "types" / "index.d.ts"
    try:
        if types_path.exists():
            text = types_path.read_text(encoding="utf-8", errors="ignore")
            shapes_block = re.search(
                r"shapes\s*:\s*\{(?P<body>[\s\S]{0,9000}?)\}\s*;", text
            )
            if shapes_block:
                parsed = re.findall(
                    r"\b([A-Z][A-Z0-9_]+)\s*:", shapes_block.group("body")
                )
                if parsed:
                    shapes = dedupe_preserve_order(parsed)
            chart_block = re.search(
                r"ChartType[\s\S]{0,3000}\{(?P<body>[\s\S]{0,5000}?)\}", text
            )
            if chart_block:
                parsed = re.findall(
                    r"\b([A-Z][A-Z0-9_]+)\s*:", chart_block.group("body")
                )
                if parsed:
                    charts = dedupe_preserve_order(parsed)
    except Exception:
        pass
    return {
        "legal_shape_enum": shapes[:40],
        "legal_chart_enum": charts[:24],
        "required_export": "module.exports = { createSlide, slideConfig };",
        "required_signature": "function createSlide(pres, theme)",
        "forbidden_api": [
            "pres.shapes.ELLIPSE",
            "slide.addPageBadge",
            "addGroup()",
            "createCanvas()",
            "slide.background(...)",
            "pres.utilitextfit(...)",
        ],
        "known_fix_examples": [
            "ELLIPSE -> OVAL",
            "RT_TRIANGLE -> RIGHT_TRIANGLE",
            "slide.background(theme.bg) -> slide.background = { color: theme.bg }",
            "ShapeType.RECTANGLE -> pres.shapes.RECTANGLE",
            "module.exports = createSlide -> module.exports = { createSlide, slideConfig }",
        ],
    }
