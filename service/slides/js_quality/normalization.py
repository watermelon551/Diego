from __future__ import annotations

import json
import re
from typing import Any, Callable

from ...models import OutlineNode


def normalize_generated_slide_js(
    js_code: str,
    *,
    slide_no: int,
    node: OutlineNode,
    target_slide_count: int,
    dedupe_preserve_order: Callable[[list[str]], list[str]],
) -> tuple[str, list[str]]:
    normalized = str(js_code or "")
    fixes: list[str] = []

    def _replace_text(old: str, new: str, label: str) -> None:
        nonlocal normalized
        if old in normalized:
            normalized = normalized.replace(old, new)
            fixes.append(label)

    def _replace_regex(pattern: str, repl: Any, label: str, *, flags: int = 0) -> None:
        nonlocal normalized
        updated, count = re.subn(pattern, repl, normalized, flags=flags)
        if count > 0:
            normalized = updated
            fixes.append(label)

    _replace_regex(r"(?m)^```(?:javascript|js)?\s*$", "", "strip markdown fence header")
    _replace_regex(r"(?m)^```\s*$", "", "strip markdown fence footer")
    normalized = normalized.strip() + "\n"

    _replace_text("require('pptxgengen')", "require('pptxgenjs')", "fix require(pptxgenjs) single quote")
    _replace_text('require("pptxgengen")', 'require("pptxgenjs")', "fix require(pptxgenjs) double quote")
    _replace_regex(r"\basync\s+function\s+createSlide\s*\(\s*pres\s*,\s*theme\s*\)", "function createSlide(pres, theme)", "remove async createSlide")

    def _background_call_to_assignment(match: re.Match[str]) -> str:
        return f"{match.group(1)}.background = {match.group(2)};"

    _replace_regex(r"(?ms)^(\s*[A-Za-z_][A-Za-z0-9_]*)\.background\(\s*(\{.*?\})\s*\)\s*;", _background_call_to_assignment, "normalize background({...}) call")
    _replace_regex(r"(?m)^(\s*slide)\.background\(\s*theme\.bg\s*\)\s*;", r"\1.background = { color: theme.bg };", "normalize background(theme.bg) call")
    _replace_regex(r"(?m)^(\s*slide)\.background\s*=\s*theme\.bg\s*;", r"\1.background = { color: theme.bg };", "normalize background assignment")

    _replace_text("pres.ShapeType.", "pres.shapes.", "normalize ShapeType namespace")
    _replace_regex(r"\bShapeType\.", "pres.shapes.", "normalize ShapeType token")
    _replace_regex(r"\bslide\.shapes\.", "pres.shapes.", "normalize slide.shapes namespace")
    _replace_regex(r"\b(?:pptxgen|pptx)\.shapes\.", "pres.shapes.", "normalize global shapes namespace")
    _replace_regex(r"addShape\(\s*[A-Za-z_][A-Za-z0-9_]*\.shapes\.", "addShape(pres.shapes.", "normalize addShape enum namespace")
    _replace_regex(r"pres\.shapes\.ELLIPSE\b", "pres.shapes.OVAL", "replace ELLIPSE with OVAL")
    _replace_regex(r"pres\.shapes\.RT_TRIANGLE\b", "pres.shapes.RIGHT_TRIANGLE", "replace RT_TRIANGLE with RIGHT_TRIANGLE")
    _replace_regex(r"\b[A-Za-z_][A-Za-z0-9_]*\.Fit\.[sS]hrink\b", "'shrink'", "normalize Fit.shrink")
    _replace_regex(r"\bpres\.utilitextfit\([^)]*\)", "36", "replace unsupported pres.utilitextfit")

    shape_alias = {
        "rect": "RECTANGLE",
        "rectangle": "RECTANGLE",
        "rounded_rectangle": "ROUNDED_RECTANGLE",
        "roundedrectangle": "ROUNDED_RECTANGLE",
        "roundrect": "ROUNDED_RECTANGLE",
        "oval": "OVAL",
        "ellipse": "OVAL",
        "circle": "OVAL",
        "line": "LINE",
        "triangle": "RIGHT_TRIANGLE",
        "rt_triangle": "RIGHT_TRIANGLE",
        "right_triangle": "RIGHT_TRIANGLE",
        "diamond": "DIAMOND",
        "chevron": "CHEVRON",
        "hexagon": "HEXAGON",
        "parallelogram": "PARALLELOGRAM",
        "pentagon": "PENTAGON",
        "pie": "PIE",
    }

    def _shape_literal_repl(match: re.Match[str]) -> str:
        token = (match.group(1) or "").strip()
        mapped = shape_alias.get(token.lower(), token.upper())
        return f"addShape(pres.shapes.{mapped}"

    def _shape_enum_case_repl(match: re.Match[str]) -> str:
        token = match.group(1)
        mapped = shape_alias.get(token.lower(), token.upper())
        return f"pres.shapes.{mapped}"

    _replace_regex(r"addShape\(\s*['\"]([A-Za-z0-9_\-]+)['\"]", _shape_literal_repl, "normalize addShape string literal")
    _replace_regex(r"pres\.shapes\.([A-Za-z_][A-Za-z0-9_]*)", _shape_enum_case_repl, "normalize pres.shapes token case")
    _replace_regex(r"(?m)^\s*slide\.addPageBadge\((.*?)\)\s*;", "  addPageBadge(pres, slide, theme, slideConfig.index);", "replace invalid slide.addPageBadge call")

    if "addPageBadge(" in normalized and "function addPageBadge(" not in normalized:
        fixes.append("inject addPageBadge helper")
        badge_helper = "\n".join([
            "function addPageBadge(pres, slide, theme, n) {",
            "  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.accent }, line: { color: theme.accent } });",
            "  slide.addText(String(n), { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 10, color: 'FFFFFF', bold: true, align: 'center', valign: 'mid', margin: 0 });",
            "}",
            "",
        ])
        normalized = normalized.replace("function createSlide(", badge_helper + "function createSlide(", 1) if "function createSlide(" in normalized else badge_helper + normalized

    _replace_regex(r"(addShape\(\s*pres\.shapes\.LINE\s*,\s*\{[^{}]*?\bw\s*:\s*)-?0(?:\.0+)?(?=\s*(?:,|\}|$))", r"\g<1>0.01", "fix LINE shape zero width", flags=re.S)
    _replace_regex(r"(addShape\(\s*pres\.shapes\.LINE\s*,\s*\{[^{}]*?\bh\s*:\s*)-?0(?:\.0+)?(?=\s*(?:,|\}|$))", r"\g<1>0.01", "fix LINE shape zero height", flags=re.S)
    _replace_regex(r"module\.exports\s*=\s*createSlide\s*;", "module.exports = { createSlide, slideConfig };", "normalize module.exports short form")
    _replace_regex(r"module\.exports\s*=\s*\{\s*createSlide\s*\}\s*;", "module.exports = { createSlide, slideConfig };", "normalize module.exports object form")

    if "module.exports = { createSlide, slideConfig };" in normalized and not re.search(r"\b(?:const|let|var)\s+slideConfig\b", normalized):
        fixes.append("inject missing slideConfig object")
        slide_config_fallback = "\n".join([
            "const slideConfig = {",
            f"  type: {json.dumps(node.page_type.value)},",
            f"  index: {slide_no},",
            f"  total: {target_slide_count},",
            f"  title: {json.dumps(node.title, ensure_ascii=False)},",
            f"  layoutHint: {json.dumps(node.layout_hint or 'content-two-column')},",
            f"  bullets: {json.dumps(node.bullets or [node.title], ensure_ascii=False)},",
            "};",
            "",
        ])
        normalized = normalized.replace("const pptxgen = require('pptxgenjs');", "const pptxgen = require('pptxgenjs');\n" + slide_config_fallback, 1) if "const pptxgen" in normalized else slide_config_fallback + normalized

    if "module.exports" not in normalized and "function createSlide" in normalized and "slideConfig" in normalized:
        fixes.append("append module.exports contract")
        normalized = normalized.rstrip() + "\n\nmodule.exports = { createSlide, slideConfig };\n"

    return normalized, dedupe_preserve_order(fixes)
