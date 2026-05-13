from __future__ import annotations

import json
import re
from typing import Callable

from ...models import OutlineNode
from .asset_contract import canonicalize_addimage_signature


def auto_canonicalize_slide_js(
    js_code: str,
    *,
    slide_no: int,
    node: OutlineNode,
    target_slide_count: int,
    legal_shape_enum: list[str],
    split_top_level_args: Callable[[str], list[str]],
    find_matching_delimiter: Callable[[str, int, str, str], int],
    dedupe_preserve_order: Callable[[list[str]], list[str]],
) -> tuple[str, list[str]]:
    canonical = str(js_code or "")
    fixes: list[str] = []

    group_vars = re.findall(r"(?m)^\s*(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*slide\.addGroup\(\s*\)\s*;", canonical)
    if group_vars:
        canonical = re.sub(r"(?m)^\s*(?:const|let|var)\s+[A-Za-z_][A-Za-z0-9_]*\s*=\s*slide\.addGroup\(\s*\)\s*;\s*$", "", canonical)
        for var_name in group_vars:
            canonical = re.sub(rf"\b{re.escape(var_name)}\.(add(?:Shape|Text|Image|Chart))\(", r"slide.\1(", canonical)
        fixes.append("flatten slide.addGroup() usage")

    legal_shapes = {str(item).strip().upper() for item in (legal_shape_enum or []) if str(item).strip()}
    if legal_shapes:
        replaced_unknown_shape = False

        def _shape_guard(match: re.Match[str]) -> str:
            nonlocal replaced_unknown_shape
            token = str(match.group(1) or "").upper()
            if token in legal_shapes:
                return f"pres.shapes.{token}"
            replaced_unknown_shape = True
            return "pres.shapes.RECTANGLE"

        canonical = re.sub(r"pres\.shapes\.([A-Z][A-Z0-9_]+)", _shape_guard, canonical)
        if replaced_unknown_shape:
            fixes.append("replace unknown shape enum with RECTANGLE")

    updated, count = re.subn(
        r"module\.exports\s*=\s*\{\s*createSlide\s*,\s*slideConfig\s*,\s*\}\s*;",
        "module.exports = { createSlide, slideConfig };",
        canonical,
    )
    if count > 0:
        canonical = updated
        fixes.append("fix malformed module.exports trailing comma")

    canonical, addimage_fix_count = canonicalize_addimage_signature(
        canonical,
        split_top_level_args=split_top_level_args,
        find_matching_delimiter=lambda payload, start_idx, open_char, close_char: find_matching_delimiter(
            payload, start_idx, open_char, close_char
        ),
    )
    if addimage_fix_count > 0:
        fixes.append("normalize addImage(path, opts) to addImage({ path, ...opts })")

    canonical, addshape_fix_count = _canonicalize_addshape_positional_signature(
        canonical,
        split_top_level_args=split_top_level_args,
        find_matching_delimiter=find_matching_delimiter,
    )
    if addshape_fix_count > 0:
        fixes.append("normalize addShape(shape, x, y, w, h, opts) to addShape(shape, { x, y, w, h, ...opts })")

    canonical, line_geometry_fix_count = _canonicalize_line_positive_geometry(
        canonical,
        split_top_level_args=split_top_level_args,
        find_matching_delimiter=find_matching_delimiter,
    )
    if line_geometry_fix_count > 0:
        fixes.append("fix LINE shape zero geometry")

    if "module.exports = { createSlide, slideConfig };" in canonical and not re.search(r"\b(?:const|let|var)\s+slideConfig\b", canonical):
        fallback = "\n".join([
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
        canonical = canonical.replace("const pptxgen = require('pptxgenjs');", "const pptxgen = require('pptxgenjs');\n" + fallback, 1) if "const pptxgen" in canonical else fallback + canonical
        fixes.append("inject minimal slideConfig fallback")

    return canonical, dedupe_preserve_order(fixes)


def _canonicalize_addshape_positional_signature(
    js_code: str,
    *,
    split_top_level_args: Callable[[str], list[str]],
    find_matching_delimiter: Callable[[str, int, str, str], int],
) -> tuple[str, int]:
    payload = str(js_code or "")
    method = "slide.addShape("
    cursor = 0
    chunks: list[str] = []
    fixes = 0
    while True:
        start = payload.find(method, cursor)
        if start < 0:
            chunks.append(payload[cursor:])
            break
        open_idx = start + len(method) - 1
        close_idx = find_matching_delimiter(payload, open_idx, "(", ")")
        if close_idx < 0:
            chunks.append(payload[cursor:])
            break
        raw_args = payload[open_idx + 1 : close_idx]
        args = split_top_level_args(raw_args)
        replacement = ""
        if len(args) >= 5 and not args[1].lstrip().startswith("{"):
            shape = args[0].strip()
            x = args[1].strip()
            y = args[2].strip()
            w = args[3].strip()
            h = args[4].strip()
            options = args[5].strip() if len(args) >= 6 else "{}"
            merged_options = _merge_addshape_options(
                x=x,
                y=y,
                w=w,
                h=h,
                options=options,
            )
            replacement = f"{method}{shape}, {merged_options})"
        if replacement:
            chunks.append(payload[cursor:start])
            chunks.append(replacement)
            fixes += 1
        else:
            chunks.append(payload[cursor : close_idx + 1])
        cursor = close_idx + 1
    return "".join(chunks), fixes


def _merge_addshape_options(
    *, x: str, y: str, w: str, h: str, options: str
) -> str:
    stripped = str(options or "").strip()
    base = f"x: {x}, y: {y}, w: {w}, h: {h}"
    if stripped.startswith("{") and stripped.endswith("}"):
        inner = stripped[1:-1].strip()
        if inner:
            return "{ " + base + ", " + inner + " }"
        return "{ " + base + " }"
    return "{ " + base + " }"


def _canonicalize_line_positive_geometry(
    js_code: str,
    *,
    split_top_level_args: Callable[[str], list[str]],
    find_matching_delimiter: Callable[[str, int, str, str], int],
) -> tuple[str, int]:
    payload = str(js_code or "")
    method = "slide.addShape("
    cursor = 0
    chunks: list[str] = []
    fixes = 0
    while True:
        start = payload.find(method, cursor)
        if start < 0:
            chunks.append(payload[cursor:])
            break
        open_idx = start + len(method) - 1
        close_idx = find_matching_delimiter(payload, open_idx, "(", ")")
        if close_idx < 0:
            chunks.append(payload[cursor:])
            break
        raw_args = payload[open_idx + 1 : close_idx]
        args = split_top_level_args(raw_args)
        replacement = ""
        if len(args) >= 2 and "pres.shapes.LINE" in args[0]:
            options = args[1].strip()
            updated_options, option_fixes = _fix_line_options_positive_geometry(options)
            if option_fixes > 0:
                replacement = f"{method}{args[0].strip()}, {updated_options})"
                fixes += option_fixes
        if replacement:
            chunks.append(payload[cursor:start])
            chunks.append(replacement)
        else:
            chunks.append(payload[cursor : close_idx + 1])
        cursor = close_idx + 1
    return "".join(chunks), fixes


def _fix_line_options_positive_geometry(options: str) -> tuple[str, int]:
    payload = str(options or "").strip()
    if not (payload.startswith("{") and payload.endswith("}")):
        return options, 0

    fixes = 0

    def _positive_dimension(match: re.Match[str]) -> str:
        nonlocal fixes
        raw = match.group(2)
        try:
            value = abs(float(raw))
        except ValueError:
            value = 0.01
        if value > 0 and not raw.strip().startswith("-"):
            return match.group(0)
        if value <= 0:
            value = 0.01
        fixes += 1
        return f"{match.group(1)}{value:g}"

    updated = re.sub(
        r"(\b[wh]\s*:\s*)(-?(?:0(?:\.0+)?|(?:\d+\.\d+|\d+)))(?=\s*(?:,|\}|$))",
        _positive_dimension,
        payload,
    )
    return updated, fixes
