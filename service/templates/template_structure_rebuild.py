from __future__ import annotations

import shutil
from pathlib import Path

from .template_structure import (
    TemplateStructureDocumentMixin,
    TemplateStructureSupportMixin,
)


class _TemplateStructureRebuilder(TemplateStructureDocumentMixin, TemplateStructureSupportMixin):
    def rebuild_template_structure(
        self, *, unpacked: Path, target_count: int
    ) -> list[Path]:
        self.ensure_template_structure_files(unpacked=unpacked)
        slides_dir = unpacked / "ppt" / "slides"
        slide_rels_dir = slides_dir / "_rels"
        presentation_path = unpacked / "ppt" / "presentation.xml"
        presentation_rels_path = unpacked / "ppt" / "_rels" / "presentation.xml.rels"
        content_types_path = unpacked / "[Content_Types].xml"

        presentation_text = presentation_path.read_text(encoding="utf-8", errors="ignore")
        presentation_rels_text = presentation_rels_path.read_text(
            encoding="utf-8", errors="ignore"
        )
        content_types_text = content_types_path.read_text(encoding="utf-8", errors="ignore")

        existing_order = self.resolve_slide_targets_from_relationships(
            presentation_text=presentation_text,
            presentation_rels_text=presentation_rels_text,
        )
        if not existing_order:
            existing_order = sorted(
                [p.relative_to(unpacked / "ppt").as_posix() for p in slides_dir.glob("slide*.xml")],
                key=self.slide_target_sort_key,
            )
        if not existing_order:
            existing_order = ["slides/slide1.xml"]
            self.write_default_slide_xml(slides_dir / "slide1.xml")

        target_count = max(1, target_count)
        mapped_sources = [
            existing_order[i % len(existing_order)] for i in range(target_count)
        ]
        final_targets = [f"slides/slide{i}.xml" for i in range(1, target_count + 1)]

        used_source_files: set[str] = set()
        for i, src_target in enumerate(mapped_sources, start=1):
            src_path = unpacked / "ppt" / src_target
            if not src_path.exists():
                self.write_default_slide_xml(src_path)
            dst_rel = f"slides/slide{i}.xml"
            dst_path = unpacked / "ppt" / dst_rel
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            if (
                src_path.resolve() == dst_path.resolve()
                and src_target not in used_source_files
            ):
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

        self.cleanup_orphan_slide_files(slides_dir=slides_dir, keep_targets=set(final_targets))
        self.cleanup_orphan_slide_rels(
            slide_rels_dir=slide_rels_dir,
            keep_slide_numbers=set(range(1, target_count + 1)),
        )

        updated_rels, rid_sequence = self.rebuild_presentation_relationships(
            rels_text=presentation_rels_text,
            final_targets=final_targets,
        )
        updated_presentation = self.rebuild_presentation_slide_list(
            presentation_text=presentation_text,
            rid_sequence=rid_sequence,
        )
        updated_content_types = self.rebuild_content_types_overrides(
            content_types_text=content_types_text,
            final_targets=final_targets,
        )

        presentation_rels_path.write_text(updated_rels, encoding="utf-8")
        presentation_path.write_text(updated_presentation, encoding="utf-8")
        content_types_path.write_text(updated_content_types, encoding="utf-8")
        return [unpacked / "ppt" / target for target in final_targets]

_REBUILDER = _TemplateStructureRebuilder()


def rebuild_template_structure(*, unpacked: Path, target_count: int) -> list[Path]:
    return _REBUILDER.rebuild_template_structure(unpacked=unpacked, target_count=target_count)


def resolve_slide_targets_from_relationships(
    *,
    presentation_text: str,
    presentation_rels_text: str,
) -> list[str]:
    return _REBUILDER.resolve_slide_targets_from_relationships(presentation_text=presentation_text, presentation_rels_text=presentation_rels_text)


def rebuild_presentation_relationships(*, rels_text: str, final_targets: list[str]) -> tuple[str, list[str]]:
    return _REBUILDER.rebuild_presentation_relationships(rels_text=rels_text, final_targets=final_targets)


def rebuild_presentation_slide_list(*, presentation_text: str, rid_sequence: list[str]) -> str:
    return _REBUILDER.rebuild_presentation_slide_list(presentation_text=presentation_text, rid_sequence=rid_sequence)


def rebuild_content_types_overrides(*, content_types_text: str, final_targets: list[str]) -> str:
    return _REBUILDER.rebuild_content_types_overrides(content_types_text=content_types_text, final_targets=final_targets)


def ensure_template_structure_files(*, unpacked: Path) -> None:
    _REBUILDER.ensure_template_structure_files(unpacked=unpacked)


def cleanup_orphan_slide_files(*, slides_dir: Path, keep_targets: set[str]) -> None:
    _REBUILDER.cleanup_orphan_slide_files(slides_dir=slides_dir, keep_targets=keep_targets)


def cleanup_orphan_slide_rels(*, slide_rels_dir: Path, keep_slide_numbers: set[int]) -> None:
    _REBUILDER.cleanup_orphan_slide_rels(slide_rels_dir=slide_rels_dir, keep_slide_numbers=keep_slide_numbers)


def slide_target_sort_key(target: str) -> tuple[int, str]:
    return _REBUILDER.slide_target_sort_key(target)


def write_default_slide_xml(path: Path) -> None:
    _REBUILDER.write_default_slide_xml(path)


def parse_xml_attrs(tag: str) -> dict[str, str]:
    return _REBUILDER.parse_xml_attrs(tag)


def next_rid(used_ids: set[str]) -> str:
    return _REBUILDER.next_rid(used_ids)
