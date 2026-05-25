from __future__ import annotations

import hashlib
import html
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import yaml

from ...models import EditableSlideNode, EditableSlideNodeBBox, EditableSlideScene
from . import (
    SlideSceneConflictError,
    SlideSceneNodeNotFoundError,
    SlideSceneUnsupportedError,
)


class _PlainTextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.parts.append(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "li":
            self.parts.append("-")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "li", "br"}:
            self.parts.append("\n")

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", " ".join(self.parts).replace(" \n ", "\n")).strip()


def build_pptd_slide_scene(
    *,
    pptd_path: Path,
    page_path: Path,
    run_id: str,
    slide_no: int,
) -> EditableSlideScene:
    page = _read_page(page_path)
    scene_version = _scene_version(pptd_path=pptd_path, page_path=page_path)
    slide_index = max(0, slide_no - 1)
    nodes: list[EditableSlideNode] = []
    for element in _page_elements(page):
        if str(element.get("elementType") or "") != "text":
            continue
        element_id = str(element.get("elementId") or "").strip()
        if not element_id:
            continue
        content = element.get("content") if isinstance(element.get("content"), dict) else {}
        raw_text = str(content.get("text") or "")
        visible_text = _plain_text(raw_text)
        if not visible_text or _is_decorative_text(element_id, raw_text, visible_text):
            continue
        bbox = _node_bbox(element)
        nodes.append(
            EditableSlideNode(
                node_id=f"text:pptd:{element_id}",
                kind="text",
                label=_label_for_element(element_id),
                text=visible_text,
                bbox=bbox,
                style=_scene_style(content),
                edit_capabilities=["replace_text"],
            )
        )
    readonly = not bool(nodes)
    return EditableSlideScene(
        run_id=run_id,
        slide_id=f"{run_id}-slide-{slide_index}",
        slide_index=slide_index,
        slide_no=slide_no,
        scene_version=scene_version,
        nodes=nodes,
        readonly=readonly,
        readonly_reason="no editable PPTD text nodes found" if readonly else None,
    )


def apply_pptd_scene_operations(
    *,
    pptd_path: Path,
    page_path: Path,
    scene_version: str,
    operations: list[dict[str, str]],
    run_id: str,
    slide_no: int,
) -> EditableSlideScene:
    current_scene = build_pptd_slide_scene(
        pptd_path=pptd_path,
        page_path=page_path,
        run_id=run_id,
        slide_no=slide_no,
    )
    if scene_version != current_scene.scene_version:
        raise SlideSceneConflictError("scene version conflict")
    if current_scene.readonly:
        raise SlideSceneUnsupportedError(current_scene.readonly_reason or "slide is read-only")

    page = _read_page(page_path)
    elements = _page_elements(page)
    by_id = {
        str(element.get("elementId") or ""): element
        for element in elements
        if isinstance(element, dict)
    }
    valid_node_ids = {node.node_id for node in current_scene.nodes}
    for operation in operations:
        op = str(operation.get("op") or "").strip()
        node_id = str(operation.get("node_id") or "").strip()
        value = str(operation.get("value") or "")
        if node_id not in valid_node_ids:
            raise SlideSceneNodeNotFoundError(f"unknown scene node: {node_id}")
        if op != "replace_text":
            raise SlideSceneUnsupportedError(f"node does not support {op}: {node_id}")
        element_id = node_id.removeprefix("text:pptd:")
        element = by_id.get(element_id)
        if not isinstance(element, dict):
            raise SlideSceneNodeNotFoundError(f"unknown PPTD element: {element_id}")
        content = element.get("content")
        if not isinstance(content, dict):
            raise SlideSceneUnsupportedError(f"node does not support replace_text: {node_id}")
        original = str(content.get("text") or "")
        content["text"] = _replace_visible_text(original, value)

    _write_page(page_path, page)
    return build_pptd_slide_scene(
        pptd_path=pptd_path,
        page_path=page_path,
        run_id=run_id,
        slide_no=slide_no,
    )


def _read_page(page_path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(page_path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _write_page(page_path: Path, page: dict[str, Any]) -> None:
    page_path.write_text(
        yaml.safe_dump(page, allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8",
    )


def _page_elements(page: dict[str, Any]) -> list[dict[str, Any]]:
    elements = page.get("elements") if isinstance(page.get("elements"), list) else []
    return [element for element in elements if isinstance(element, dict)]


def _scene_version(*, pptd_path: Path, page_path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(pptd_path.read_bytes() if pptd_path.is_file() else b"")
    digest.update(page_path.read_bytes())
    return digest.hexdigest()[:16]


def _node_bbox(element: dict[str, Any]) -> EditableSlideNodeBBox | None:
    bounds = element.get("bounds")
    if (
        isinstance(bounds, list)
        and len(bounds) == 4
        and all(isinstance(item, (int, float)) for item in bounds)
    ):
        return EditableSlideNodeBBox(
            x=float(bounds[0]),
            y=float(bounds[1]),
            w=float(bounds[2]),
            h=float(bounds[3]),
        )
    return None


def _scene_style(content: dict[str, Any]) -> dict[str, Any]:
    style: dict[str, Any] = {}
    for key in ("style", "fontSize", "fontFamily", "color", "lineHeight", "lineHeightPx"):
        if key in content:
            style[key] = content[key]
    return style


def _label_for_element(element_id: str) -> str:
    normalized = element_id.replace("_", "-").replace(" ", "-").strip("-")
    if normalized in {"title", "cover-title", "page-title"} or normalized.endswith("-title"):
        return "Title"
    if "subtitle" in normalized or "subject" in normalized:
        return "Subtitle"
    if "body" in normalized or "content" in normalized or "point" in normalized:
        return "Body"
    return normalized or "Text"


def _plain_text(value: str) -> str:
    parser = _PlainTextHTMLParser()
    parser.feed(value)
    parsed = parser.text()
    return html.unescape(parsed or re.sub("<[^>]+>", "", value)).strip()


def _replace_visible_text(original_html: str, value: str) -> str:
    original_plain = _plain_text(original_html)
    escaped_value = html.escape(value.strip())
    if original_plain and original_plain in original_html:
        return original_html.replace(original_plain, escaped_value, 1)
    return f"<p>{escaped_value}</p>"


def _is_decorative_text(element_id: str, raw_text: str, visible_text: str) -> bool:
    lowered_id = element_id.lower()
    if any(marker in lowered_id for marker in ("symbol", "decorative", "ornament")):
        return True
    if visible_text.strip() in {"π", "∑", "△", "▲", "◆", "◇", "○", "●"}:
        return True
    for alpha in re.findall(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})", raw_text):
        try:
            if int(alpha, 16) <= 0x40:
                return True
        except ValueError:
            continue
    return False
