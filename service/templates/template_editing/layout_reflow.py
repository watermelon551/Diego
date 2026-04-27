from __future__ import annotations

import re
from typing import Any

from ...run.types import LayoutBox, SLIDE_HEIGHT_EMU, SLIDE_WIDTH_EMU
from ..template_structure_rebuild import parse_xml_attrs


def analyze_and_reflow_template_layout(*, content: str, slide_no: int) -> tuple[str, dict[str, Any]]:
    boxes_before = extract_layout_boxes(content)
    before = collect_layout_issues(boxes_before)
    if not boxes_before:
        return (
            content,
            {
                "slide_no": slide_no,
                "box_count": 0,
                "moved_count": 0,
                "issues_before_count": 0,
                "issues_after_count": 0,
                "issues_before": [],
                "issues_after": [],
                "fidelity_score": 100,
                "passed": True,
            },
        )

    rewritten, moved_count = reflow_layout_boxes(content=content, boxes=boxes_before)
    boxes_after = extract_layout_boxes(rewritten) if moved_count else boxes_before
    after = collect_layout_issues(boxes_after)
    fidelity_score = compute_template_fidelity_score(
        box_count=len(boxes_before),
        moved_count=moved_count,
        issues_after_count=len(after["issues"]),
    )
    return (
        rewritten,
        {
            "slide_no": slide_no,
            "box_count": len(boxes_before),
            "moved_count": moved_count,
            "issues_before_count": len(before["issues"]),
            "issues_after_count": len(after["issues"]),
            "issues_before": before["issues"],
            "issues_after": after["issues"],
            "fidelity_score": fidelity_score,
            "passed": not after["issues"],
        },
    )


def extract_layout_boxes(content: str) -> list[LayoutBox]:
    boxes: list[LayoutBox] = []
    pattern = re.compile(r"<p:(sp|pic|graphicFrame)\b[\s\S]*?</p:\1>")
    for match in pattern.finditer(content):
        xml_tag = match.group(1)
        block = match.group(0)
        xfrm = re.search(r"<a:xfrm\b[^>]*>([\s\S]*?)</a:xfrm>", block)
        if not xfrm:
            continue
        xfrm_body = xfrm.group(1)
        off = re.search(r"<a:off\b[^>]*/>", xfrm_body)
        ext = re.search(r"<a:ext\b[^>]*/>", xfrm_body)
        if not off or not ext:
            continue
        off_attrs = parse_xml_attrs(off.group(0))
        ext_attrs = parse_xml_attrs(ext.group(0))
        try:
            x_emu = int(off_attrs.get("x", "0"))
            y_emu = int(off_attrs.get("y", "0"))
            w_emu = int(ext_attrs.get("cx", "0"))
            h_emu = int(ext_attrs.get("cy", "0"))
        except ValueError:
            continue
        if w_emu <= 0 or h_emu <= 0:
            continue
        rel_match = re.search(r"<a:blip\b[^>]*r:embed=\"([^\"]+)\"", block)
        rel_id = rel_match.group(1) if rel_match else None
        cnvpr = re.search(r"<p:cNvPr\b[^>]*/>", block)
        element_id = None
        if cnvpr:
            attrs = parse_xml_attrs(cnvpr.group(0))
            element_id = attrs.get("id") or attrs.get("name")
        element_type = layout_element_type(xml_tag=xml_tag, block=block)
        boxes.append(
            LayoutBox(
                element_type=element_type,
                xml_tag=xml_tag,
                block_start=match.start(),
                block_end=match.end(),
                x_emu=x_emu,
                y_emu=y_emu,
                w_emu=w_emu,
                h_emu=h_emu,
                rel_id=rel_id,
                element_id=element_id,
            )
        )
    return boxes


def layout_element_type(*, xml_tag: str, block: str) -> str:
    if xml_tag == "pic":
        hint = ""
        cnvpr = re.search(r"<p:cNvPr\b[^>]*/>", block)
        if cnvpr:
            attrs = parse_xml_attrs(cnvpr.group(0))
            hint = f"{attrs.get('name', '')} {attrs.get('descr', '')}".lower()
        if "icon" in hint:
            return "icon"
        if "logo" in hint:
            return "logo"
        return "image"
    if xml_tag == "graphicFrame":
        lowered = block.lower()
        if "<a:tbl" in lowered:
            return "table"
        if "chart" in lowered:
            return "chart"
        return "graphic"
    if "<p:txBody" in block:
        return "text"
    return "shape"


def collect_layout_issues(boxes: list[LayoutBox]) -> dict[str, Any]:
    issues: list[str] = []
    for idx, box in enumerate(boxes, start=1):
        if box.x_emu < 0 or box.y_emu < 0:
            issues.append(f"box-{idx} negative position")
            continue
        if box.x_emu + box.w_emu > SLIDE_WIDTH_EMU or box.y_emu + box.h_emu > SLIDE_HEIGHT_EMU:
            issues.append(f"box-{idx} out of slide bounds")
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if boxes_overlap_significantly(boxes[i], boxes[j]):
                issues.append(f"box-{i + 1} overlaps box-{j + 1}")
    return {"issues": issues}


