from __future__ import annotations

import re
from pathlib import Path
from typing import Callable


def cleanup_orphan_media(*, unpacked: Path, parse_xml_attrs: Callable[[str], dict[str, str]]) -> None:
    media_dir = unpacked / "ppt" / "media"
    if not media_dir.exists():
        return
    referenced: set[str] = set()
    for rel_file in (unpacked / "ppt" / "slides" / "_rels").glob("*.rels"):
        rels_text = rel_file.read_text(encoding="utf-8", errors="ignore")
        for tag in re.findall(r"<Relationship\b[^>]*/>", rels_text):
            attrs = parse_xml_attrs(tag)
            rel_type = attrs.get("Type", "")
            target = attrs.get("Target", "")
            if not rel_type.endswith("/image") or not target:
                continue
            target_path = (rel_file.parent.parent / target).resolve()
            try:
                rel = target_path.relative_to(unpacked.resolve()).as_posix()
            except ValueError:
                continue
            referenced.add(rel)

    for media_file in media_dir.rglob("*"):
        if media_file.is_file():
            rel = media_file.relative_to(unpacked).as_posix()
            if rel not in referenced:
                media_file.unlink(missing_ok=True)
