from __future__ import annotations

import html
import httpx
import os
import random
import re
import shutil
import struct
import zlib
from pathlib import Path
from typing import Any

from ..models import OutlineNode
from ..run.types import (
    ChartFact,
    ChartPlan,
    LayoutBox,
    SlotGraph,
    SlotNode,
    TemplateAssetError,
    TemplateLayoutConflictError,
    TemplateSlotMappingError,
    SLIDE_HEIGHT_EMU,
    SLIDE_WIDTH_EMU,
)

class TemplateOpsMixin:
    def _rebuild_template_structure(self, *, unpacked: Path, target_count: int) -> list[Path]:
        self._ensure_template_structure_files(unpacked=unpacked)
        slides_dir = unpacked / "ppt" / "slides"
        slide_rels_dir = slides_dir / "_rels"
        presentation_path = unpacked / "ppt" / "presentation.xml"
        presentation_rels_path = unpacked / "ppt" / "_rels" / "presentation.xml.rels"
        content_types_path = unpacked / "[Content_Types].xml"

        presentation_text = presentation_path.read_text(encoding="utf-8", errors="ignore")
        presentation_rels_text = presentation_rels_path.read_text(encoding="utf-8", errors="ignore")
        content_types_text = content_types_path.read_text(encoding="utf-8", errors="ignore")

        existing_order = self._resolve_slide_targets_from_relationships(
            presentation_text=presentation_text,
            presentation_rels_text=presentation_rels_text,
        )
        if not existing_order:
            existing_order = sorted(
                [p.relative_to(unpacked / "ppt").as_posix() for p in slides_dir.glob("slide*.xml")],
                key=self._slide_target_sort_key,
            )
        if not existing_order:
            existing_order = ["slides/slide1.xml"]
            self._write_default_slide_xml(slides_dir / "slide1.xml")

        target_count = max(1, target_count)
        mapped_sources = [existing_order[i % len(existing_order)] for i in range(target_count)]
        final_targets = [f"slides/slide{i}.xml" for i in range(1, target_count + 1)]

        used_source_files: set[str] = set()
        for i, src_target in enumerate(mapped_sources, start=1):
            src_path = unpacked / "ppt" / src_target
            if not src_path.exists():
                self._write_default_slide_xml(src_path)
            dst_rel = f"slides/slide{i}.xml"
            dst_path = unpacked / "ppt" / dst_rel
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            if src_path.resolve() == dst_path.resolve() and src_target not in used_source_files:
                used_source_files.add(src_target)
            else:
                shutil.copy2(src_path, dst_path)
                used_source_files.add(src_target)

            src_rel = slide_rels_dir / f"{Path(src_target).stem}.xml.rels"
            dst_rel_file = slide_rels_dir / f"slide{i}.xml.rels"
            if src_rel.exists():
                if src_rel.resolve() != dst_rel_file.resolve():
                    shutil.copy2(src_rel, dst_rel_file)
            else:
                dst_rel_file.unlink(missing_ok=True)

        self._cleanup_orphan_slide_files(slides_dir=slides_dir, keep_targets=set(final_targets))
        self._cleanup_orphan_slide_rels(slide_rels_dir=slide_rels_dir, keep_slide_numbers=set(range(1, target_count + 1)))

        updated_rels, rid_sequence = self._rebuild_presentation_relationships(
            rels_text=presentation_rels_text,
            final_targets=final_targets,
        )
        updated_presentation = self._rebuild_presentation_slide_list(
            presentation_text=presentation_text,
            rid_sequence=rid_sequence,
        )
        updated_content_types = self._rebuild_content_types_overrides(
            content_types_text=content_types_text,
            final_targets=final_targets,
        )

        presentation_rels_path.write_text(updated_rels, encoding="utf-8")
        presentation_path.write_text(updated_presentation, encoding="utf-8")
        content_types_path.write_text(updated_content_types, encoding="utf-8")
        return [unpacked / "ppt" / target for target in final_targets]

    def _resolve_slide_targets_from_relationships(self, *, presentation_text: str, presentation_rels_text: str) -> list[str]:
        rid_to_target: dict[str, str] = {}
        for tag in re.findall(r"<Relationship\b[^>]*/>", presentation_rels_text):
            attrs = self._parse_xml_attrs(tag)
            rel_type = attrs.get("Type", "")
            target = attrs.get("Target", "").replace("\\", "/")
            if rel_type.endswith("/slide") and target.startswith("slides/"):
                rid_to_target[attrs.get("Id", "")] = target
        ordered: list[str] = []
        for rid in re.findall(r'r:id="([^"]+)"', presentation_text):
            target = rid_to_target.get(rid)
            if target:
                ordered.append(target)
        return ordered

    def _rebuild_presentation_relationships(self, *, rels_text: str, final_targets: list[str]) -> tuple[str, list[str]]:
        relationship_tags = re.findall(r"<Relationship\b[^>]*/>", rels_text)
        non_slide_tags: list[str] = []
        used_ids: set[str] = set()
        for tag in relationship_tags:
            attrs = self._parse_xml_attrs(tag)
            rel_type = attrs.get("Type", "")
            rel_id = attrs.get("Id", "")
            if rel_id:
                used_ids.add(rel_id)
            if rel_type.endswith("/slide"):
                continue
            non_slide_tags.append(tag)

        rid_sequence: list[str] = []
        slide_tags: list[str] = []
        for target in final_targets:
            rid = self._next_rid(used_ids)
            rid_sequence.append(rid)
            slide_tags.append(
                f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="{target}"/>'
            )
            used_ids.add(rid)

        body = "\n".join(non_slide_tags + slide_tags)
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            f"{body}\n"
            "</Relationships>\n",
            rid_sequence,
        )

    def _rebuild_presentation_slide_list(self, *, presentation_text: str, rid_sequence: list[str]) -> str:
        max_slide_id = 255
        for value in re.findall(r"<p:sldId\b[^>]*\bid=\"(\d+)\"", presentation_text):
            try:
                max_slide_id = max(max_slide_id, int(value))
            except ValueError:
                pass
        next_id = max_slide_id + 1
        sld_entries: list[str] = []
        for rid in rid_sequence:
            sld_entries.append(f'    <p:sldId id="{next_id}" r:id="{rid}"/>')
            next_id += 1
        block = "<p:sldIdLst>\n" + "\n".join(sld_entries) + "\n  </p:sldIdLst>"
        if "<p:sldIdLst>" in presentation_text and "</p:sldIdLst>" in presentation_text:
            return re.sub(
                r"<p:sldIdLst>.*?</p:sldIdLst>",
                block,
                presentation_text,
                flags=re.DOTALL,
            )
        insert_at = presentation_text.find(">", presentation_text.find("<p:presentation"))
        if insert_at == -1:
            return presentation_text
        return presentation_text[: insert_at + 1] + "\n  " + block + presentation_text[insert_at + 1 :]

    def _rebuild_content_types_overrides(self, *, content_types_text: str, final_targets: list[str]) -> str:
        override_tags = re.findall(r"<Override\b[^>]*/>", content_types_text)
        kept: list[str] = []
        for tag in override_tags:
            attrs = self._parse_xml_attrs(tag)
            part_name = attrs.get("PartName", "")
            if part_name.startswith("/ppt/slides/slide") and part_name.endswith(".xml"):
                continue
            kept.append(tag)
        slide_overrides = [
            f'<Override PartName="/ppt/{target}" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            for target in final_targets
        ]
        body = "\n".join(kept + slide_overrides)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
            f"{body}\n"
            "</Types>\n"
        )

    def _ensure_template_structure_files(self, *, unpacked: Path) -> None:
        ppt_dir = unpacked / "ppt"
        slides_dir = ppt_dir / "slides"
        slide_rels_dir = slides_dir / "_rels"
        pres_rels_dir = ppt_dir / "_rels"
        slides_dir.mkdir(parents=True, exist_ok=True)
        slide_rels_dir.mkdir(parents=True, exist_ok=True)
        pres_rels_dir.mkdir(parents=True, exist_ok=True)

        existing_slides = sorted(slides_dir.glob("slide*.xml"), key=lambda p: self._slide_target_sort_key(f"slides/{p.name}"))
        if not existing_slides:
            self._write_default_slide_xml(slides_dir / "slide1.xml")
            existing_slides = [slides_dir / "slide1.xml"]

        presentation_path = ppt_dir / "presentation.xml"
        if not presentation_path.exists():
            presentation_path.write_text(
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
                'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">\n'
                "  <p:sldIdLst>\n"
                '    <p:sldId id="256" r:id="rId1"/>\n'
                "  </p:sldIdLst>\n"
                '  <p:sldSz cx="9144000" cy="5143500" type="screen16x9"/>\n'
                '  <p:notesSz cx="6858000" cy="9144000"/>\n'
                "</p:presentation>\n",
                encoding="utf-8",
            )

        presentation_rels_path = pres_rels_dir / "presentation.xml.rels"
        if not presentation_rels_path.exists():
            first_slide = existing_slides[0].name
            presentation_rels_path.write_text(
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
                f'  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/{first_slide}"/>\n'
                "</Relationships>\n",
                encoding="utf-8",
            )

        content_types_path = unpacked / "[Content_Types].xml"
        if not content_types_path.exists():
            content_types_path.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
                '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
                '  <Default Extension="xml" ContentType="application/xml"/>\n'
                '  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>\n'
                "</Types>\n",
                encoding="utf-8",
            )

    def _cleanup_orphan_slide_files(self, *, slides_dir: Path, keep_targets: set[str]) -> None:
        keep_names = {Path(target).name for target in keep_targets}
        for slide_file in slides_dir.glob("slide*.xml"):
            if slide_file.name not in keep_names:
                slide_file.unlink(missing_ok=True)

    def _cleanup_orphan_slide_rels(self, *, slide_rels_dir: Path, keep_slide_numbers: set[int]) -> None:
        for rel_file in slide_rels_dir.glob("slide*.xml.rels"):
            match = re.search(r"slide(\d+)\.xml\.rels$", rel_file.name)
            if not match:
                continue
            number = int(match.group(1))
            if number not in keep_slide_numbers:
                rel_file.unlink(missing_ok=True)

    def _slide_target_sort_key(self, target: str) -> tuple[int, str]:
        match = re.search(r"slide(\d+)\.xml$", target)
        if match:
            return (int(match.group(1)), target)
        return (10_000, target)

    def _write_default_slide_xml(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "<?xml version='1.0' encoding='UTF-8'?>"
            "<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main' "
            "xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'>"
            "<p:cSld><p:spTree><p:sp><p:txBody><a:bodyPr/><a:lstStyle/>"
            "<a:p><a:r><a:t>Template Slide</a:t></a:r></a:p>"
            "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>",
            encoding="utf-8",
        )

    def _parse_xml_attrs(self, tag: str) -> dict[str, str]:
        attrs: dict[str, str] = {}
        for key, value in re.findall(r'([A-Za-z_:][A-Za-z0-9_.:-]*)="([^"]*)"', tag):
            attrs[key] = value
        return attrs

    def _next_rid(self, used_ids: set[str]) -> str:
        numbers = []
        for rel_id in used_ids:
            match = re.fullmatch(r"rId(\d+)", rel_id)
            if match:
                numbers.append(int(match.group(1)))
        candidate = (max(numbers) + 1) if numbers else 1
        while f"rId{candidate}" in used_ids:
            candidate += 1
        return f"rId{candidate}"

    def _build_slot_graph(self, *, slide_xml: Path, slide_no: int) -> SlotGraph:
        text = slide_xml.read_text(encoding="utf-8", errors="ignore")
        graph = SlotGraph(slide_no=slide_no, slots=[])
        placeholder_re = re.compile(
            r"(placeholder|lorem|ipsum|xxxx|template|caption|insert|click to add|text here|your text)",
            flags=re.IGNORECASE,
        )
        text_hits = re.findall(r"<a:t>(.*?)</a:t>", text, flags=re.DOTALL)
        for idx, raw in enumerate(text_hits, start=1):
            plain = self._xml_unescape(raw).strip()
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

        picture_slots = self._extract_picture_slots(text)
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
                attrs = self._parse_xml_attrs(tag)
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
            attrs = self._parse_xml_attrs(tag)
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

    def _plan_slot_mapping(self, *, slot_graph: SlotGraph) -> dict[str, Any]:
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

    def _build_chart_plan_from_bullets(self, *, node: OutlineNode, source_refs: list[str]) -> ChartPlan:
        facts = self._extract_chart_facts(node=node, source_refs=source_refs)
        if facts:
            labels = [item.label for item in facts[:6]]
            values = [item.value for item in facts[:6]]
            unit = facts[0].unit
            return ChartPlan(
                has_verified_data=True,
                mode="quantitative",
                labels=labels,
                values=values,
                unit=unit,
                note="",
                source="outline_facts",
            )
        labels = [item[:28] for item in (node.bullets[:5] or [node.title])]
        return ChartPlan(
            has_verified_data=False,
            mode="qualitative_fallback",
            labels=labels,
            values=[1.0 for _ in labels],
            unit="",
            note="Qualitative trend view; quantitative values not supplied in source bullets.",
            source="qualitative_fallback",
        )

    def _extract_chart_facts(self, *, node: OutlineNode, source_refs: list[str]) -> list[ChartFact]:
        facts: list[ChartFact] = []
        colon_re = re.compile(
            r"(?P<label>[^:]{1,60})[:]?\s*(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>%|k|m|b)?",
            flags=re.IGNORECASE,
        )
        unit_re = re.compile(
            r"(?P<label>[^0-9]{1,60}?)(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>%|k|m|b)?",
            flags=re.IGNORECASE,
        )
        source = source_refs[0] if source_refs else "user_outline"
        for bullet in node.bullets:
            text = bullet.strip()
            if not text:
                continue
            # Ignore ordinal placeholder bullets like "Point 1.1" from synthetic outlines.
            if re.fullmatch(r"point\s+\d+(?:\.\d+)?", text, flags=re.IGNORECASE):
                continue
            match = colon_re.search(text)
            if not match:
                match = unit_re.search(text)
            if not match:
                continue
            label = match.group("label").strip(" -:") or node.title
            raw_value = match.group("value")
            try:
                value = float(raw_value)
            except ValueError:
                continue
            unit = (match.group("unit") or "").strip()
            facts.append(
                ChartFact(
                    label=label[:40],
                    value=value,
                    unit=unit,
                    source_ref=source,
                )
            )
        return facts

    def _rewrite_template_slide_semantics(
        self,
        *,
        unpacked: Path,
        slide_xml: Path,
        node: OutlineNode,
        slide_no: int,
        chart_plan: ChartPlan,
    ) -> dict[str, Any]:
        content = slide_xml.read_text(encoding="utf-8", errors="ignore")
        content = self._rewrite_template_text_runs(content=content, node=node)
        content = self._rewrite_template_table_cells(content=content, node=node)
        content = self._rewrite_template_media_metadata(content=content, node=node, slide_no=slide_no)
        slide_xml.write_text(content, encoding="utf-8")
        self._rewrite_template_image_icon_assets(unpacked=unpacked, slide_xml=slide_xml, node=node, slide_no=slide_no)
        chart_report = self._rewrite_related_chart_xml(
            unpacked=unpacked,
            slide_xml=slide_xml,
            node=node,
            chart_plan=chart_plan,
        )
        layout_report = self._analyze_and_reflow_template_layout(slide_xml=slide_xml, slide_no=slide_no)
        return {"chart": chart_report, "layout": layout_report}

    def _rewrite_template_text_runs(self, *, content: str, node: OutlineNode) -> str:
        replacements = [node.title] + node.bullets
        matches = list(re.finditer(r"<a:t>.*?</a:t>", content, flags=re.DOTALL))
        if not matches:
            return content

        placeholder_re = re.compile(
            r"(placeholder|lorem|ipsum|xxxx|template|caption|insert|click to add|text here|your text)",
            flags=re.IGNORECASE,
        )
        has_explicit_placeholder = False
        for match in matches:
            inner = re.sub(r"^<a:t>|</a:t>$", "", match.group(0), flags=re.DOTALL)
            inner_plain = re.sub(r"<[^>]+>", "", inner).strip()
            if placeholder_re.search(inner_plain):
                has_explicit_placeholder = True
                break
        out: list[str] = []
        cursor = 0
        replacement_idx = 0
        for match in matches:
            out.append(content[cursor:match.start()])
            segment = match.group(0)
            inner = re.sub(r"^<a:t>|</a:t>$", "", segment, flags=re.DOTALL)
            inner_plain = re.sub(r"<[^>]+>", "", inner).strip()

            use_replacement = replacement_idx < len(replacements)
            if has_explicit_placeholder:
                use_replacement = use_replacement and bool(placeholder_re.search(inner_plain))
            if use_replacement:
                replacement = replacements[replacement_idx]
                out.append(f"<a:t>{self._xml_escape(replacement)}</a:t>")
                replacement_idx += 1
            else:
                out.append(segment)
            cursor = match.end()
        out.append(content[cursor:])
        return "".join(out)

    def _rewrite_template_table_cells(self, *, content: str, node: OutlineNode) -> str:
        bullets = node.bullets or [node.title]
        bullet_iter = iter(bullets)

        def replace_table(match: re.Match[str]) -> str:
            block = match.group(0)

            def repl_text(text_match: re.Match[str]) -> str:
                current = text_match.group(1)
                if re.search(r"(placeholder|lorem|ipsum|xxxx|template|caption|insert)", current, flags=re.IGNORECASE):
                    value = next(bullet_iter, node.title)
                    return f"<a:t>{self._xml_escape(value)}</a:t>"
                return text_match.group(0)

            return re.sub(r"<a:t>(.*?)</a:t>", repl_text, block, flags=re.DOTALL)

        return re.sub(r"<a:tbl>[\s\S]*?</a:tbl>", replace_table, content, flags=re.DOTALL)

    def _rewrite_template_media_metadata(self, *, content: str, node: OutlineNode, slide_no: int) -> str:
        def repl_cnvpr(match: re.Match[str]) -> str:
            tag = match.group(0)
            attrs = self._parse_xml_attrs(tag)
            name = attrs.get("name", "")
            descr = attrs.get("descr", "")
            hint = f"{name} {descr}".lower()
            looks_media = any(word in hint for word in ("pic", "image", "icon", "logo", "placeholder", "template"))
            if not looks_media:
                return tag

            if "icon" in hint:
                semantic = f"{node.title} icon"
            elif "logo" in hint:
                semantic = f"{node.title} logo"
            else:
                semantic = f"{node.title} image"
            caption = node.bullets[0] if node.bullets else node.title
            attrs["name"] = semantic[:80]
            attrs["descr"] = caption[:160]
            attrs_str = " ".join(f'{k}="{self._xml_attr_escape(v)}"' for k, v in attrs.items())
            return f"<p:cNvPr {attrs_str}/>"

        content = re.sub(r"<p:cNvPr\b[^>]*/>", repl_cnvpr, content)

        # Replace obvious caption placeholders.
        caption_re = re.compile(r"<a:t>(.*?)</a:t>", flags=re.DOTALL | re.IGNORECASE)

        def repl_caption(match: re.Match[str]) -> str:
            text = match.group(1).strip()
            if re.search(r"(caption|placeholder|lorem|ipsum|xxxx)", text, flags=re.IGNORECASE):
                caption = node.bullets[min(slide_no - 1, max(len(node.bullets) - 1, 0))] if node.bullets else node.title
                return f"<a:t>{self._xml_escape(caption)}</a:t>"
            return match.group(0)

        return caption_re.sub(repl_caption, content)

    def _rewrite_template_image_icon_assets(self, *, unpacked: Path, slide_xml: Path, node: OutlineNode, slide_no: int) -> None:
        slide_text = slide_xml.read_text(encoding="utf-8", errors="ignore")
        slots = self._extract_picture_slots(slide_text)
        if not slots:
            return

        desired_slots = min(max(1, len(node.bullets) if node.bullets else 1), len(slots))
        keep_slots = slots[:desired_slots]
        drop_slots = slots[desired_slots:]
        drop_ids = {item["rel_id"] for item in drop_slots}
        keep_slot_map = {item["rel_id"]: item["slot_type"] for item in keep_slots}

        if drop_slots:
            ranges = [(item["start"], item["end"]) for item in drop_slots]
            slide_text = self._remove_ranges(slide_text, ranges)
            slide_xml.write_text(slide_text, encoding="utf-8")

        rels_path = slide_xml.parent / "_rels" / f"{slide_xml.name}.rels"
        if not rels_path.exists():
            return

        rels_text = rels_path.read_text(encoding="utf-8", errors="ignore")
        tags = list(re.finditer(r"<Relationship\b[^>]*/>", rels_text))
        if not tags:
            return

        media_dir = unpacked / "ppt" / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        out: list[str] = []
        cursor = 0
        replaced_any = False
        seen_exts: set[str] = set()
        for tag_match in tags:
            out.append(rels_text[cursor:tag_match.start()])
            tag = tag_match.group(0)
            attrs = self._parse_xml_attrs(tag)
            rel_id = attrs.get("Id", "")
            rel_type = attrs.get("Type", "")
            target = attrs.get("Target", "")

            if rel_id in drop_ids and rel_type.endswith("/image"):
                replaced_any = True
                cursor = tag_match.end()
                continue

            should_replace = rel_type.endswith("/image") and bool(target) and (
                rel_id in keep_slot_map or any(word in target.lower() for word in ("placeholder", "template", "image", "icon", "logo"))
            )
            if not should_replace:
                out.append(tag)
                cursor = tag_match.end()
                continue

            slot_type = keep_slot_map.get(rel_id, "image")
            query = self._build_asset_query(node=node, slot_type=slot_type, slide_no=slide_no)
            asset_bytes, ext = self._fetch_slot_asset(
                query=query,
                slot_type=slot_type,
                node=node,
                slide_no=slide_no,
                rel_id=rel_id,
            )
            filename = f"slot-s{slide_no:02d}-{rel_id.lower() or 'img'}-{slot_type}.{ext}"
            target_file = media_dir / filename
            target_file.write_bytes(asset_bytes)
            attrs["Target"] = self._relative_target(from_dir=slide_xml.parent, to_path=target_file)
            attrs_str = " ".join(f'{k}="{self._xml_attr_escape(v)}"' for k, v in attrs.items())
            out.append(f"<Relationship {attrs_str}/>")
            replaced_any = True
            seen_exts.add(ext)
            cursor = tag_match.end()
        out.append(rels_text[cursor:])

        if replaced_any:
            rels_path.write_text("".join(out), encoding="utf-8")
            self._ensure_image_content_types(unpacked=unpacked, exts=seen_exts)

    def _extract_picture_slots(self, slide_text: str) -> list[dict[str, Any]]:
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
                attrs = self._parse_xml_attrs(cnvpr.group(0))
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

    def _remove_ranges(self, text: str, ranges: list[tuple[int, int]]) -> str:
        if not ranges:
            return text
        normalized = sorted(ranges, key=lambda item: item[0])
        out: list[str] = []
        cursor = 0
        for start, end in normalized:
            out.append(text[cursor:start])
            cursor = max(cursor, end)
        out.append(text[cursor:])
        return "".join(out)

    def _build_asset_query(self, *, node: OutlineNode, slot_type: str, slide_no: int) -> str:
        head = node.title.strip() or f"slide {slide_no}"
        tail = node.bullets[0].strip() if node.bullets else ""
        if slot_type == "icon":
            return f"{head} {tail} flat icon"
        if slot_type == "logo":
            return f"{head} {tail} company logo"
        return f"{head} {tail} presentation photo"

    def _fetch_slot_asset(self, *, query: str, slot_type: str, node: OutlineNode, slide_no: int, rel_id: str) -> tuple[bytes, str]:
        provider = self.settings.asset_provider.lower().strip()
        if provider == "mock":
            return self._build_slot_png_bytes(node=node, slot_type=slot_type, slide_no=slide_no, rel_id=rel_id), "png"
        if provider == "none":
            raise TemplateAssetError("asset provider is disabled")

        providers = self._asset_provider_chain(provider)
        if not providers:
            raise TemplateAssetError(f"no configured asset providers for {provider}")

        last_error: Exception | None = None
        for name in providers:
            for _ in range(max(1, self.settings.asset_max_retries)):
                try:
                    if name == "unsplash":
                        return self._fetch_unsplash_asset(query=query, slot_type=slot_type)
                    if name == "pexels":
                        return self._fetch_pexels_asset(query=query, slot_type=slot_type)
                except Exception as exc:  # noqa: PERF203
                    last_error = exc
                    continue
        raise TemplateAssetError(f"asset fetch failed for query={query!r}: {last_error}")

    def _asset_provider_chain(self, provider: str) -> list[str]:
        if provider == "unsplash":
            return ["unsplash"]
        if provider == "pexels":
            return ["pexels"]
        if provider == "auto":
            order: list[str] = []
            if self.settings.unsplash_access_key:
                order.append("unsplash")
            if self.settings.pexels_api_key:
                order.append("pexels")
            return order
        return []

    def _fetch_unsplash_asset(self, *, query: str, slot_type: str) -> tuple[bytes, str]:
        key = self.settings.unsplash_access_key.strip()
        if not key:
            raise TemplateAssetError("missing UNSPLASH_ACCESS_KEY")
        orientation = "landscape" if slot_type == "image" else "squarish"
        with httpx.Client(timeout=self.settings.asset_timeout_sec, follow_redirects=True) as client:
            resp = client.get(
                "https://api.unsplash.com/search/photos",
                params={"query": query, "per_page": 1, "orientation": orientation},
                headers={"Authorization": f"Client-ID {key}"},
            )
            resp.raise_for_status()
            payload = resp.json()
            results = payload.get("results", []) if isinstance(payload, dict) else []
            if not results:
                raise TemplateAssetError("unsplash returned no results")
            first = results[0] if isinstance(results[0], dict) else {}
            urls = first.get("urls", {}) if isinstance(first, dict) else {}
            image_url = urls.get("regular") or urls.get("full") or urls.get("small")
            if not image_url:
                raise TemplateAssetError("unsplash response missing image url")
            return self._download_asset(client=client, url=str(image_url))

    def _fetch_pexels_asset(self, *, query: str, slot_type: str) -> tuple[bytes, str]:
        key = self.settings.pexels_api_key.strip()
        if not key:
            raise TemplateAssetError("missing PEXELS_API_KEY")
        orientation = "landscape" if slot_type == "image" else "square"
        with httpx.Client(timeout=self.settings.asset_timeout_sec, follow_redirects=True) as client:
            resp = client.get(
                "https://api.pexels.com/v1/search",
                params={"query": query, "per_page": 1, "orientation": orientation},
                headers={"Authorization": key},
            )
            resp.raise_for_status()
            payload = resp.json()
            photos = payload.get("photos", []) if isinstance(payload, dict) else []
            if not photos:
                raise TemplateAssetError("pexels returned no results")
            first = photos[0] if isinstance(photos[0], dict) else {}
            src = first.get("src", {}) if isinstance(first, dict) else {}
            image_url = src.get("large2x") or src.get("large") or src.get("original")
            if not image_url:
                raise TemplateAssetError("pexels response missing image url")
            return self._download_asset(client=client, url=str(image_url))

    def _download_asset(self, *, client: httpx.Client, url: str) -> tuple[bytes, str]:
        resp = client.get(url)
        resp.raise_for_status()
        content = resp.content
        if not content:
            raise TemplateAssetError("downloaded asset is empty")
        ext = self._guess_image_ext(content_type=resp.headers.get("content-type", ""), url=url)
        return content, ext

    def _guess_image_ext(self, *, content_type: str, url: str) -> str:
        lowered = content_type.lower()
        if "png" in lowered:
            return "png"
        if "jpeg" in lowered or "jpg" in lowered:
            return "jpg"
        if "webp" in lowered:
            return "webp"
        suffix = Path(url.split("?", 1)[0]).suffix.lower().lstrip(".")
        if suffix in {"png", "jpg", "jpeg", "webp"}:
            return "jpg" if suffix == "jpeg" else suffix
        return "jpg"

    def _build_slot_png_bytes(self, *, node: OutlineNode, slot_type: str, slide_no: int, rel_id: str) -> bytes:
        key = f"{node.title}|{slot_type}|{slide_no}|{rel_id}".encode("utf-8", errors="ignore")
        seed = zlib.crc32(key) & 0xFFFFFFFF
        r = 40 + (seed & 0x7F)
        g = 40 + ((seed >> 8) & 0x7F)
        b = 40 + ((seed >> 16) & 0x7F)
        width = 96
        height = 96
        row = bytes([0]) + bytes([r, g, b] * width)
        raw = row * height
        compressed = zlib.compress(raw, level=9)

        def chunk(tag: bytes, payload: bytes) -> bytes:
            body = tag + payload
            return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")

    def _ensure_image_content_types(self, *, unpacked: Path, exts: set[str]) -> None:
        if not exts:
            return
        content_types_path = unpacked / "[Content_Types].xml"
        if not content_types_path.exists():
            return
        text = content_types_path.read_text(encoding="utf-8", errors="ignore")
        content_map = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "webp": "image/webp",
        }
        changed = False
        for ext in sorted(exts):
            if ext not in content_map:
                continue
            if re.search(rf'<Default\b[^>]*Extension="{re.escape(ext)}"[^>]*/>', text):
                continue
            text = text.replace(
                "</Types>",
                f'  <Default Extension="{ext}" ContentType="{content_map[ext]}"/>\n</Types>',
            )
            changed = True
        if changed:
            content_types_path.write_text(text, encoding="utf-8")

    def _relative_target(self, *, from_dir: Path, to_path: Path) -> str:
        return Path(os.path.relpath(to_path, from_dir)).as_posix()

    def _rewrite_related_chart_xml(
        self,
        *,
        unpacked: Path,
        slide_xml: Path,
        node: OutlineNode,
        chart_plan: ChartPlan,
    ) -> dict[str, Any]:
        rels_path = slide_xml.parent / "_rels" / f"{slide_xml.name}.rels"
        if not rels_path.exists():
            return {"has_chart_slot": False, "has_verified_data": chart_plan.has_verified_data, "mode": "none", "source": chart_plan.source}
        rels_text = rels_path.read_text(encoding="utf-8", errors="ignore")
        chart_targets: list[str] = []
        for tag in re.findall(r"<Relationship\b[^>]*/>", rels_text):
            attrs = self._parse_xml_attrs(tag)
            rel_type = attrs.get("Type", "")
            target = attrs.get("Target", "")
            if rel_type.endswith("/chart") and target:
                chart_targets.append(target)
        if not chart_targets:
            return {"has_chart_slot": False, "has_verified_data": chart_plan.has_verified_data, "mode": "none", "source": chart_plan.source}
        report = {
            "has_chart_slot": True,
            "has_verified_data": chart_plan.has_verified_data,
            "mode": chart_plan.mode,
            "source": chart_plan.source,
            "note": chart_plan.note,
            "labels": chart_plan.labels,
        }
        for target in chart_targets:
            chart_path = (slide_xml.parent / target).resolve()
            try:
                chart_path.relative_to(unpacked.resolve())
            except ValueError:
                continue
            if not chart_path.exists():
                continue
            chart_xml = chart_path.read_text(encoding="utf-8", errors="ignore")
            chart_xml = self._rewrite_chart_xml_content(
                chart_xml=chart_xml,
                node=node,
                chart_plan=chart_plan,
            )
            chart_path.write_text(chart_xml, encoding="utf-8")
        return report

    def _rewrite_chart_xml_content(self, *, chart_xml: str, node: OutlineNode, chart_plan: ChartPlan) -> str:
        chart_xml = re.sub(
            r"<a:t>.*?</a:t>",
            f"<a:t>{self._xml_escape(node.title)}</a:t>",
            chart_xml,
            count=1,
            flags=re.DOTALL,
        )
        categories = chart_plan.labels[:5] or [node.title]
        values = [str(value).rstrip("0").rstrip(".") for value in chart_plan.values[: len(categories)]]
        if len(values) < len(categories):
            values.extend(["1" for _ in range(len(categories) - len(values))])
        chart_xml = self._rewrite_chart_cache_points(
            chart_xml=chart_xml,
            cache_tag="c:strCache",
            value_tag="c:v",
            values=categories,
        )
        chart_xml = self._rewrite_chart_cache_points(
            chart_xml=chart_xml,
            cache_tag="c:numCache",
            value_tag="c:v",
            values=values,
        )
        return chart_xml

    def _rewrite_chart_cache_points(
        self,
        *,
        chart_xml: str,
        cache_tag: str,
        value_tag: str,
        values: list[str],
    ) -> str:
        pattern = rf"<{cache_tag}>[\s\S]*?</{cache_tag}>"

        def repl(match: re.Match[str]) -> str:
            block = match.group(0)
            pt_pattern = re.compile(rf"<c:pt\b[^>]*idx=\"(\d+)\"[^>]*>[\s\S]*?<c:v>.*?</c:v>[\s\S]*?</c:pt>")
            pts = list(pt_pattern.finditer(block))
            if not pts:
                return block
            out: list[str] = []
            cursor = 0
            for idx, pt in enumerate(pts):
                out.append(block[cursor:pt.start()])
                value = values[idx] if idx < len(values) else values[-1]
                out.append(
                    re.sub(
                        r"<c:v>.*?</c:v>",
                        f"<c:v>{self._xml_escape(value)}</c:v>",
                        pt.group(0),
                        flags=re.DOTALL,
                    )
                )
                cursor = pt.end()
            out.append(block[cursor:])
            rebuilt = "".join(out)
            rebuilt = re.sub(
                r"<c:ptCount\b[^>]*/>",
                f'<c:ptCount val="{len(pts)}"/>',
                rebuilt,
                count=1,
            )
            return rebuilt

        return re.sub(pattern, repl, chart_xml)

    def _analyze_and_reflow_template_layout(self, *, slide_xml: Path, slide_no: int) -> dict[str, Any]:
        content = slide_xml.read_text(encoding="utf-8", errors="ignore")
        boxes_before = self._extract_layout_boxes(content)
        before = self._collect_layout_issues(boxes_before)
        if not boxes_before:
            return {
                "slide_no": slide_no,
                "box_count": 0,
                "moved_count": 0,
                "issues_before_count": 0,
                "issues_after_count": 0,
                "issues_before": [],
                "issues_after": [],
                "fidelity_score": 100,
                "passed": True,
            }

        rewritten, moved_count = self._reflow_layout_boxes(content=content, boxes=boxes_before)
        if moved_count:
            slide_xml.write_text(rewritten, encoding="utf-8")
            boxes_after = self._extract_layout_boxes(rewritten)
        else:
            boxes_after = boxes_before
        after = self._collect_layout_issues(boxes_after)
        fidelity_score = self._compute_template_fidelity_score(
            box_count=len(boxes_before),
            moved_count=moved_count,
            issues_after_count=len(after["issues"]),
        )
        return {
            "slide_no": slide_no,
            "box_count": len(boxes_before),
            "moved_count": moved_count,
            "issues_before_count": len(before["issues"]),
            "issues_after_count": len(after["issues"]),
            "issues_before": before["issues"],
            "issues_after": after["issues"],
            "fidelity_score": fidelity_score,
            "passed": not after["issues"],
        }

    def _extract_layout_boxes(self, content: str) -> list[LayoutBox]:
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
            off_attrs = self._parse_xml_attrs(off.group(0))
            ext_attrs = self._parse_xml_attrs(ext.group(0))
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
                attrs = self._parse_xml_attrs(cnvpr.group(0))
                element_id = attrs.get("id") or attrs.get("name")
            element_type = self._layout_element_type(xml_tag=xml_tag, block=block)
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

    def _layout_element_type(self, *, xml_tag: str, block: str) -> str:
        if xml_tag == "pic":
            hint = ""
            cnvpr = re.search(r"<p:cNvPr\b[^>]*/>", block)
            if cnvpr:
                attrs = self._parse_xml_attrs(cnvpr.group(0))
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

    def _collect_layout_issues(self, boxes: list[LayoutBox]) -> dict[str, Any]:
        issues: list[str] = []
        for idx, box in enumerate(boxes, start=1):
            if box.x_emu < 0 or box.y_emu < 0:
                issues.append(f"box-{idx} negative position")
                continue
            if box.x_emu + box.w_emu > SLIDE_WIDTH_EMU or box.y_emu + box.h_emu > SLIDE_HEIGHT_EMU:
                issues.append(f"box-{idx} out of slide bounds")
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if self._boxes_overlap_significantly(boxes[i], boxes[j]):
                    issues.append(f"box-{i + 1} overlaps box-{j + 1}")
        return {"issues": issues}

    def _boxes_overlap_significantly(self, left: LayoutBox, right: LayoutBox) -> bool:
        x_overlap = max(0, min(left.x_emu + left.w_emu, right.x_emu + right.w_emu) - max(left.x_emu, right.x_emu))
        y_overlap = max(0, min(left.y_emu + left.h_emu, right.y_emu + right.h_emu) - max(left.y_emu, right.y_emu))
        if x_overlap <= 0 or y_overlap <= 0:
            return False
        overlap_area = x_overlap * y_overlap
        min_area = min(left.w_emu * left.h_emu, right.w_emu * right.h_emu)
        if min_area <= 0:
            return False
        return overlap_area / min_area >= 0.08

    def _reflow_layout_boxes(self, *, content: str, boxes: list[LayoutBox]) -> tuple[str, int]:
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
                    if self._rect_overlap_significant(
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
            rewritten = self._rewrite_box_off_tag(block=block, x_emu=x_emu, y_emu=y_emu)
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

    def _rect_overlap_significant(
        self,
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

    def _rewrite_box_off_tag(self, *, block: str, x_emu: int, y_emu: int) -> str:
        def repl(match: re.Match[str]) -> str:
            attrs = self._parse_xml_attrs(match.group(0))
            attrs["x"] = str(x_emu)
            attrs["y"] = str(y_emu)
            attrs_str = " ".join(f'{key}="{self._xml_attr_escape(value)}"' for key, value in attrs.items())
            return f"<a:off {attrs_str}/>"

        return re.sub(r"<a:off\b[^>]*/>", repl, block, count=1)

    def _compute_template_fidelity_score(self, *, box_count: int, moved_count: int, issues_after_count: int) -> int:
        if box_count <= 0:
            return 100
        move_ratio = moved_count / box_count
        move_penalty = int(move_ratio * 55)
        issue_penalty = min(45, issues_after_count * 15)
        return max(0, 100 - move_penalty - issue_penalty)

    def _xml_escape(self, text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def _xml_unescape(self, text: str) -> str:
        return html.unescape(text)

    def _xml_attr_escape(self, text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

