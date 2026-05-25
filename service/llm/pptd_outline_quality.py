from __future__ import annotations

import re

from ..models import OutlineNode, SlidePageType


def normalize_pptd_outline_nodes(nodes: list[OutlineNode]) -> None:
    """Shape model outlines into page plans the PPTD renderer can use."""
    for node in nodes:
        if node.page_type != SlidePageType.CONTENT:
            continue
        _normalize_gbn_sr_comparison(node)
        _normalize_strong_layout_signal(node)


def _normalize_gbn_sr_comparison(node: OutlineNode) -> None:
    joined = " ".join([node.title, *node.bullets]).lower()
    if "gbn" not in joined or "sr" not in joined:
        return

    existing_labels = {_label_key(item) for item in node.bullets}
    if {"gbn", "sr"}.issubset(existing_labels):
        node.layout_hint = "content-comparison"
        return

    gbn_points: list[str] = []
    sr_points: list[str] = []
    other_points: list[str] = []
    for bullet in node.bullets:
        text = _compact_text(bullet)
        if not text:
            continue
        lower = text.lower()
        if "gbn" in lower and "sr" not in lower:
            gbn_points.extend(_extract_labeled_points(text, "GBN"))
        elif "sr" in lower and "gbn" not in lower:
            sr_points.extend(_extract_labeled_points(text, "SR"))
        else:
            other_points.append(text)

    if not gbn_points or not sr_points:
        return

    node.layout_hint = "content-comparison"
    node.bullets = [
        "GBN：",
        *gbn_points[:3],
        "SR：",
        *sr_points[:3],
        *other_points[:2],
    ]


def _normalize_strong_layout_signal(node: OutlineNode) -> None:
    text = " ".join([node.title, *node.bullets]).lower()
    if "|" in text and any(keyword in text for keyword in ("指标", "metric", "性能", "利用率", "吞吐")):
        node.layout_hint = "content-stat-callout"
        return
    if _is_core_concept_page(text):
        node.layout_hint = "content-icon-rows"
        return
    if any(keyword in text for keyword in ("步骤", "流程", "过程", "机制", "sequence", "timeline")):
        if node.layout_hint not in {"content-comparison", "content-stat-callout"}:
            node.layout_hint = "content-timeline"


def has_strong_content_signal(node: OutlineNode) -> bool:
    text = " ".join([node.title, *node.bullets]).lower()
    return (
        _is_core_concept_page(text)
        or any(
            keyword in text
            for keyword in (
                "gbn",
                "sr",
                "crc",
                "arq",
                "ack",
                "对比",
                "比较",
                "差异",
                "指标",
                "性能",
                "利用率",
                "吞吐",
                "差错检测",
                "校验",
                "成帧",
                "滑动窗口",
            )
        )
        or any(keyword in text for keyword in ("步骤", "流程", "过程", "机制", "sequence", "timeline"))
        or any("|" in bullet for bullet in node.bullets)
        or _has_labeled_content_bullets(node)
    )


def has_toc_signal(node: OutlineNode) -> bool:
    text = " ".join([node.title, *node.bullets]).lower()
    return any(
        keyword in text
        for keyword in (
            "目录",
            "大纲",
            "学习路径",
            "课程结构",
            "roadmap",
            "agenda",
            "contents",
            "table of contents",
        )
    )


def _is_core_concept_page(text: str) -> bool:
    return any(
        keyword in text
        for keyword in (
            "核心概念",
            "基本概念",
            "基本构件",
            "关键构件",
            "三大功能",
            "组成",
            "定义",
            "概念图",
            "concept",
            "component",
            "building block",
        )
    )


def _has_labeled_content_bullets(node: OutlineNode) -> bool:
    labeled_count = 0
    for bullet in node.bullets:
        text = _compact_text(bullet)
        if not text:
            continue
        if re.match(r"^[^：:]{1,14}[：:]", text):
            labeled_count += 1
    return labeled_count >= 2


def _label_key(text: str) -> str:
    normalized = _compact_text(text).lower().rstrip(":：")
    if normalized == "gbn":
        return "gbn"
    if normalized == "sr":
        return "sr"
    return normalized


def _extract_labeled_points(text: str, label: str) -> list[str]:
    pattern = re.compile(
        rf"(?i)\b{re.escape(label)}\b\s*(?:[（(][^）)]*[）)])?\s*[:：：-]?\s*"
    )
    stripped = pattern.sub("", text, count=1)
    stripped = _compact_text(stripped)
    if not stripped:
        stripped = "关键机制与适用条件"
    return [_trim_point(stripped)]


def _trim_point(text: str) -> str:
    text = _compact_text(text)
    if len(text) <= 36:
        return text
    for delimiter in ("；", ";", "，", ","):
        head = text.split(delimiter, 1)[0].strip()
        if 8 <= len(head) <= 36:
            return head
    return text[:34].rstrip() + "..."


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()
