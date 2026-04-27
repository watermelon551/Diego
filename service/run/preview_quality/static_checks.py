from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ...models import VisualPolicy
from ...slides.js_asset_contract import (
    collect_addimage_signature_issues,
    extract_main_asset_path,
    extract_planned_asset_paths,
    has_image_placeholder_text,
)


@dataclass
class ScratchSlideStaticEvaluation:
    page_type: str
    observed_layout: str | None
    checksum: str
    static_issues: list[str]
    unchanged_preview: bool
    cached_preview_issues: list[str]


def evaluate_scratch_slide_static(
    *,
    slide_js_path: Path,
    slide_no: int,
    text: str,
    visual_policy: VisualPolicy,
    preview_cache_in: dict[str, Any],
    has_valid_page_badge: Callable[[str, int], bool],
    extract_method_call_args: Callable[[str, str], list[list[str]]],
    dedupe_preserve_order: Callable[[list[str]], list[str]],
) -> ScratchSlideStaticEvaluation:
    page_type_match = re.search(r"type:\s*['\"]([^'\"]+)['\"]", text)
    page_type = page_type_match.group(1).strip().lower() if page_type_match else ""
    if not page_type:
        page_type_match = re.search(r"page_type:\s*['\"]([^'\"]+)['\"]", text)
        page_type = page_type_match.group(1).strip().lower() if page_type_match else ""

    static_issues: list[str] = []
    if "module.exports = { createSlide, slideConfig };" not in text:
        static_issues.append(f"{slide_js_path.name}: missing export contract")
    if "function createSlide(pres, theme)" not in text:
        static_issues.append(f"{slide_js_path.name}: createSlide signature invalid")
    if "async function createSlide" in text:
        static_issues.append(f"{slide_js_path.name}: createSlide must be synchronous")
    if re.search(r"['\"]#[0-9a-fA-F]{3,8}['\"]", text):
        static_issues.append(f"{slide_js_path.name}: hex color with # is forbidden")
    if re.search(r"['\"][0-9a-fA-F]{8}['\"]", text):
        static_issues.append(f"{slide_js_path.name}: 8-char hex color is forbidden")
    if slide_no > 1 and not has_valid_page_badge(text, slide_no):
        static_issues.append(
            f"{slide_js_path.name}: missing required page badge position"
        )

    theme_hits = sum(
        1
        for key in (
            "theme.primary",
            "theme.secondary",
            "theme.accent",
            "theme.light",
            "theme.bg",
        )
        if key in text
    )
    if "theme.primary" not in text or "theme.bg" not in text or theme_hits < 4:
        static_issues.append(f"{slide_js_path.name}: theme key usage incomplete")
    if any(char in text for char in ("•", "✓", "▪", "◦")):
        static_issues.append(f"{slide_js_path.name}: unicode bullet symbol detected")
    if re.search(r"addShape\(pres\.shapes\.LINE,[^\n]*y:\s*1\.[0-3]", text):
        static_issues.append(f"{slide_js_path.name}: title accent line pattern detected")
    if page_type == "content" and all(
        token not in text for token in ("addShape(", "addImage(", "addChart(")
    ):
        static_issues.append(
            f"{slide_js_path.name}: content slide missing non-text visual element"
        )

    image_sig_issues = collect_addimage_signature_issues(
        text,
        extract_method_call_args=lambda payload, method_expr: extract_method_call_args(
            payload, method_expr
        ),
        dedupe=dedupe_preserve_order,
    )
    for issue in image_sig_issues:
        static_issues.append(f"{slide_js_path.name}: {issue}")

    planned_assets = extract_planned_asset_paths(
        js_code=text,
        slide_plan=None,
        dedupe=dedupe_preserve_order,
    )
    main_asset = extract_main_asset_path(
        js_code=text,
        slide_plan=None,
        dedupe=dedupe_preserve_order,
    )
    if page_type == "content" and planned_assets:
        if "addImage(" not in text:
            static_issues.append(
                f"{slide_js_path.name}: visual assets planned but addImage() missing"
            )
        if main_asset and main_asset not in text:
            static_issues.append(
                f"{slide_js_path.name}: visual assets planned but main image path not used"
            )
        if has_image_placeholder_text(text):
            static_issues.append(
                f"{slide_js_path.name}: image placeholder text remains while visual assets are planned"
            )

    if page_type == "content" and visual_policy == VisualPolicy.MEDIA_REQUIRED:
        if "addImage(" not in text:
            static_issues.append(
                f"{slide_js_path.name}: visual_policy media_required expects addImage()"
            )
        if all(token not in text for token in ("addShape(", "addChart(")):
            static_issues.append(
                f"{slide_js_path.name}: visual_policy media_required expects shape/chart complement"
            )
    if (
        page_type == "content"
        and visual_policy == VisualPolicy.BASIC_GRAPHICS_ONLY
        and "addImage(" in text
    ):
        static_issues.append(
            f"{slide_js_path.name}: visual_policy basic_graphics_only forbids addImage()"
        )

    layout_match = re.search(r"(?:layoutHint|layout):\s*['\"]([^'\"]+)['\"]", text)
    observed_layout = layout_match.group(1) if layout_match else None

    checksum = f"{zlib.crc32(text.encode('utf-8')):08x}"
    cache_entry = (
        preview_cache_in.get(slide_js_path.name, {})
        if isinstance(preview_cache_in.get(slide_js_path.name, {}), dict)
        else {}
    )
    unchanged_preview = str(cache_entry.get("hash", "")) == checksum
    cached_preview_issues = (
        [str(item) for item in cache_entry.get("issues", [])]
        if isinstance(cache_entry.get("issues", []), list)
        else []
    )

    return ScratchSlideStaticEvaluation(
        page_type=page_type,
        observed_layout=observed_layout,
        checksum=checksum,
        static_issues=static_issues,
        unchanged_preview=unchanged_preview,
        cached_preview_issues=cached_preview_issues,
    )
