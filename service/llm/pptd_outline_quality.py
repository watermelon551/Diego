from __future__ import annotations

import re

from ..models import OutlineNode, SlidePageType


def normalize_pptd_outline_nodes(nodes: list[OutlineNode]) -> None:
    """Shape model outlines into page plans the PPTD renderer can use."""
    for node in nodes:
        if node.page_type != SlidePageType.CONTENT:
            continue
        _normalize_protocol_comparison(node)
        _normalize_strong_layout_signal(node)


def _normalize_protocol_comparison(node: OutlineNode) -> None:
    joined = " ".join([node.title, *node.bullets]).lower()
    if not _has_protocol_pair_signal(joined):
        return

    existing_labels = {_heading_label_key(item) for item in node.bullets}
    if (
        {"gbn", "sr"}.issubset(existing_labels)
        or {"回退n帧", "选择重传"}.issubset(existing_labels)
    ):
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
        if _has_gbn_signal(lower) and not _has_sr_signal(lower):
            gbn_points.extend(_extract_labeled_points(text, "GBN"))
        elif _has_sr_signal(lower) and not _has_gbn_signal(lower):
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
    if node.layout_hint == "content-comparison" and _has_comparison_signal(text):
        return
    if _has_metric_signal(text, node):
        node.layout_hint = "content-stat-callout"
        return
    if _has_comparison_signal(text):
        node.layout_hint = "content-comparison"
        return
    if _is_core_concept_page(text):
        node.layout_hint = "content-icon-rows"
        return
    if any(keyword in text for keyword in ("步骤", "流程", "过程", "机制", "sequence", "timeline")):
        if node.layout_hint not in {"content-comparison", "content-stat-callout"}:
            node.layout_hint = "content-timeline"
            return
    if node.layout_hint in {
        "content-comparison",
        "content-stat-callout",
        "content-timeline",
    }:
        node.layout_hint = "content-icon-rows" if _has_labeled_content_bullets(node) else "content-showcase"


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
    if any(
        keyword in text
        for keyword in (
            "目录",
            "大纲",
            "导览",
            "学习路径",
            "课程结构",
            "课程内容",
            "roadmap",
            "agenda",
            "contents",
            "table of contents",
        )
    ):
        return True
    numbered = sum(1 for bullet in node.bullets if re.match(r"^\s*\d+[.)、]\s*", str(bullet)))
    return numbered >= 3


def _has_protocol_pair_signal(text: str) -> bool:
    return _has_gbn_signal(text) and _has_sr_signal(text)


def _has_gbn_signal(text: str) -> bool:
    return "gbn" in text or "go-back-n" in text or "回退n" in text or "后退n" in text


def _has_sr_signal(text: str) -> bool:
    return (
        re.search(r"(?<![a-z0-9])sr(?![a-z0-9])", text) is not None
        or "选择重传" in text
        or "selective repeat" in text
    )


def _has_comparison_signal(text: str) -> bool:
    return any(
        keyword in text
        for keyword in (
            " vs ",
            "对比",
            "比较",
            "差异",
            "优劣",
            "取舍",
            "versus",
            "compare",
            "comparison",
        )
    ) or _has_protocol_pair_signal(text)


def _has_metric_signal(text: str, node: OutlineNode) -> bool:
    return (
        any("|" in bullet for bullet in node.bullets)
        and any(keyword in text for keyword in ("指标", "metric", "性能", "利用率", "吞吐"))
    ) or any(
        keyword in text
        for keyword in (
            "指标",
            "性能",
            "量化",
            "利用率",
            "吞吐",
            "吞吐量",
            "延迟",
            "时延",
            "rtt",
            "带宽时延积",
            "窗口大小",
            "信道利用率",
            "metric",
            "ratio",
            "throughput",
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
    label = normalized.split("：", 1)[0].split(":", 1)[0].strip()
    if _has_gbn_signal(label):
        return "gbn"
    if _has_sr_signal(label):
        return "sr"
    return normalized


def _heading_label_key(text: str) -> str:
    normalized = _compact_text(text).lower().rstrip(":：")
    if not normalized or ("：" in normalized or ":" in normalized):
        return normalized
    return _label_key(normalized)


def _extract_labeled_points(text: str, label: str) -> list[str]:
    if label == "GBN":
        pattern = re.compile(r"(?i)(?:\bGBN\b|go-back-n|回退N?帧|后退N?帧)\s*(?:[（(][^）)]*[）)])?\s*[:：：-]?\s*")
    elif label == "SR":
        pattern = re.compile(r"(?i)(?:\bSR\b|selective repeat|选择重传)\s*(?:[（(][^）)]*[）)])?\s*[:：：-]?\s*")
    else:
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
    return text[:36].rstrip(" ：:，,、；;。.!！?？")


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()
