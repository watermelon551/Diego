from __future__ import annotations

import os
import re
import struct
import zlib
from pathlib import Path
from typing import Any

from ...models import OutlineNode


def rewrite_template_image_icon_assets(
    *,
    unpacked: Path,
    slide_xml: Path,
    node: OutlineNode,
    slide_no: int,
    extract_picture_slots,
    remove_ranges,
    active_asset_search_context,
    parse_xml_attrs,
    build_asset_query,
    fetch_slot_asset,
    relative_target,
    xml_attr_escape,
    ensure_image_content_types,
    run_asset_keys_snapshot,
    remember_run_asset_key,
) -> None:
    slide_text = slide_xml.read_text(encoding="utf-8", errors="ignore")
    slots = extract_picture_slots(slide_text)
    if not slots:
        return

    desired_slots = min(max(1, len(node.bullets) if node.bullets else 1), len(slots))
    keep_slots = slots[:desired_slots]
    drop_slots = slots[desired_slots:]
    drop_ids = {item["rel_id"] for item in drop_slots}
    keep_slot_map = {item["rel_id"]: item["slot_type"] for item in keep_slots}

    if drop_slots:
        ranges = [(item["start"], item["end"]) for item in drop_slots]
        slide_text = remove_ranges(slide_text, ranges)
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
    context = active_asset_search_context()
    run_id = str(context.get("run_id", "")).strip()
    used_keys: set[str] = set()
    if run_id and callable(run_asset_keys_snapshot):
        snap = run_asset_keys_snapshot(run_id=run_id)
        if isinstance(snap, set):
            used_keys = {str(item).strip() for item in snap if str(item).strip()}
    out: list[str] = []
    cursor = 0
    replaced_any = False
    seen_exts: set[str] = set()
    for tag_match in tags:
        out.append(rels_text[cursor:tag_match.start()])
        tag = tag_match.group(0)
        attrs = parse_xml_attrs(tag)
        rel_id = attrs.get("Id", "")
        rel_type = attrs.get("Type", "")
        target = attrs.get("Target", "")

        if rel_id in drop_ids and rel_type.endswith("/image"):
            replaced_any = True
            cursor = tag_match.end()
            continue

        should_replace = rel_type.endswith("/image") and bool(target) and (
            rel_id in keep_slot_map
            or any(
                word in target.lower()
                for word in ("placeholder", "template", "image", "icon", "logo")
            )
        )
        if not should_replace:
            out.append(tag)
            cursor = tag_match.end()
            continue

        slot_type = keep_slot_map.get(rel_id, "image")
        query = build_asset_query(node=node, slot_type=slot_type, slide_no=slide_no)
        asset_bytes, ext, meta = fetch_slot_asset(
            query=query,
            slot_type=slot_type,
            node=node,
            slide_no=slide_no,
            rel_id=rel_id,
            search_context=context,
            used_asset_keys=used_keys,
        )
        filename = f"slot-s{slide_no:02d}-{rel_id.lower() or 'img'}-{slot_type}.{ext}"
        target_file = media_dir / filename
        target_file.write_bytes(asset_bytes)
        attrs["Target"] = relative_target(from_dir=slide_xml.parent, to_path=target_file)
        attrs_str = " ".join(f'{k}="{xml_attr_escape(v)}"' for k, v in attrs.items())
        out.append(f"<Relationship {attrs_str}/>")
        selected_key = str(meta.get("key", "")).strip()
        if selected_key:
            used_keys.add(selected_key)
            if run_id and callable(remember_run_asset_key):
                remember_run_asset_key(run_id=run_id, key=selected_key)
        replaced_any = True
        seen_exts.add(ext)
        cursor = tag_match.end()
    out.append(rels_text[cursor:])

    if replaced_any:
        rels_path.write_text("".join(out), encoding="utf-8")
        ensure_image_content_types(unpacked=unpacked, exts=seen_exts)


def active_asset_search_context(getter) -> dict[str, Any]:
    if callable(getter):
        value = getter()
        if isinstance(value, dict):
            return value
    return {}


def build_asset_query(*, node: OutlineNode, slot_type: str, slide_no: int) -> str:
    head = node.title.strip() or f"slide {slide_no}"
    tail = node.bullets[0].strip() if node.bullets else ""
    if slot_type == "icon":
        return f"{head} {tail} flat icon"
    if slot_type == "logo":
        return f"{head} {tail} company logo"
    return f"{head} {tail} presentation photo"


def build_slot_png_bytes(
    *,
    node: OutlineNode,
    slot_type: str,
    slide_no: int,
    rel_id: str,
) -> bytes:
    key = f"{node.title}|{slot_type}|{slide_no}|{rel_id}".encode(
        "utf-8", errors="ignore"
    )
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
        return (
            struct.pack(">I", len(payload))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


def ensure_image_content_types(*, unpacked: Path, exts: set[str]) -> None:
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


def relative_target(*, from_dir: Path, to_path: Path) -> str:
    return Path(os.path.relpath(to_path, from_dir)).as_posix()
