from __future__ import annotations

from typing import Any

from .js_parsing import (
    decode_js_string,
    find_matching,
    parse_object_literal,
    split_top_level,
)
from .types import _Binding


def parse_image_nodes(*, js_code: str) -> list[tuple[str, _Binding]]:
    nodes: list[tuple[str, _Binding]] = []
    offset = 0
    index = 0
    while True:
        call_start = js_code.find("slide.addImage(", offset)
        if call_start < 0:
            break
        paren_start = js_code.find("(", call_start)
        paren_end = find_matching(js_code, paren_start, "(", ")")
        if paren_start < 0 or paren_end < 0:
            break
        args_source = js_code[paren_start + 1 : paren_end]
        args = split_top_level(args_source, ",")
        expr = args[0].strip() if args else ""
        options = ""
        span: tuple[int, int] | None = None
        current_src = ""
        bbox: dict[str, float] | None = None
        style: dict[str, Any] = {}

        if expr.startswith("{") and expr.endswith("}"):
            parsed_object = parse_object_literal(expr, absolute_start=paren_start + 1)
            if "path" in parsed_object:
                entry = parsed_object["path"]
                span = entry["span"]
                current_src = entry["value"] if isinstance(entry["value"], str) else str(entry["raw"])
            elif "data" in parsed_object:
                entry = parsed_object["data"]
                span = entry["span"]
                current_src = entry["value"] if isinstance(entry["value"], str) else str(entry["raw"])
            bbox = bbox_from_object(parsed_object)
        elif expr:
            absolute_start = paren_start + 1 + args_source.index(expr)
            absolute_end = absolute_start + len(expr)
            value = decode_js_string(expr)
            current_src = value if value is not None else expr
            span = (absolute_start, absolute_end)
            options = args[1].strip() if len(args) > 1 else ""
            bbox, style = parse_style_and_bbox(options)

        if span is not None and current_src.strip():
            index += 1
            node_id = f"image:call:{index}"
            nodes.append(
                (
                    node_id,
                    _Binding(
                        kind="image_path",
                        value_span=span,
                        value=current_src,
                        label=f"Image {index}",
                        source_order=call_start,
                        bbox=bbox,
                        style=style,
                        edit_capabilities=["replace_image"],
                    ),
                )
            )
        offset = paren_end + 1
    return nodes


def parse_style_and_bbox(options_source: str) -> tuple[dict[str, float] | None, dict[str, Any]]:
    parsed = parse_object_literal(options_source, absolute_start=0)
    bbox = bbox_from_object(parsed)
    style: dict[str, Any] = {}
    for key in ("fontSize", "fontFace", "color", "align", "bold", "italic"):
        entry = parsed.get(key)
        if entry is not None:
            style[key] = entry["value"]
    return bbox, style


def bbox_from_object(parsed_object: dict[str, dict[str, Any]]) -> dict[str, float] | None:
    values: dict[str, float] = {}
    for key in ("x", "y", "w", "h"):
        entry = parsed_object.get(key)
        if entry is None:
            return None
        value = entry["value"]
        if isinstance(value, (int, float)):
            values[key] = float(value)
        else:
            return None
    return values
