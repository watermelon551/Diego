from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml


_SINGLE_LINE_SIGNALS = (
    "title",
    "label",
    "badge",
    "tag",
    "num",
    "number",
    "source",
    "footer",
)


def repair_pptd_warning_layout(*, pptd_path: Path, checker_output: str) -> bool:
    """Apply a conservative one-pass text-box repair for PPTD checker warnings."""

    warning_text = checker_output.lower()
    if not any(
        token in warning_text
        for token in (
            "textoverflowwarning",
            "textunderfillwarning",
            "textdriftwarning",
            "textocclusionwarning",
        )
    ):
        return False
    deck = _read_yaml(pptd_path)
    pages = deck.get("pages") if isinstance(deck, dict) else None
    size = deck.get("size") if isinstance(deck, dict) else None
    page_width = _number(size[0], 1280) if isinstance(size, list) and size else 1280
    page_height = _number(size[1], 720) if isinstance(size, list) and len(size) > 1 else 720
    if not isinstance(pages, list):
        return False
    backup_dir = pptd_path.parent / ".warning_repair_backup"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    _backup_project_files(pptd_path=pptd_path, pages=pages, backup_dir=backup_dir)
    changed = False
    for page_ref in pages:
        page_path = pptd_path.parent / str(page_ref)
        if not page_path.is_file():
            continue
        page = _read_yaml(page_path)
        elements = page.get("elements") if isinstance(page, dict) else None
        if not isinstance(elements, list):
            continue
        page_changed = False
        for element in elements:
            if not isinstance(element, dict) or element.get("elementType") != "text":
                continue
            if _repair_text_element(
                element,
                page_width=page_width,
                page_height=page_height,
                warning_text=warning_text,
            ):
                page_changed = True
        if page_changed:
            _write_yaml(page_path, page)
            changed = True
    return changed


def restore_pptd_warning_repair_backup(*, pptd_path: Path) -> bool:
    backup_dir = pptd_path.parent / ".warning_repair_backup"
    manifest_path = backup_dir / "manifest.txt"
    if not manifest_path.is_file():
        return False
    for rel in manifest_path.read_text(encoding="utf-8").splitlines():
        rel = rel.strip()
        if not rel:
            continue
        src = backup_dir / rel
        dst = pptd_path.parent / rel
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    return True


def _backup_project_files(*, pptd_path: Path, pages: list[Any], backup_dir: Path) -> None:
    rel_paths = [pptd_path.name]
    rel_paths.extend(str(page_ref) for page_ref in pages)
    manifest: list[str] = []
    for rel in rel_paths:
        src = pptd_path.parent / rel
        if not src.is_file():
            continue
        dst = backup_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        manifest.append(rel)
    (backup_dir / "manifest.txt").write_text("\n".join(manifest), encoding="utf-8")


def _repair_text_element(
    element: dict[str, Any],
    *,
    page_width: int,
    page_height: int,
    warning_text: str,
) -> bool:
    content = element.get("content")
    bounds = element.get("bounds")
    if not isinstance(content, dict) or not _bounds_ok(bounds):
        return False
    element_id = str(element.get("elementId") or "").lower()
    text = _plain_text(str(content.get("text") or ""))
    changed = False
    single_line = any(token in element_id for token in _SINGLE_LINE_SIGNALS)
    font_size = _number(content.get("fontSize"), 0)
    if "textoverflowwarning" in warning_text:
        if font_size > 12:
            next_size = max(12, int(round(font_size * 0.92)))
            if next_size != font_size:
                content["fontSize"] = next_size
                changed = True
        line_height = _number(content.get("lineHeight"), 0)
        if line_height > 1.18:
            content["lineHeight"] = round(max(1.12, line_height * 0.92), 2)
            changed = True
        if not single_line and len(text) > 18:
            if element.get("wrap") is False:
                element.pop("wrap", None)
                changed = True
            if content.get("wrap") is not True:
                content["wrap"] = True
                changed = True
            if _expand_bounds(bounds, page_width=page_width, page_height=page_height):
                changed = True
    if "textunderfillwarning" in warning_text and not single_line:
        if font_size and font_size < 22 and len(text) <= 80:
            content["fontSize"] = min(22, font_size + 1)
            changed = True
        if _tighten_bounds(bounds):
            changed = True
    if "textdriftwarning" in warning_text or "textocclusionwarning" in warning_text:
        if _nudge_inside_page(bounds, page_width=page_width, page_height=page_height):
            changed = True
    return changed


def _expand_bounds(bounds: list[Any], *, page_width: int, page_height: int) -> bool:
    x, y, width, height = [_number(item, 0) for item in bounds[:4]]
    changed = False
    max_width = max(1, page_width - x - 48)
    if width < max_width and width < 620:
        width = min(max_width, int(width * 1.12) + 24)
        bounds[2] = width
        changed = True
    max_height = max(1, page_height - y - 42)
    if height < max_height:
        height = min(max_height, int(height * 1.18) + 8)
        bounds[3] = height
        changed = True
    return changed


def _tighten_bounds(bounds: list[Any]) -> bool:
    height = _number(bounds[3], 0)
    if height <= 56:
        return False
    next_height = max(56, int(height * 0.9))
    if next_height == height:
        return False
    bounds[3] = next_height
    return True


def _nudge_inside_page(bounds: list[Any], *, page_width: int, page_height: int) -> bool:
    x, y, width, height = [_number(item, 0) for item in bounds[:4]]
    next_x = min(max(24, x), max(24, page_width - width - 24))
    next_y = min(max(24, y), max(24, page_height - height - 24))
    changed = next_x != x or next_y != y
    if changed:
        bounds[0] = next_x
        bounds[1] = next_y
    return changed


def _read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _bounds_ok(value: Any) -> bool:
    return isinstance(value, list) and len(value) >= 4


def _number(value: Any, fallback: int | float) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(fallback)


def _plain_text(value: str) -> str:
    return (
        value.replace("<p>", "")
        .replace("</p>", "")
        .replace("<br/>", " ")
        .replace("<br>", " ")
        .strip()
    )
