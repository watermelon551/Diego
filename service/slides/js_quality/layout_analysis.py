from __future__ import annotations

import re
from typing import Any, Callable

from ...run.types import JsLayoutBox, SLIDE_HEIGHT_IN, SLIDE_WIDTH_IN


def collect_js_style_issues(
    *,
    js_code: str,
    page_type: str,
    find_matching_delimiter: Callable[[str, int, str, str], int],
    split_top_level_args: Callable[[str], list[str]],
    dedupe_preserve_order: Callable[[list[str]], list[str]],
) -> list[str]:
    issues: list[str] = []
    boxes = collect_js_layout_boxes(
        js_code,
        find_matching_delimiter=find_matching_delimiter,
        split_top_level_args=split_top_level_args,
    )
    if not boxes:
        return issues

    major_boxes = [
        box
        for box in boxes
        if not is_js_page_badge_box(box)
        and (box.element_type in {"text", "image", "chart"} or box.area >= 0.45)
    ]
    margin_floor = 0.5 if page_type == "content" else 0.35

    for idx, box in enumerate(major_boxes, start=1):
        if box.x < -0.01 or box.y < -0.01 or box.x + box.w > SLIDE_WIDTH_IN + 0.01 or box.y + box.h > SLIDE_HEIGHT_IN + 0.01:
            issues.append(f"box-{idx} out of slide bounds")
            continue
        if page_type == "content":
            left = box.x
            top = box.y
            right = SLIDE_WIDTH_IN - (box.x + box.w)
            bottom = SLIDE_HEIGHT_IN - (box.y + box.h)
            lowered_expr = box.text_expr.lower()
            is_title_box = box.element_type == "text" and "slideconfig.title" in lowered_expr
            if is_title_box:
                if min(left, right) < margin_floor - 0.03:
                    issues.append(f"box-{idx} horizontal margin too tight (<{margin_floor:.1f}in)")
            elif min(left, right, top, bottom) < margin_floor - 0.03:
                issues.append(f"box-{idx} margin too tight (<{margin_floor:.1f}in)")

    for i in range(len(major_boxes)):
        for j in range(i + 1, len(major_boxes)):
            if major_boxes[i].element_type == "shape" and major_boxes[j].element_type == "shape":
                continue
            if is_js_intentional_container_overlap(major_boxes[i], major_boxes[j]):
                continue
            overlap_ratio = js_box_overlap_ratio(major_boxes[i], major_boxes[j])
            if overlap_ratio >= 0.12:
                issues.append(f"box-{i + 1} overlaps box-{j + 1} (ratio={overlap_ratio:.2f})")
            if page_type == "content":
                gap = js_major_block_gap(major_boxes[i], major_boxes[j])
                if gap is not None and 0 < gap < 0.22:
                    issues.append(f"box-{i + 1} and box-{j + 1} gap too tight ({gap:.2f}\" < 0.22\")")

    text_boxes = [box for box in boxes if box.element_type == "text" and not is_js_page_badge_box(box)]
    title_box = next((box for box in text_boxes if "slideconfig.title" in box.text_expr.lower()), None)
    body_font_sizes: list[float] = []
    for box in text_boxes:
        looks_like_body = is_js_body_text_candidate(box)
        if looks_like_body and box.font_size is not None:
            body_font_sizes.append(box.font_size)
        if page_type == "content" and looks_like_body:
            if (box.align or "").lower() == "center" and box.h >= 0.32:
                issues.append("body text must be left-aligned (center detected)")
            if box.bold is True and (box.font_size is None or box.font_size <= 18):
                issues.append("body text should not use bold")
            if box.w >= 1.2 and box.h >= 0.45 and (box.fit or "").lower() != "shrink":
                issues.append("body text missing fit:'shrink'")

    if title_box is not None:
        if (title_box.fit or "").lower() != "shrink":
            issues.append("title missing fit:'shrink'")
        if title_box.font_size is not None:
            if title_box.font_size < 36:
                issues.append(f"title font too small ({title_box.font_size:.0f} < 36)")
            if body_font_sizes and title_box.font_size < max(body_font_sizes) + 18:
                issues.append("title/body size contrast too weak")

    return dedupe_preserve_order(issues)


def is_js_body_text_candidate(box: JsLayoutBox) -> bool:
    if box.element_type != "text":
        return False
    lowered_expr = box.text_expr.lower()
    if "slideconfig.title" in lowered_expr:
        return False

    literal_match = re.fullmatch(r"['\"]([^'\"]*)['\"]", box.text_expr.strip(), flags=re.DOTALL)
    if literal_match:
        literal_text = re.sub(r"\s+", " ", literal_match.group(1)).strip()
        if literal_text and len(literal_text) <= 24 and len(literal_text.split()) <= 4:
            return False

    signal_tokens = ("bullets", "rows", "item", "note", "takeaway", "payload", "prepared", "join(")
    if any(token in lowered_expr for token in signal_tokens):
        return True

    if box.y < 1.0 or box.w < 1.4 or box.h < 0.34:
        return False
    if box.font_size is not None and box.font_size >= 20:
        return False
    return True


