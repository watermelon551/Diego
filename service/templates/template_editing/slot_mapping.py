from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from ...run.types import SlotGraph, SlotNode
from ..template_structure_rebuild import parse_xml_attrs


def build_slot_graph(*, slide_xml: Path, slide_no: int) -> SlotGraph:
    text = slide_xml.read_text(encoding="utf-8", errors="ignore")
    graph = SlotGraph(slide_no=slide_no, slots=[])
    placeholder_re = re.compile(
        r"(placeholder|lorem|ipsum|xxxx|template|caption|insert|click to add|text here|your text)",
        flags=re.IGNORECASE,
    )
    text_hits = re.findall(r"<a:t>(.*?)</a:t>", text, flags=re.DOTALL)
    for idx, raw in enumerate(text_hits, start=1):
        plain = html.unescape(raw).strip()
        if not plain:
            continue
        if not placeholder_re.search(plain):
            continue
        lowered = plain.lower()
        slot_type = "caption" if "caption" in lowered else "text"
        graph.slots.append(
            SlotNode(
                slot_id=f"text-{idx}",
                slot_type=slot_type,
                required=True,
                hint=plain,
                group_id=f"text-{idx}",
            )
        )

    picture_slots = extract_picture_slots(text)
    for idx, slot in enumerate(picture_slots, start=1):
        graph.slots.append(
            SlotNode(
                slot_id=f"pic-{idx}",
                slot_type=str(slot["slot_type"]),
                required=True,
                rel_id=str(slot["rel_id"]),
                hint=str(slot["slot_type"]),
                group_id=f"pic-{idx}",
            )
        )

    rels_path = slide_xml.parent / "_rels" / f"{slide_xml.name}.rels"
    if rels_path.exists():
        rels_text = rels_path.read_text(encoding="utf-8", errors="ignore")
        chart_idx = 0
        for tag in re.findall(r"<Relationship\b[^>]*/>", rels_text):
            attrs = parse_xml_attrs(tag)
            rel_type = attrs.get("Type", "")
            rel_id = attrs.get("Id", "")
            if rel_type.endswith("/chart") and rel_id:
                chart_idx += 1
                graph.slots.append(
                    SlotNode(
                        slot_id=f"chart-{chart_idx}",
                        slot_type="chart",
                        required=True,
                        rel_id=rel_id,
                        hint="chart",
                        group_id=f"chart-{chart_idx}",
                    )
                )

    known_ids = {slot.rel_id for slot in graph.slots if slot.rel_id}
    for idx, tag in enumerate(re.findall(r"<p:cNvPr\b[^>]*/>", text), start=1):
        attrs = parse_xml_attrs(tag)
        name = attrs.get("name", "")
        descr = attrs.get("descr", "")
        hint = f"{name} {descr}".strip()
        hint_lower = hint.lower()
        if not hint or not placeholder_re.search(hint):
            continue
        if any(word in hint_lower for word in ("text", "caption")):
            continue
        if any(word in hint_lower for word in ("image", "icon", "logo", "chart")):
            continue
        slot_id = attrs.get("id", f"unknown-{idx}")
        if slot_id in known_ids:
            continue
        graph.slots.append(
            SlotNode(
                slot_id=f"unknown-{slot_id}",
                slot_type="unknown",
                required=True,
                hint=hint,
                group_id=f"unknown-{slot_id}",
            )
        )
    return graph


def plan_slot_mapping(*, slot_graph: SlotGraph) -> dict[str, Any]:
    slots: list[dict[str, Any]] = []
    for slot in slot_graph.slots:
        mapped = slot.slot_type in {"text", "caption", "image", "icon", "logo", "chart"}
        reason = "" if mapped else "unsupported placeholder type"
        slots.append(
            {
                "slot_id": slot.slot_id,
                "slot_type": slot.slot_type,
                "required": slot.required,
                "mapped": mapped,
                "reason": reason,
                "hint": slot.hint,
                "rel_id": slot.rel_id,
                "group_id": slot.group_id,
            }
        )
    return {"slide_no": slot_graph.slide_no, "slots": slots}


def extract_picture_slots(slide_text: str) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for match in re.finditer(r"<p:pic\b[\s\S]*?</p:pic>", slide_text):
        block = match.group(0)
        blip = re.search(r"<a:blip\b[^>]*r:embed=\"([^\"]+)\"", block)
        if not blip:
            continue
        rel_id = blip.group(1)
        cnvpr = re.search(r"<p:cNvPr\b[^>]*/>", block)
        hint = ""
        if cnvpr:
            attrs = parse_xml_attrs(cnvpr.group(0))
            hint = f"{attrs.get('name', '')} {attrs.get('descr', '')}".lower()
        if "icon" in hint:
            slot_type = "icon"
        elif "logo" in hint:
            slot_type = "logo"
        else:
            slot_type = "image"
        slots.append(
            {
                "rel_id": rel_id,
                "slot_type": slot_type,
                "start": match.start(),
                "end": match.end(),
            }
        )
    return slots
