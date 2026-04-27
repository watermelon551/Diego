from __future__ import annotations

from typing import Any


def build_slide_generated_preview_payload(
    *,
    slide_no: int,
    status: str,
    preview: dict[str, Any],
) -> dict[str, Any]:
    return {
        "slide_no": slide_no,
        "status": status,
        "preview": preview.get("preview"),
        "preview_format": "svg",
        "svg_data_url": preview.get("svg_data_url"),
        "preview_width": preview.get("width", 1280),
        "preview_height": preview.get("height", 720),
        "is_final": True,
    }


def build_regeneration_rule_violations(
    *,
    instruction: str,
    preserve_style: bool,
) -> list[str]:
    rule_violations = [instruction]
    if preserve_style:
        rule_violations.append(
            "Preserve the current visual style unless the instruction explicitly changes it."
        )
    return rule_violations