def collect_js_layout_boxes(
    js_code: str,
    *,
    find_matching_delimiter: Callable[[str, int, str, str], int],
    split_top_level_args: Callable[[str], list[str]],
) -> list[JsLayoutBox]:
    boxes: list[JsLayoutBox] = []
    for method in ("addText", "addShape", "addImage", "addChart"):
        for first_arg, options_raw in extract_slide_method_calls(
            js_code,
            method=method,
            find_matching_delimiter=find_matching_delimiter,
            split_top_level_args=split_top_level_args,
        ):
            x = parse_js_float_option(options_raw, "x")
            y = parse_js_float_option(options_raw, "y")
            w = parse_js_float_option(options_raw, "w")
            h = parse_js_float_option(options_raw, "h")
            if x is None or y is None or w is None or h is None or w <= 0 or h <= 0:
                continue
            element_type = "text" if method == "addText" else ("shape" if method == "addShape" else ("image" if method == "addImage" else "chart"))
            boxes.append(
                JsLayoutBox(
                    element_type=element_type,
                    x=x,
                    y=y,
                    w=w,
                    h=h,
                    text_expr=first_arg,
                    options_raw=options_raw,
                    font_size=parse_js_float_option(options_raw, "fontSize") if method == "addText" else None,
                    align=parse_js_string_option(options_raw, "align") if method == "addText" else None,
                    bold=parse_js_bool_option(options_raw, "bold") if method == "addText" else None,
                    fit=parse_js_string_option(options_raw, "fit") if method == "addText" else None,
                )
            )
    return boxes


def extract_slide_method_calls(
    js_code: str,
    *,
    method: str,
    find_matching_delimiter: Callable[[str, int, str, str], int],
    split_top_level_args: Callable[[str], list[str]],
) -> list[tuple[str, str]]:
    token = f"slide.{method}("
    calls: list[tuple[str, str]] = []
    cursor = 0
    while True:
        start = js_code.find(token, cursor)
        if start < 0:
            break
        open_idx = start + len(token) - 1
        close_idx = find_matching_delimiter(js_code, open_idx, "(", ")")
        if close_idx < 0:
            cursor = start + len(token)
            continue
        args_raw = js_code[open_idx + 1 : close_idx]
        parts = split_top_level_args(args_raw)
        if len(parts) >= 2:
            calls.append((parts[0].strip(), parts[1].strip()))
        cursor = close_idx + 1
    return calls


def parse_js_float_option(options_raw: str, key: str) -> float | None:
    match = re.search(rf"\b{re.escape(key)}\s*:\s*(-?\d+(?:\.\d+)?)\b", options_raw)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def parse_js_string_option(options_raw: str, key: str) -> str | None:
    match = re.search(rf"\b{re.escape(key)}\s*:\s*(['\"])(.*?)\1", options_raw, flags=re.S)
    if not match:
        return None
    return match.group(2).strip()


def parse_js_bool_option(options_raw: str, key: str) -> bool | None:
    match = re.search(rf"\b{re.escape(key)}\s*:\s*(true|false)\b", options_raw)
    if not match:
        return None
    return match.group(1) == "true"


def is_js_page_badge_box(box: JsLayoutBox) -> bool:
    if box.x >= 9.1 and box.y >= 5.0 and box.w <= 0.7 and box.h <= 0.7:
        return True
    lowered = box.text_expr.lower()
    if "slideconfig.index" in lowered and box.w <= 0.8 and box.h <= 0.8:
        return True
    return False


def is_js_intentional_container_overlap(left: JsLayoutBox, right: JsLayoutBox) -> bool:
    if left.element_type == right.element_type:
        return False
    if "shape" not in {left.element_type, right.element_type}:
        return False
    container = left if left.element_type == "shape" else right
    inner = right if container is left else left
    tol = 0.08
    inside = (
        inner.x >= container.x - tol
        and inner.y >= container.y - tol
        and inner.x + inner.w <= container.x + container.w + tol
        and inner.y + inner.h <= container.y + container.h + tol
    )
    if not inside:
        return False
    if container.area <= 0:
        return False
    ratio = inner.area / container.area
    return 0.03 <= ratio <= 0.95


def js_box_overlap_ratio(left: JsLayoutBox, right: JsLayoutBox) -> float:
    x_overlap = max(0.0, min(left.x + left.w, right.x + right.w) - max(left.x, right.x))
    y_overlap = max(0.0, min(left.y + left.h, right.y + right.h) - max(left.y, right.y))
    if x_overlap <= 0 or y_overlap <= 0:
        return 0.0
    overlap_area = x_overlap * y_overlap
    min_area = min(left.area, right.area)
    if min_area <= 0:
        return 0.0
    return overlap_area / min_area


def js_major_block_gap(left: JsLayoutBox, right: JsLayoutBox) -> float | None:
    x_overlap = min(left.x + left.w, right.x + right.w) - max(left.x, right.x)
    y_overlap = min(left.y + left.h, right.y + right.h) - max(left.y, right.y)
    if x_overlap > 0:
        if left.y <= right.y:
            return max(0.0, right.y - (left.y + left.h))
        return max(0.0, left.y - (right.y + right.h))
    if y_overlap > 0:
        if left.x <= right.x:
            return max(0.0, right.x - (left.x + left.w))
        return max(0.0, left.x - (right.x + right.w))
    return None
