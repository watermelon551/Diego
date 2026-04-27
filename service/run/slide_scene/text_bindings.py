from __future__ import annotations

from typing import Any

from .image_bindings import parse_style_and_bbox
from .js_parsing import decode_js_string, find_matching, is_quoted_string, split_top_level
from .types import _Binding
from .variable_bindings import resolve_variable_binding


def parse_text_nodes(
    *,
    js_code: str,
    config: dict[str, dict[str, Any]],
    variable_bindings: dict[str, dict[str, Any]],
) -> list[tuple[str, _Binding]]:
    nodes: list[tuple[str, _Binding]] = []
    offset = 0
    text_node_index = 0
    literal_index = 0
    body_index = 0
    while True:
        call_start = js_code.find("slide.addText(", offset)
        if call_start < 0:
            break
        paren_start = js_code.find("(", call_start)
        paren_end = find_matching(js_code, paren_start, "(", ")")
        if paren_start < 0 or paren_end < 0:
            break
        args_source = js_code[paren_start + 1 : paren_end]
        args = split_top_level(args_source, ",")
        expr = args[0].strip() if args else ""
        options = args[1].strip() if len(args) > 1 else ""
        binding_info = resolve_text_binding(
            expr=expr,
            expr_start=paren_start + 1,
            config=config,
            variable_bindings=variable_bindings,
        )
        if binding_info is not None and binding_info["value"].strip():
            bbox, style = parse_style_and_bbox(options)
            node_kind = str(binding_info["binding_kind"])
            node_value = str(binding_info["value"])
            prop_name = str(binding_info.get("prop_name") or "").strip()
            if prop_name == "title":
                label = "Title"
            elif prop_name in {"subtitle", "summary"}:
                label = prop_name.capitalize()
            elif node_kind == "text_array" or prop_name in {"bullets", "points", "items"}:
                body_index += 1
                label = "Bullet Text" if body_index == 1 else f"Text Box {body_index}"
            else:
                literal_index += 1
                label = f"Text Box {literal_index}"
            if prop_name:
                node_id = f"text:config:{prop_name}"
            else:
                text_node_index += 1
                node_id = f"text:literal:{text_node_index}"
            nodes.append(
                (
                    node_id,
                    _Binding(
                        kind=node_kind,
                        value_span=binding_info["span"],
                        value=node_value,
                        label=label,
                        source_order=call_start,
                        bbox=bbox,
                        style=style,
                        edit_capabilities=["replace_text"],
                    ),
                )
            )
        offset = paren_end + 1
    return nodes


def resolve_text_binding(
    *,
    expr: str,
    expr_start: int,
    config: dict[str, dict[str, Any]],
    variable_bindings: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    stripped = expr.strip()
    if not stripped:
        return None
    absolute_start = expr_start + expr.index(stripped)
    absolute_end = absolute_start + len(stripped)

    if is_quoted_string(stripped):
        value = decode_js_string(stripped)
        if value is None:
            return None
        return {
            "binding_kind": "text_string",
            "value": value,
            "span": (absolute_start, absolute_end),
            "prop_name": "",
        }

    return resolve_variable_binding(
        expr=stripped,
        span=(absolute_start, absolute_end),
        config=config,
        variable_bindings=variable_bindings,
    )
