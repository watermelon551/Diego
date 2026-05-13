from __future__ import annotations

import re
from typing import Any

from ...models import VisualPolicy
from .asset_contract import (
    collect_addimage_signature_issues,
    collect_addshape_signature_issues,
    collect_addtext_signature_issues,
    extract_main_asset_path,
    extract_planned_asset_paths,
    has_image_placeholder_text,
)


def validate_slide_js_contract(
    js_code: str,
    *,
    slide_no: int,
    page_type: str,
    visual_policy: VisualPolicy = VisualPolicy.AUTO,
    slide_plan: dict[str, Any] | None = None,
    extract_method_call_args,
    dedupe_preserve_order,
    collect_js_style_issues,
) -> list[str]:
    issues: list[str] = []
    export_ok = False
    export_match = re.search(
        r"module\.exports\s*=\s*\{([\s\S]{0,1400}?)\}\s*;",
        js_code,
    )
    if export_match:
        export_body = export_match.group(1)
        export_ok = ("createSlide" in export_body) and ("slideConfig" in export_body)
    if not export_ok:
        issues.append("missing export contract")
    if not re.search(r"\bfunction\s+createSlide\s*\(\s*pres\s*,\s*theme\s*\)", js_code):
        issues.append("createSlide signature invalid")
    if "async function createSlide" in js_code:
        issues.append("createSlide must be synchronous")
    if "addGroup(" in js_code:
        issues.append("forbidden api detected: addGroup()")
    if "slide.addPageBadge(" in js_code:
        issues.append("forbidden api detected: slide.addPageBadge()")
    if "createCanvas(" in js_code:
        issues.append("forbidden runtime dependency: createCanvas()")
    if re.search(r"addShape\(\s*['\"][a-zA-Z0-9_-]+['\"]", js_code):
        issues.append("addShape must use pres.shapes enum, not string literal")
    issues.extend(
        collect_addshape_signature_issues(
            js_code,
            extract_method_call_args=extract_method_call_args,
            dedupe=dedupe_preserve_order,
        )
    )
    issues.extend(
        collect_addtext_signature_issues(
            js_code,
            extract_method_call_args=extract_method_call_args,
            dedupe=dedupe_preserve_order,
        )
    )
    if _has_invalid_line_geometry(
        js_code,
        extract_method_call_args=extract_method_call_args,
    ):
        issues.append("line shape geometry invalid: w/h must be > 0")
    if re.search(r"['\"]#[0-9a-fA-F]{3,8}['\"]", js_code):
        issues.append("hex color with # is forbidden")
    if re.search(r"['\"][0-9a-fA-F]{8}['\"]", js_code):
        issues.append("8-char hex color is forbidden")
    issues.extend(
        collect_addimage_signature_issues(
            js_code,
            extract_method_call_args=extract_method_call_args,
            dedupe=dedupe_preserve_order,
        )
    )
    if slide_no > 1 and "x: 9.3, y: 5.1" not in js_code:
        issues.append("missing required page badge position")
    if any(char in js_code for char in ("•", "✓", "▪", "◦")):
        issues.append("unicode bullet symbol detected")
    planned_assets = extract_planned_asset_paths(
        js_code=js_code,
        slide_plan=slide_plan,
        dedupe=dedupe_preserve_order,
    )
    main_asset = extract_main_asset_path(
        js_code=js_code,
        slide_plan=slide_plan,
        dedupe=dedupe_preserve_order,
    )
    if page_type == "content" and all(
        token not in js_code for token in ("addShape(", "addImage(", "addChart(")
    ):
        issues.append("content slide missing non-text visual element")
    if page_type == "content" and planned_assets:
        if "addImage(" not in js_code:
            issues.append("visual assets planned but addImage() missing")
        if main_asset and main_asset not in js_code:
            issues.append("visual assets planned but main image path not used")
        if has_image_placeholder_text(js_code):
            issues.append("image placeholder text remains while visual assets are planned")
    if page_type == "content":
        if visual_policy == VisualPolicy.MEDIA_REQUIRED:
            if "addImage(" not in js_code:
                issues.append("visual_policy violation: media_required needs addImage()")
            if all(token not in js_code for token in ("addShape(", "addChart(")):
                issues.append(
                    "visual_policy violation: media_required needs addShape()/addChart() complement"
                )
        elif visual_policy == VisualPolicy.BASIC_GRAPHICS_ONLY:
            if "addImage(" in js_code:
                issues.append("visual_policy violation: basic_graphics_only forbids addImage()")
    issues.extend(collect_js_style_issues(js_code=js_code, page_type=page_type))
    return dedupe_preserve_order(issues)


def _has_invalid_line_geometry(js_code: str, *, extract_method_call_args) -> bool:
    calls = extract_method_call_args(str(js_code or ""), r"\bslide\.addShape\s*\(")
    for args in calls:
        if len(args) != 2 or "pres.shapes.LINE" not in str(args[0]):
            continue
        options = str(args[1])
        for key in ("w", "h"):
            match = re.search(rf"\b{key}\s*:\s*(-?\d+(?:\.\d+)?)\b", options)
            if match and float(match.group(1)) <= 0:
                return True
    return False
