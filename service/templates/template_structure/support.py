from __future__ import annotations

import re
from pathlib import Path


class TemplateStructureSupportMixin:
    def ensure_template_structure_files(self, *, unpacked: Path) -> None:
        ppt_dir = unpacked / "ppt"
        slides_dir = ppt_dir / "slides"
        slide_rels_dir = slides_dir / "_rels"
        pres_rels_dir = ppt_dir / "_rels"
        slides_dir.mkdir(parents=True, exist_ok=True)
        slide_rels_dir.mkdir(parents=True, exist_ok=True)
        pres_rels_dir.mkdir(parents=True, exist_ok=True)

        existing_slides = sorted(
            slides_dir.glob("slide*.xml"),
            key=lambda p: self.slide_target_sort_key(f"slides/{p.name}"),
        )
        if not existing_slides:
            self.write_default_slide_xml(slides_dir / "slide1.xml")
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

    def cleanup_orphan_slide_files(self, *, slides_dir: Path, keep_targets: set[str]) -> None:
        keep_names = {Path(target).name for target in keep_targets}
        for slide_file in slides_dir.glob("slide*.xml"):
            if slide_file.name not in keep_names:
                slide_file.unlink(missing_ok=True)

    def cleanup_orphan_slide_rels(
        self, *, slide_rels_dir: Path, keep_slide_numbers: set[int]
    ) -> None:
        for rel_file in slide_rels_dir.glob("slide*.xml.rels"):
            match = re.search(r"slide(\d+)\.xml\.rels$", rel_file.name)
            if not match:
                continue
            number = int(match.group(1))
            if number not in keep_slide_numbers:
                rel_file.unlink(missing_ok=True)

    def slide_target_sort_key(self, target: str) -> tuple[int, str]:
        match = re.search(r"slide(\d+)\.xml$", target)
        if match:
            return (int(match.group(1)), target)
        return (10_000, target)

    def write_default_slide_xml(self, path: Path) -> None:
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

    def parse_xml_attrs(self, tag: str) -> dict[str, str]:
        attrs: dict[str, str] = {}
        for key, value in re.findall(r'([A-Za-z_:][A-Za-z0-9_.:-]*)="([^"]*)"', tag):
            attrs[key] = value
        return attrs

    def next_rid(self, used_ids: set[str]) -> str:
        numbers = []
        for rel_id in used_ids:
            match = re.fullmatch(r"rId(\d+)", rel_id)
            if match:
                numbers.append(int(match.group(1)))
        candidate = (max(numbers) + 1) if numbers else 1
        while f"rId{candidate}" in used_ids:
            candidate += 1
        return f"rId{candidate}"
