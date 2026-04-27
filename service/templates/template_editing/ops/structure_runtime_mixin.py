from __future__ import annotations

from pathlib import Path
from typing import Any

from ....run.types import SlotGraph
from ...template_structure_rebuild import (
    cleanup_orphan_slide_files,
    cleanup_orphan_slide_rels,
    ensure_template_structure_files,
    next_rid,
    parse_xml_attrs,
    rebuild_content_types_overrides,
    rebuild_presentation_relationships,
    rebuild_presentation_slide_list,
    rebuild_template_structure,
    resolve_slide_targets_from_relationships,
    slide_target_sort_key,
    write_default_slide_xml,
)
from ..slot_mapping import build_slot_graph, plan_slot_mapping


class TemplateStructureRuntimeMixin:
    def _rebuild_template_structure(
        self, *, unpacked: Path, target_count: int
    ) -> list[Path]:
        return rebuild_template_structure(unpacked=unpacked, target_count=target_count)

    def _resolve_slide_targets_from_relationships(
        self, *, presentation_text: str, presentation_rels_text: str
    ) -> list[str]:
        return resolve_slide_targets_from_relationships(
            presentation_text=presentation_text,
            presentation_rels_text=presentation_rels_text,
        )

    def _rebuild_presentation_relationships(
        self, *, rels_text: str, final_targets: list[str]
    ) -> tuple[str, list[str]]:
        return rebuild_presentation_relationships(
            rels_text=rels_text,
            final_targets=final_targets,
        )

    def _rebuild_presentation_slide_list(
        self, *, presentation_text: str, rid_sequence: list[str]
    ) -> str:
        return rebuild_presentation_slide_list(
            presentation_text=presentation_text,
            rid_sequence=rid_sequence,
        )

    def _rebuild_content_types_overrides(
        self, *, content_types_text: str, final_targets: list[str]
    ) -> str:
        return rebuild_content_types_overrides(
            content_types_text=content_types_text,
            final_targets=final_targets,
        )

    def _ensure_template_structure_files(self, *, unpacked: Path) -> None:
        ensure_template_structure_files(unpacked=unpacked)

    def _cleanup_orphan_slide_files(
        self, *, slides_dir: Path, keep_targets: set[str]
    ) -> None:
        cleanup_orphan_slide_files(slides_dir=slides_dir, keep_targets=keep_targets)

    def _cleanup_orphan_slide_rels(
        self, *, slide_rels_dir: Path, keep_slide_numbers: set[int]
    ) -> None:
        cleanup_orphan_slide_rels(
            slide_rels_dir=slide_rels_dir,
            keep_slide_numbers=keep_slide_numbers,
        )

    def _slide_target_sort_key(self, target: str) -> tuple[int, str]:
        return slide_target_sort_key(target)

    def _write_default_slide_xml(self, path: Path) -> None:
        write_default_slide_xml(path)

    def _parse_xml_attrs(self, tag: str) -> dict[str, str]:
        return parse_xml_attrs(tag)

    def _next_rid(self, used_ids: set[str]) -> str:
        return next_rid(used_ids)

    def _build_slot_graph(self, *, slide_xml: Path, slide_no: int) -> SlotGraph:
        return build_slot_graph(slide_xml=slide_xml, slide_no=slide_no)

    def _plan_slot_mapping(self, *, slot_graph: SlotGraph) -> dict[str, Any]:
        return plan_slot_mapping(slot_graph=slot_graph)
