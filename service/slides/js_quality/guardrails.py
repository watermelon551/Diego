from __future__ import annotations

import re

from ...models import SlidePageType


def apply_local_js_guardrails(
    *,
    js_code: str,
    slide_no: int,
    page_type: SlidePageType,
    has_valid_page_badge,
) -> str:
    guarded = str(js_code or "")
    guarded = _ensure_create_slide_returns_slide(guarded)
    guarded = _ensure_slide_config_index(guarded, slide_no=slide_no)
    guarded = _ensure_title_text_guardrails(guarded)
    guarded = _ensure_rows_text_guardrails(guarded)
    guarded = _ensure_line_positive_geometry(guarded)
    if page_type != SlidePageType.COVER and slide_no > 1:
        guarded = _ensure_page_badge_position(
            guarded,
            slide_no=slide_no,
            has_valid_page_badge=has_valid_page_badge,
        )
    return guarded


def has_valid_page_badge(*, js_code: str, slide_no: int) -> bool:
    if slide_no <= 1:
        return True
    payload = str(js_code or "")
    has_xy = "x: 9.3, y: 5.1" in payload
    has_helper_call = bool(re.search(r"\baddPageBadge\s*\(\s*pres\s*,\s*slide\s*,\s*theme", payload))
    has_inline = (
        bool(re.search(r"slide\.addShape\(\s*pres\.shapes\.(?:OVAL|ROUNDED_RECTANGLE)\s*,\s*\{[^{}]*x\s*:\s*9\.3[^{}]*y\s*:\s*5\.1", payload, flags=re.S))
        and bool(re.search(r"slide\.addText\([^)]*x\s*:\s*9\.3[^)]*y\s*:\s*5\.1", payload, flags=re.S))
    )
    return bool(has_xy and (has_helper_call or has_inline))


def _ensure_create_slide_returns_slide(js_code: str) -> str:
    fixed = str(js_code or "")
    fixed, count = re.subn(r"(?m)^\s*return\s*\{\s*createSlide\s*,\s*slideConfig\s*\}\s*;\s*$", "  return slide;", fixed)
    if count > 0 or not re.search(r"\bfunction\s+createSlide\s*\(", fixed) or re.search(r"(?m)^\s*return\s+slide\s*;\s*$", fixed):
        return fixed
    marker = "module.exports = { createSlide, slideConfig };"
    if marker in fixed:
        idx = fixed.find(marker)
        prefix = fixed[:idx]
        suffix = fixed[idx:]
        if "}" in prefix:
            last_brace = prefix.rfind("}")
            if last_brace >= 0:
                prefix = prefix[:last_brace] + "  return slide;\n" + prefix[last_brace:]
                return prefix + suffix
    return fixed


def _ensure_slide_config_index(js_code: str, *, slide_no: int) -> str:
    fixed = str(js_code or "")
    fixed, count = re.subn(r"(\b(?:const|let|var)\s+slideConfig\s*=\s*\{[\s\S]*?\bindex\s*:\s*)\d+", rf"\g<1>{slide_no}", fixed, count=1)
    if count > 0:
        return fixed
    if re.search(r"\b(?:const|let|var)\s+slideConfig\s*=\s*\{", fixed):
        fixed = re.sub(r"(\b(?:const|let|var)\s+slideConfig\s*=\s*\{)", rf"\1\n  index: {slide_no},", fixed, count=1)
    return fixed


def _ensure_title_text_guardrails(js_code: str) -> str:
    def repl(match: re.Match[str]) -> str:
        options = match.group(1)
        updated = options
        font_match = re.search(r"\bfontSize\s*:\s*([0-9]+(?:\.[0-9]+)?)", updated)
        if font_match:
            try:
                if float(font_match.group(1)) < 36.0:
                    updated = re.sub(r"\bfontSize\s*:\s*[0-9]+(?:\.[0-9]+)?", "fontSize: 38", updated, count=1)
            except ValueError:
                updated = re.sub(r"\bfontSize\s*:\s*[0-9]+(?:\.[0-9]+)?", "fontSize: 38", updated, count=1)
        else:
            updated = f"fontSize: 38, {updated}"
        if not re.search(r"\balign\s*:", updated):
            updated = updated.rstrip() + ", align: 'left'"
        if not re.search(r"\bfit\s*:", updated):
            updated = updated.rstrip() + ", fit: 'shrink'"
        return f"slide.addText(slideConfig.title, {{{updated}}});"

    return re.sub(r"slide\.addText\(\s*slideConfig\.title\s*,\s*\{([^{}]*)\}\s*\);", repl, js_code)


def _ensure_rows_text_guardrails(js_code: str) -> str:
    def repl(match: re.Match[str]) -> str:
        options = match.group(1)
        updated = options
        if not re.search(r"\balign\s*:", updated):
            updated = updated.rstrip() + ", align: 'left'"
        if not re.search(r"\bbold\s*:", updated):
            updated = updated.rstrip() + ", bold: false"
        if not re.search(r"\bfit\s*:", updated):
            updated = updated.rstrip() + ", fit: 'shrink'"
        return f"slide.addText(rows, {{{updated}}});"

    return re.sub(r"slide\.addText\(\s*rows\s*,\s*\{([^{}]*)\}\s*\);", repl, js_code)


def _ensure_line_positive_geometry(js_code: str) -> str:
    fixed = re.sub(r"(addShape\(\s*pres\.shapes\.LINE\s*,\s*\{[^{}]*?\bw\s*:\s*)0(?:\.0+)?(?=\s*(?:,|\}|$))", r"\g<1>0.01", js_code, flags=re.S)
    fixed = re.sub(r"(addShape\(\s*pres\.shapes\.LINE\s*,\s*\{[^{}]*?\bh\s*:\s*)0(?:\.0+)?(?=\s*(?:,|\}|$))", r"\g<1>0.01", fixed, flags=re.S)
    return fixed


def _ensure_page_badge_position(js_code: str, *, slide_no: int, has_valid_page_badge) -> str:
    if has_valid_page_badge(js_code=js_code, slide_no=slide_no) or "function createSlide(" not in js_code:
        return js_code
    updated = js_code
    if "function addPageBadge(" not in updated:
        badge_helper = "\n".join([
            "function addPageBadge(pres, slide, theme, n) {",
            "  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.accent }, line: { color: theme.accent } });",
            "  slide.addText(String(n), { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 10, color: 'FFFFFF', bold: true, align: 'center', valign: 'mid', margin: 0 });",
            "}",
            "",
        ])
        updated = updated.replace("function createSlide(", badge_helper + "function createSlide(", 1)
    if re.search(r"\baddPageBadge\s*\(\s*pres\s*,\s*slide\s*,\s*theme", updated):
        return updated
    badge_snippet = "  addPageBadge(pres, slide, theme, slideConfig.index || 1);"
    return updated.replace("return slide;", badge_snippet + "\n  return slide;", 1) if "return slide;" in updated else updated
