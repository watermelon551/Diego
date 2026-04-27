from __future__ import annotations

import base64
import json
from typing import Any


def build_slide_preview_payload(
    *, run_id: str, slide_no: int, preview: dict[str, Any]
) -> dict[str, Any]:
    page_index = slide_no - 1
    return {
        "run_id": run_id,
        "slide_no": slide_no,
        "page_index": page_index,
        "slide_id": f"{run_id}-slide-{page_index}",
        "status": "ready",
        **preview,
    }


def build_placeholder_preview(
    *,
    slide_no: int,
    theme: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    safe_theme = _safe_theme(theme)
    bg = safe_theme["bg"]
    fg = safe_theme["primary"]
    accent = safe_theme["accent"]
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='1280' height='720' viewBox='0 0 1280 720'>"
        f"<rect width='1280' height='720' fill='#{bg}'/>"
        f"<rect x='80' y='84' width='1120' height='8' rx='4' fill='#{accent}'/>"
        f"<text x='96' y='180' font-size='48' font-family='Arial' fill='#{fg}'>Slide {slide_no}</text>"
        f"<text x='96' y='236' font-size='24' font-family='Arial' fill='#{fg}'>Preview fallback active</text>"
        f"<text x='96' y='286' font-size='18' font-family='Arial' fill='#{fg}'>Reason: {reason[:80]}</text>"
        "</svg>"
    )
    svg_data_url = "data:image/svg+xml;base64," + base64.b64encode(
        svg.encode("utf-8")
    ).decode("ascii")
    return {
        "preview": {
            "format": "svg",
            "svg_data_url": svg_data_url,
            "width": 1280,
            "height": 720,
        },
        "preview_format": "svg",
        "svg_data_url": svg_data_url,
        "width": 1280,
        "height": 720,
        "fallback": True,
        "reason": reason,
    }


def build_preview_runner_js(*, slide_js_name: str, preview_name: str) -> str:
    safe_slide = json.dumps(f"./{slide_js_name}")
    safe_preview = json.dumps(preview_name)
    return "\n".join(
        [
            "const pptxgen = require('pptxgenjs');",
            f"const mod = require({safe_slide});",
            "const theme = { primary: '111111', secondary: '222222', accent: '0A84FF', light: 'F2F3F5', bg: 'FFFFFF' };",
            "(async () => {",
            "  if (!mod || typeof mod.createSlide !== 'function') {",
            "    throw new Error('missing createSlide export');",
            "  }",
            "  const pres = new pptxgen();",
            "  pres.layout = 'LAYOUT_16x9';",
            "  mod.createSlide(pres, theme);",
            f"  await pres.writeFile({{ fileName: {safe_preview} }});",
            "})();",
            "",
        ]
    )


def _safe_theme(theme: dict[str, Any] | None) -> dict[str, str]:
    source = theme if isinstance(theme, dict) else {}
    result: dict[str, str] = {}
    for key, fallback in {
        "primary": "111111",
        "secondary": "222222",
        "accent": "0A84FF",
        "light": "F2F3F5",
        "bg": "FFFFFF",
    }.items():
        value = str(source.get(key) or fallback).strip().lstrip("#")
        result[key] = value or fallback
    return result
