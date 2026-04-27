from __future__ import annotations

from typing import Any


def build_template_mapping_report() -> dict[str, Any]:
    return {
        "mode": "template",
        "slides": [],
        "unmapped_required": [],
        "passed": True,
    }


def build_template_chart_report() -> dict[str, Any]:
    return {
        "slides": [],
        "passed": True,
    }


def build_template_layout_report() -> dict[str, Any]:
    return {
        "slides": [],
        "passed": True,
    }


def build_slot_mapping_entry(*, slide_no: int, slots: list[dict[str, Any]]) -> dict[str, Any]:
    missing_required = [item for item in slots if item["required"] and not item["mapped"]]
    return {
        "slide_no": slide_no,
        "slot_count": len(slots),
        "mapped_count": sum(1 for item in slots if item["mapped"]),
        "missing_required": missing_required,
        "slots": slots,
    }


def build_slot_mapping_completed_payload(mapping_entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "slide_no": mapping_entry["slide_no"],
        "mapped_count": mapping_entry["mapped_count"],
        "slot_count": mapping_entry["slot_count"],
        "missing_required": mapping_entry["missing_required"],
    }


def build_template_layout_completed_payload(layout_entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "slide_no": int(layout_entry.get("slide_no", 0)),
        "box_count": int(layout_entry.get("box_count", 0)),
        "moved_count": int(layout_entry.get("moved_count", 0)),
        "issues_before_count": int(layout_entry.get("issues_before_count", 0)),
        "issues_after_count": int(layout_entry.get("issues_after_count", 0)),
        "passed": bool(layout_entry.get("passed", False)),
    }


def build_template_fidelity_payload(layout_entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "slide_no": int(layout_entry.get("slide_no", 0)),
        "fidelity_score": int(layout_entry.get("fidelity_score", 0)),
        "passed": bool(layout_entry.get("passed", False)),
    }


def build_chart_truth_checked_payload(*, slide_no: int, chart_entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "slide_no": slide_no,
        "has_verified_data": chart_entry.get("has_verified_data", False),
        "mode": chart_entry.get("mode", "none"),
        "source": chart_entry.get("source", ""),
    }
