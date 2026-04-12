from __future__ import annotations

import re
from typing import Any, Callable


def collect_addimage_signature_issues(
    js_code: str,
    *,
    extract_method_call_args: Callable[[str, str], list[list[str]]],
    dedupe: Callable[[list[str]], list[str]],
) -> list[str]:
    issues: list[str] = []
    calls = extract_method_call_args(str(js_code or ""), r"\bslide\.addImage\s*\(")
    for args in calls:
        if len(args) != 1:
            issues.append("addImage call signature invalid: use addImage({ path|data, ...options })")
            continue
        options = str(args[0]).strip()
        if not options.startswith("{"):
            issues.append("addImage call signature invalid: options must be object literal")
            continue
        if not re.search(r"\b(?:path|data)\s*:", options):
            issues.append("addImage call signature invalid: object must include path or data")
    return dedupe(issues)


def collect_addtext_signature_issues(
    js_code: str,
    *,
    extract_method_call_args: Callable[[str, str], list[list[str]]],
    dedupe: Callable[[list[str]], list[str]],
) -> list[str]:
    issues: list[str] = []
    calls = extract_method_call_args(str(js_code or ""), r"\bslide\.addText\s*\(")
    for args in calls:
        if len(args) != 2:
            issues.append("addText call signature invalid: use addText(textOrRuns, { ...options })")
            continue
        options = str(args[1]).strip()
        if not options.startswith("{"):
            issues.append("addText call signature invalid: options must be object literal")
    return dedupe(issues)


def collect_addshape_signature_issues(
    js_code: str,
    *,
    extract_method_call_args: Callable[[str, str], list[list[str]]],
    dedupe: Callable[[list[str]], list[str]],
) -> list[str]:
    issues: list[str] = []
    calls = extract_method_call_args(str(js_code or ""), r"\bslide\.addShape\s*\(")
    for args in calls:
        if len(args) != 2:
            issues.append("addShape call signature invalid: use addShape(pres.shapes.X, { ...options })")
            continue
        options = str(args[1]).strip()
        if not options.startswith("{"):
            issues.append("addShape call signature invalid: options must be object literal")
    return dedupe(issues)


def canonicalize_addimage_signature(
    js_code: str,
    *,
    split_top_level_args: Callable[[str], list[str]],
    find_matching_delimiter: Callable[[str, int, str, str], int],
) -> tuple[str, int]:
    payload = str(js_code or "")
    token = "slide.addImage("
    cursor = 0
    out: list[str] = []
    fix_count = 0
    while True:
        start = payload.find(token, cursor)
        if start < 0:
            out.append(payload[cursor:])
            break
        out.append(payload[cursor:start])
        open_idx = start + len(token) - 1
        close_idx = find_matching_delimiter(payload, open_idx, "(", ")")
        if close_idx < 0:
            out.append(payload[start:])
            break
        args_raw = payload[open_idx + 1 : close_idx]
        args = split_top_level_args(args_raw)
        replacement = payload[start : close_idx + 1]
        if len(args) == 2:
            path_expr = str(args[0]).strip()
            opts_expr = str(args[1]).strip()
            if opts_expr.startswith("{") and opts_expr.endswith("}") and not re.search(r"\b(?:path|data)\s*:", opts_expr):
                body = opts_expr[1:-1].strip()
                merged = f"path: {path_expr}"
                if body:
                    merged += f", {body}"
                replacement = f"slide.addImage({{ {merged} }})"
                fix_count += 1
        out.append(replacement)
        cursor = close_idx + 1
    return "".join(out), fix_count


def extract_planned_asset_paths(*, js_code: str, slide_plan: dict[str, Any] | None, dedupe: Callable[[list[str]], list[str]]) -> list[str]:
    paths: list[str] = []
    visual_plan = slide_plan.get("visual_plan") if isinstance(slide_plan, dict) and isinstance(slide_plan.get("visual_plan"), dict) else {}
    assets = visual_plan.get("assets", []) if isinstance(visual_plan, dict) and isinstance(visual_plan.get("assets"), list) else []
    for item in assets:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).strip()
        if path:
            paths.append(path)
    match = re.search(r"\bassets\s*:\s*\[([\s\S]{0,4000}?)\]", str(js_code or ""))
    if match:
        for item in re.findall(r"\bpath\s*:\s*['\"]([^'\"]+)['\"]", match.group(1)):
            path = str(item).strip()
            if path:
                paths.append(path)
    return dedupe(paths)


def extract_main_asset_path(*, js_code: str, slide_plan: dict[str, Any] | None, dedupe: Callable[[list[str]], list[str]]) -> str:
    if isinstance(slide_plan, dict):
        visual_plan = slide_plan.get("visual_plan")
        if isinstance(visual_plan, dict):
            assets = visual_plan.get("assets")
            if isinstance(assets, list):
                for item in assets:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("slot", "")).strip().lower() == "main":
                        path = str(item.get("path", "")).strip()
                        if path:
                            return path
                for item in assets:
                    if not isinstance(item, dict):
                        continue
                    path = str(item.get("path", "")).strip()
                    if path:
                        return path
    match = re.search(
        r"\bassets\s*:\s*\[[\s\S]{0,4000}?\{\s*slot\s*:\s*['\"]main['\"][\s\S]{0,400}?\bpath\s*:\s*['\"]([^'\"]+)['\"]",
        str(js_code or ""),
        flags=re.IGNORECASE,
    )
    if match:
        return str(match.group(1)).strip()
    candidates = extract_planned_asset_paths(js_code=js_code, slide_plan=slide_plan, dedupe=dedupe)
    return candidates[0] if candidates else ""


def has_image_placeholder_text(js_code: str) -> bool:
    lowered = str(js_code or "").lower()
    return bool(
        re.search(
            r"\[(?:[^\]]{0,20})?(主视觉|辅助图|流程图|示意图|占位|placeholder|image|visual)(?:[^\]]{0,20})?\]",
            lowered,
        )
    )


def collect_detected_api_violations(js_code: str) -> list[str]:
    checks = [
        ("pres.shapes.ELLIPSE", "use OVAL instead of ELLIPSE"),
        ("pres.shapes.RT_TRIANGLE", "use RIGHT_TRIANGLE instead of RT_TRIANGLE"),
        ("slide.addPageBadge(", "slide.addPageBadge is invalid; use addPageBadge helper"),
        ("addGroup(", "addGroup is not supported in this runtime"),
        ("createCanvas(", "createCanvas is unsupported runtime dependency"),
        ("slide.background(", "slide.background(...) call is invalid; use assignment"),
        ("pres.utilitextfit(", "pres.utilitextfit is not a valid pptxgenjs API"),
    ]
    lowered = str(js_code or "")
    hits: list[str] = []
    for marker, desc in checks:
        if marker in lowered:
            hits.append(desc)
    return hits