def boxes_overlap_significantly(left: LayoutBox, right: LayoutBox) -> bool:
    x_overlap = max(0, min(left.x_emu + left.w_emu, right.x_emu + right.w_emu) - max(left.x_emu, right.x_emu))
    y_overlap = max(0, min(left.y_emu + left.h_emu, right.y_emu + right.h_emu) - max(left.y_emu, right.y_emu))
    if x_overlap <= 0 or y_overlap <= 0:
        return False
    overlap_area = x_overlap * y_overlap
    min_area = min(left.w_emu * left.h_emu, right.w_emu * right.h_emu)
    if min_area <= 0:
        return False
    return overlap_area / min_area >= 0.08


def reflow_layout_boxes(*, content: str, boxes: list[LayoutBox]) -> tuple[str, int]:
    if not boxes:
        return content, 0
    gap = 120_000
    ordered = sorted(range(len(boxes)), key=lambda idx: (boxes[idx].y_emu, boxes[idx].x_emu))
    adjusted: list[tuple[int, int, int, int]] = [(b.x_emu, b.y_emu, b.w_emu, b.h_emu) for b in boxes]
    placed: list[tuple[int, int, int, int]] = []
    moved_count = 0

    for idx in ordered:
        x_emu, y_emu, w_emu, h_emu = adjusted[idx]
        if w_emu > SLIDE_WIDTH_EMU or h_emu > SLIDE_HEIGHT_EMU:
            placed.append((x_emu, y_emu, w_emu, h_emu))
            continue
        x_emu = min(max(0, x_emu), SLIDE_WIDTH_EMU - w_emu)
        y_emu = min(max(0, y_emu), SLIDE_HEIGHT_EMU - h_emu)
        attempts = 0
        while attempts < 24:
            overlaps = [
                item
                for item in placed
                if rect_overlap_significant(
                    x_emu=x_emu,
                    y_emu=y_emu,
                    w_emu=w_emu,
                    h_emu=h_emu,
                    other=item,
                )
            ]
            if not overlaps:
                break
            lowest_bottom = max(other[1] + other[3] for other in overlaps)
            candidate_y = lowest_bottom + gap
            if candidate_y + h_emu > SLIDE_HEIGHT_EMU:
                break
            y_emu = candidate_y
            attempts += 1
        adjusted[idx] = (x_emu, y_emu, w_emu, h_emu)
        placed.append((x_emu, y_emu, w_emu, h_emu))
        if x_emu != boxes[idx].x_emu or y_emu != boxes[idx].y_emu:
            moved_count += 1

    if moved_count == 0:
        return content, 0
    updates: list[tuple[int, int, str]] = []
    for idx, box in enumerate(boxes):
        x_emu, y_emu, _, _ = adjusted[idx]
        if x_emu == box.x_emu and y_emu == box.y_emu:
            continue
        block = content[box.block_start:box.block_end]
        rewritten = rewrite_box_off_tag(block=block, x_emu=x_emu, y_emu=y_emu)
        updates.append((box.block_start, box.block_end, rewritten))
    if not updates:
        return content, 0
    updates.sort(key=lambda item: item[0])
    out: list[str] = []
    cursor = 0
    for start, end, payload in updates:
        out.append(content[cursor:start])
        out.append(payload)
        cursor = end
    out.append(content[cursor:])
    return "".join(out), moved_count


def rect_overlap_significant(
    *,
    x_emu: int,
    y_emu: int,
    w_emu: int,
    h_emu: int,
    other: tuple[int, int, int, int],
) -> bool:
    ox, oy, ow, oh = other
    x_overlap = max(0, min(x_emu + w_emu, ox + ow) - max(x_emu, ox))
    y_overlap = max(0, min(y_emu + h_emu, oy + oh) - max(y_emu, oy))
    if x_overlap <= 0 or y_overlap <= 0:
        return False
    overlap_area = x_overlap * y_overlap
    min_area = min(w_emu * h_emu, ow * oh)
    if min_area <= 0:
        return False
    return overlap_area / min_area >= 0.08


def rewrite_box_off_tag(*, block: str, x_emu: int, y_emu: int) -> str:
    def repl(match: re.Match[str]) -> str:
        attrs = parse_xml_attrs(match.group(0))
        attrs["x"] = str(x_emu)
        attrs["y"] = str(y_emu)
        attrs_str = " ".join(f'{key}="{xml_attr_escape(value)}"' for key, value in attrs.items())
        return f"<a:off {attrs_str}/>"

    return re.sub(r"<a:off\b[^>]*/>", repl, block, count=1)


def compute_template_fidelity_score(*, box_count: int, moved_count: int, issues_after_count: int) -> int:
    if box_count <= 0:
        return 100
    move_ratio = moved_count / box_count
    move_penalty = int(move_ratio * 55)
    issue_penalty = min(45, issues_after_count * 15)
    return max(0, 100 - move_penalty - issue_penalty)


def xml_attr_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
