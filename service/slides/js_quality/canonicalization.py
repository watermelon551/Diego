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
