from __future__ import annotations

import re


def classify_slide_issues(issues: list[str], *, dedupe_preserve_order) -> dict[str, list[str]]:
    blocking_markers = (
        "candidate build failed",
        "missing export contract",
        "createSlide signature invalid",
        "createSlide must be synchronous",
        "preview compile failed",
        "preview pptx missing",
        "out of slide bounds",
        "overlaps box",
        "visual_policy violation",
        "forbidden api detected",
        "forbidden runtime dependency",
        "addShape must use pres.shapes enum",
        "addText call signature invalid",
        "addShape call signature invalid",
        "addImage call signature invalid",
        "line shape geometry invalid",
        "hex color with # is forbidden",
        "8-char hex color is forbidden",
        "visual assets planned but addImage() missing",
        "visual assets planned but main image path not used",
        "image placeholder text remains while visual assets are planned",
        "llm_output_not_executable",
    )
    high_risk_markers = (
        "body text must be left-aligned",
        "body text should not use bold",
        "body text missing fit:'shrink'",
        "title missing fit:'shrink'",
        "title font too small",
        "title/body size contrast too weak",
        "missing required page badge position",
        "margin too tight",
        "gap too tight",
        "content slide missing non-text visual element",
        "theme key usage incomplete",
    )

    blocking: list[str] = []
    high_risk: list[str] = []
    warnings: list[str] = []
    for issue in issues:
        text = str(issue).strip()
        if not text:
            continue
        lowered = text.lower()
        if any(marker.lower() in lowered for marker in blocking_markers):
            blocking.append(text)
        elif any(marker.lower() in lowered for marker in high_risk_markers):
            high_risk.append(text)
        else:
            warnings.append(text)

    return {
        "blocking": dedupe_preserve_order(blocking),
        "high_risk": dedupe_preserve_order(high_risk),
        "warnings": dedupe_preserve_order(warnings),
    }


def local_quality_score(*, classified: dict[str, list[str]]) -> int:
    blocking = len(classified.get("blocking", []))
    high_risk = len(classified.get("high_risk", []))
    warnings = len(classified.get("warnings", []))
    score = 100 - blocking * 24 - high_risk * 12 - warnings * 3
    return max(0, min(100, score))


def build_local_repair_directives(*, classified: dict[str, list[str]], dedupe_preserve_order) -> list[str]:
    blocking = classified.get("blocking", [])
    high_risk = classified.get("high_risk", [])
    directives: list[str] = []

    if any("export" in item.lower() or "signature" in item.lower() for item in blocking):
        directives.append("Enforce contract exactly: function createSlide(pres, theme) + module.exports = { createSlide, slideConfig }.")
    if any("preview compile failed" in item.lower() or "forbidden api" in item.lower() for item in blocking):
        directives.append("Use pptxgenjs legal API only: slide.background = { color: theme.bg }; addShape with pres.shapes.*; never ShapeType/slide.shapes/addGroup.")
    if any("line shape geometry invalid" in item.lower() for item in blocking):
        directives.append("For pres.shapes.LINE always keep both w and h > 0 (e.g., h: 0.01), never zero-length geometry.")
    if any("addtext call signature invalid" in item.lower() or "addshape call signature invalid" in item.lower() for item in blocking):
        directives.append("Call signatures must be strict: addText(textOrRuns, { ...opts }) and addShape(pres.shapes.X, { ...opts }); never pass style as 3rd arg or positional x,y,w,h.")
    if any("addimage call signature invalid" in item.lower() for item in blocking):
        directives.append("Use strict image API signature only: slide.addImage({ path|data, x, y, w, h, ...opts }); never addImage(path, opts).")
    if any("visual assets planned but addimage() missing" in item.lower() or "main image path not used" in item.lower() for item in blocking):
        directives.append("When visual assets are planned, consume slot='main' via explicit addImage({ path: <main-path>, ... }).")
    if any("image placeholder text remains while visual assets are planned" in item.lower() for item in blocking + high_risk):
        directives.append("Remove image placeholder labels and render real images from visual_plan.assets instead.")
    if any("out of slide bounds" in item.lower() or "overlaps" in item.lower() for item in blocking + high_risk):
        directives.append("Reflow layout with safe margins and non-overlap: content margins >=0.5in, preserve 0.22in+ block gap.")
    if any("page badge" in item.lower() for item in blocking):
        directives.append("Add page badge on non-cover slides via addPageBadge() at x:9.3, y:5.1.")
    if any("left-aligned" in item.lower() for item in high_risk):
        directives.append("Left-align body paragraphs/lists; center only title or badge text.")
    if any("fit:'shrink'" in item.lower() for item in high_risk):
        directives.append("Apply fit:'shrink' to title and long body text blocks to prevent overflow.")
    if any("title font too small" in item.lower() or "size contrast" in item.lower() for item in high_risk):
        directives.append("Strengthen hierarchy: title >=36pt and at least 18pt larger than body text.")
    if any("content slide missing non-text visual element" in item.lower() for item in high_risk):
        directives.append("Ensure content slide contains at least one non-text element: addShape/addImage/addChart.")

    if not directives and (blocking or high_risk):
        directives.append("Fix all blocking/high-risk issues without changing the slide topic, page type, or narrative intent.")

    return dedupe_preserve_order(directives)


def issues_have_fatal_markers(issues: list[str]) -> bool:
    markers = (
        "missing export contract",
        "createSlide signature invalid",
        "createSlide must be synchronous",
        "preview compile failed",
        "preview pptx missing",
        "jsondecodeerror",
        "llm_output_not_executable",
    )
    for issue in issues:
        text = str(issue)
        if any(marker in text for marker in markers):
            return True
    return False


def fallback_quality_gate(*, hard_issues: list[str], preview_text: str, candidate_js: str) -> dict[str, object]:
    score = 92 - len(hard_issues) * 15
    text = (preview_text or "").strip()
    lowered = candidate_js.lower()
    issues: list[str] = []
    directives: list[str] = []
    if len(text) < 20:
        score -= 18
        issues.append("preview text too short")
        directives.append("expand concrete natural-language copy")
    if re.search(r"(placeholder|lorem|ipsum|todo|xxxx|\[[^\]]*(主视觉|辅助图|流程图|示意图|image)\])", lowered):
        score -= 25
        issues.append("placeholder-like code/text remains")
        directives.append("replace placeholders with natural language")
    score = max(0, min(100, int(score)))
    return {"score": score, "issues": issues, "repair_directives": directives}
