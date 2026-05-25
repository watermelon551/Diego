from __future__ import annotations

import re
from typing import Any


def pptd_source_notes_from_report(
    report: dict[str, Any],
    *,
    slide_count: int,
) -> list[str]:
    focus = report.get("page_focus") if isinstance(report, dict) else []
    if not isinstance(focus, list):
        focus = []
    notes = [_source_note_from_focus_item(item) for item in focus[:slide_count]]
    if len(notes) < slide_count:
        notes.extend([""] * (slide_count - len(notes)))
    return notes


def _source_note_from_focus_item(value: Any) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    label = text.split(":", 1)[0].strip()
    if len(label) > 48:
        label = text[:48].strip()
    label = re.sub(r"\s+", " ", label)
    return label
