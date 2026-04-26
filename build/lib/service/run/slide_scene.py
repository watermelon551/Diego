from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from ..models import EditableSlideNode, EditableSlideNodeBBox, EditableSlideScene


class SlideSceneError(RuntimeError):
    """Base error for deterministic slide scene parsing and save."""


class SlideSceneConflictError(SlideSceneError):
    """Raised when the caller saves against a stale scene version."""


class SlideSceneUnsupportedError(SlideSceneError):
    """Raised when a slide cannot be edited deterministically."""


class SlideSceneNodeNotFoundError(SlideSceneError):
    """Raised when an operation references a missing node."""


@dataclass(frozen=True)
class _Binding:
    kind: str
    value_span: tuple[int, int]
    value: str
    label: str
    source_order: int
    bbox: dict[str, float] | None
    style: dict[str, Any]
    edit_capabilities: list[str]


@dataclass(frozen=True)
class _ParsedScene:
    scene: EditableSlideScene
    bindings: dict[str, _Binding]


def build_slide_scene(*, js_code: str, run_id: str, slide_no: int) -> _ParsedScene:
    scene_version = _scene_version(js_code)
    slide_index = max(0, slide_no - 1)
    slide_id = f"{run_id}-slide-{slide_index}"
    config = _parse_slide_config(js_code)
    variable_bindings = _parse_variable_bindings(js_code, config)
    text_nodes = _parse_text_nodes(
        js_code=js_code,
        config=config,
        variable_bindings=variable_bindings,
    )
    image_nodes = _parse_image_nodes(js_code=js_code)

    bindings: dict[str, _Binding] = {}
    nodes: list[EditableSlideNode] = []
    for node_id, binding in sorted([*text_nodes, *image_nodes], key=lambda item: item[1].source_order):
        bindings[node_id] = binding
        bbox = EditableSlideNodeBBox(**binding.bbox) if binding.bbox is not None else None
        node = EditableSlideNode(
            node_id=node_id,
            kind="text" if node_id.startswith("text:") else "image",
            label=binding.label,
            text=binding.value if node_id.startswith("text:") else None,
            src=binding.value if node_id.startswith("image:") else None,
            bbox=bbox,
            style=binding.style,
            edit_capabilities=list(binding.edit_capabilities),
        )
        nodes.append(node)

    readonly = not bool(nodes)
    readonly_reason = "no deterministic editable nodes found in slide.js" if readonly else None
    scene = EditableSlideScene(
        run_id=run_id,
        slide_id=slide_id,
        slide_index=slide_index,
        slide_no=slide_no,
        scene_version=scene_version,
        nodes=nodes,
        readonly=readonly,
        readonly_reason=readonly_reason,
    )
    return _ParsedScene(scene=scene, bindings=bindings)


def apply_scene_operations(
    *,
    js_code: str,
    parsed_scene: _ParsedScene,
    scene_version: str,
    operations: list[dict[str, str]],
    run_id: str,
    slide_no: int,
) -> tuple[str, _ParsedScene]:
    if scene_version != parsed_scene.scene.scene_version:
        raise SlideSceneConflictError("scene version conflict")
    if parsed_scene.scene.readonly:
        raise SlideSceneUnsupportedError(parsed_scene.scene.readonly_reason or "slide is read-only")

    replacements: list[tuple[int, int, str]] = []
    for operation in operations:
        op = str(operation.get("op") or "").strip()
        node_id = str(operation.get("node_id") or "").strip()
        value = str(operation.get("value") or "")
        binding = parsed_scene.bindings.get(node_id)
        if binding is None:
            raise SlideSceneNodeNotFoundError(f"unknown scene node: {node_id}")
        if op == "replace_text" and binding.kind not in {"text_string", "text_array"}:
            raise SlideSceneUnsupportedError(f"node does not support replace_text: {node_id}")
        if op == "replace_image" and binding.kind != "image_path":
            raise SlideSceneUnsupportedError(f"node does not support replace_image: {node_id}")

        replacement = _serialize_binding_value(binding_kind=binding.kind, value=value)
        replacements.append((binding.value_span[0], binding.value_span[1], replacement))

    next_code = js_code
    for start, end, replacement in sorted(replacements, key=lambda item: item[0], reverse=True):
        next_code = f"{next_code[:start]}{replacement}{next_code[end:]}"
    return next_code, build_slide_scene(js_code=next_code, run_id=run_id, slide_no=slide_no)


def scene_outline_values(scene: EditableSlideScene) -> tuple[str | None, list[str] | None]:
    title: str | None = None
    bullets: list[str] | None = None
    for node in scene.nodes:
        if node.kind != "text":
            continue
        lowered_label = node.label.strip().lower()
        if title is None and lowered_label == "title":
            title = node.text or None
            continue
        if bullets is None and ("bullet" in lowered_label or "text box" in lowered_label or "body" in lowered_label):
            body = str(node.text or "").strip()
            if body:
                bullets = [line.strip() for line in body.splitlines() if line.strip()]
    return title, bullets


def _scene_version(js_code: str) -> str:
    return hashlib.sha256(js_code.encode("utf-8")).hexdigest()[:16]


def _serialize_binding_value(*, binding_kind: str, value: str) -> str:
    if binding_kind == "text_array":
        items = [item.strip() for item in value.replace("\r\n", "\n").split("\n") if item.strip()]
        return json.dumps(items, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


def _parse_variable_bindings(
    js_code: str,
    config: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    bindings: dict[str, dict[str, Any]] = {}
    for name, expr, span in _iter_variable_declarations(js_code):
        binding = _resolve_variable_binding(
            expr=expr,
            span=span,
            config=config,
            variable_bindings=bindings,
        )
        if binding is not None:
            bindings[name] = binding
    return bindings


def _iter_variable_declarations(
    js_code: str,
) -> list[tuple[str, str, tuple[int, int]]]:
    declarations: list[tuple[str, str, tuple[int, int]]] = []
    pattern = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=")
    offset = 0
    while True:
        match = pattern.search(js_code, offset)
        if match is None:
            break
        name = str(match.group(1))
        expr_start = match.end()
        expr_end = _find_statement_end(js_code, expr_start)
        if expr_end < 0:
            break
        raw_expr = js_code[expr_start:expr_end]
        stripped = raw_expr.strip()
        if stripped:
            absolute_start = expr_start + raw_expr.index(stripped)
            absolute_end = absolute_start + len(stripped)
            declarations.append((name, stripped, (absolute_start, absolute_end)))
        offset = expr_end + 1
    return declarations


def _parse_slide_config(js_code: str) -> dict[str, dict[str, Any]]:
    start = js_code.find("const slideConfig")
    if start < 0:
        return {}
    brace_start = js_code.find("{", start)
    if brace_start < 0:
        return {}
    brace_end = _find_matching(js_code, brace_start, "{", "}")
    if brace_end < 0:
        return {}

    body_start = brace_start + 1
    body_end = brace_end
    config_body = js_code[body_start:body_end]
    entries: dict[str, dict[str, Any]] = {}
    for item in _split_top_level(config_body, ","):
        if not item.strip():
            continue
        colon_index = _find_top_level_char(item, ":")
        if colon_index < 0:
            continue
        raw_key = item[:colon_index].strip()
        raw_value = item[colon_index + 1 :].strip()
        if not raw_key:
            continue
        key = raw_key.strip("'\"")
        local_value_start = item.index(raw_value)
        absolute_value_start = body_start + config_body.index(item) + local_value_start
        absolute_value_end = absolute_value_start + len(raw_value)
        parsed_value = _parse_js_value(raw_value)
        entries[key] = {
            "span": (absolute_value_start, absolute_value_end),
            "raw": raw_value,
            "value": parsed_value,
        }
    return entries


def _parse_text_nodes(
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
        paren_end = _find_matching(js_code, paren_start, "(", ")")
        if paren_start < 0 or paren_end < 0:
            break
        args_source = js_code[paren_start + 1 : paren_end]
        args = _split_top_level(args_source, ",")
        expr = args[0].strip() if args else ""
        options = args[1].strip() if len(args) > 1 else ""
        binding_info = _resolve_text_binding(
            js_code=js_code,
            expr=expr,
            expr_start=paren_start + 1,
            config=config,
            variable_bindings=variable_bindings,
        )
        if binding_info is not None and binding_info["value"].strip():
            bbox, style = _parse_style_and_bbox(options)
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


def _resolve_text_binding(
    *,
    js_code: str,
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

    if _is_quoted_string(stripped):
        value = _decode_js_string(stripped)
        if value is None:
            return None
        return {
            "binding_kind": "text_string",
            "value": value,
            "span": (absolute_start, absolute_end),
            "prop_name": "",
        }

    return _resolve_variable_binding(
        expr=stripped,
        span=(absolute_start, absolute_end),
        config=config,
        variable_bindings=variable_bindings,
    )


def _resolve_variable_binding(
    *,
    expr: str,
    span: tuple[int, int],
    config: dict[str, dict[str, Any]],
    variable_bindings: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    stripped = expr.strip()
    if not stripped:
        return None

    direct_binding = _binding_from_literal_or_reference(
        stripped,
        span=span,
        config=config,
        variable_bindings=variable_bindings,
    )
    if direct_binding is not None:
        return direct_binding

    map_source = _resolve_map_source_binding(
        stripped,
        config=config,
        variable_bindings=variable_bindings,
    )
    if map_source is not None:
        return map_source
    return None


def _binding_from_literal_or_reference(
    source: str,
    *,
    span: tuple[int, int],
    config: dict[str, dict[str, Any]],
    variable_bindings: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    decoded = _decode_js_string(source)
    if decoded is not None:
        return {
            "binding_kind": "text_string",
            "value": decoded,
            "span": span,
            "prop_name": "",
        }

    parsed_value = _parse_js_value(source)
    if isinstance(parsed_value, list) and all(isinstance(item, str) for item in parsed_value):
        return {
            "binding_kind": "text_array",
            "value": "\n".join(item for item in parsed_value if item.strip()),
            "span": span,
            "prop_name": "",
        }

    prop_match = re.fullmatch(r"slideConfig\.([A-Za-z_$][\w$]*)", source)
    if prop_match is not None:
        return _binding_from_config_entry(config, str(prop_match.group(1)))

    if source in variable_bindings:
        return dict(variable_bindings[source])
    return None


def _binding_from_config_entry(
    config: dict[str, dict[str, Any]],
    prop_name: str,
) -> dict[str, Any] | None:
    if prop_name not in config:
        return None
    config_entry = config[prop_name]
    raw_value = config_entry["value"]
    if isinstance(raw_value, str):
        return {
            "binding_kind": "text_string",
            "value": raw_value,
            "span": config_entry["span"],
            "prop_name": prop_name,
        }
    if isinstance(raw_value, list) and all(isinstance(item, str) for item in raw_value):
        return {
            "binding_kind": "text_array",
            "value": "\n".join(item for item in raw_value if item.strip()),
            "span": config_entry["span"],
            "prop_name": prop_name,
        }
    return None


def _resolve_map_source_binding(
    source: str,
    *,
    config: dict[str, dict[str, Any]],
    variable_bindings: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if ".map" not in source:
        return None

    prop_match = re.search(r"slideConfig\.([A-Za-z_$][\w$]*)", source)
    if prop_match is not None:
        binding = _binding_from_config_entry(config, str(prop_match.group(1)))
        if binding is not None and binding.get("binding_kind") == "text_array":
            return binding

    ident_match = re.search(r"([A-Za-z_$][\w$]*)\s*\.map\s*\(", source)
    if ident_match is None:
        return None
    binding = variable_bindings.get(str(ident_match.group(1)))
    if binding is None or binding.get("binding_kind") != "text_array":
        return None
    return dict(binding)


def _parse_image_nodes(*, js_code: str) -> list[tuple[str, _Binding]]:
    nodes: list[tuple[str, _Binding]] = []
    offset = 0
    index = 0
    while True:
        call_start = js_code.find("slide.addImage(", offset)
        if call_start < 0:
            break
        paren_start = js_code.find("(", call_start)
        paren_end = _find_matching(js_code, paren_start, "(", ")")
        if paren_start < 0 or paren_end < 0:
            break
        args_source = js_code[paren_start + 1 : paren_end]
        args = _split_top_level(args_source, ",")
        expr = args[0].strip() if args else ""
        options = ""
        span: tuple[int, int] | None = None
        current_src = ""
        bbox: dict[str, float] | None = None
        style: dict[str, Any] = {}

        if expr.startswith("{") and expr.endswith("}"):
            parsed_object = _parse_object_literal(expr, absolute_start=paren_start + 1)
            if "path" in parsed_object:
                entry = parsed_object["path"]
                span = entry["span"]
                current_src = entry["value"] if isinstance(entry["value"], str) else str(entry["raw"])
            elif "data" in parsed_object:
                entry = parsed_object["data"]
                span = entry["span"]
                current_src = entry["value"] if isinstance(entry["value"], str) else str(entry["raw"])
            bbox = _bbox_from_object(parsed_object)
            style = {}
        elif expr:
            absolute_start = paren_start + 1 + args_source.index(expr)
            absolute_end = absolute_start + len(expr)
            value = _decode_js_string(expr)
            current_src = value if value is not None else expr
            span = (absolute_start, absolute_end)
            options = args[1].strip() if len(args) > 1 else ""
            bbox, style = _parse_style_and_bbox(options)

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


def _parse_style_and_bbox(options_source: str) -> tuple[dict[str, float] | None, dict[str, Any]]:
    parsed = _parse_object_literal(options_source, absolute_start=0)
    bbox = _bbox_from_object(parsed)
    style: dict[str, Any] = {}
    for key in ("fontSize", "fontFace", "color", "align", "bold", "italic"):
        entry = parsed.get(key)
        if entry is None:
            continue
        style[key] = entry["value"]
    return bbox, style


def _bbox_from_object(parsed_object: dict[str, dict[str, Any]]) -> dict[str, float] | None:
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


def _parse_object_literal(source: str, *, absolute_start: int) -> dict[str, dict[str, Any]]:
    stripped = source.strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        return {}
    content = stripped[1:-1]
    result: dict[str, dict[str, Any]] = {}
    cursor = source.index("{") + 1
    for item in _split_top_level(content, ","):
        if not item.strip():
            cursor += len(item) + 1
            continue
        colon_index = _find_top_level_char(item, ":")
        if colon_index < 0:
            cursor += len(item) + 1
            continue
        raw_key = item[:colon_index].strip()
        raw_value = item[colon_index + 1 :].strip()
        key = raw_key.strip("'\"")
        local_value_start = source.find(raw_value, cursor)
        absolute_value_start = absolute_start + local_value_start
        absolute_value_end = absolute_value_start + len(raw_value)
        result[key] = {
            "raw": raw_value,
            "value": _parse_js_value(raw_value),
            "span": (absolute_value_start, absolute_value_end),
        }
        cursor = max(cursor, local_value_start + len(raw_value))
    return result


def _parse_js_value(raw_value: str) -> Any:
    stripped = raw_value.strip()
    decoded = _decode_js_string(stripped)
    if decoded is not None:
        return decoded
    if stripped in {"true", "false"}:
        return stripped == "true"
    if re.fullmatch(r"-?\d+(?:\.\d+)?", stripped):
        return float(stripped) if "." in stripped else int(stripped)
    if stripped.startswith("[") and stripped.endswith("]"):
        items = _split_top_level(stripped[1:-1], ",")
        return [
            _parse_js_value(item)
            for item in items
            if item.strip()
        ]
    return stripped


def _decode_js_string(source: str) -> str | None:
    stripped = source.strip()
    if not _is_quoted_string(stripped):
        return None
    if stripped.startswith("`") and stripped.endswith("`"):
        if "${" in stripped:
            return None
        body = stripped[1:-1]
        return (
            body.replace("\\`", "`")
            .replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace("\\t", "\t")
            .replace("\\\\", "\\")
        )
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        if stripped.startswith("'") and stripped.endswith("'"):
            try:
                return json.loads('"' + stripped[1:-1].replace("\\", "\\\\").replace('"', '\\"') + '"')
            except json.JSONDecodeError:
                return stripped[1:-1]
        return None


def _is_quoted_string(source: str) -> bool:
    stripped = source.strip()
    return len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {
        "'",
        '"',
        "`",
    }


def _find_matching(source: str, start_index: int, open_char: str, close_char: str) -> int:
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(start_index, len(source)):
        char = source[index]
        if quote is not None:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
            continue
        if char == open_char:
            depth += 1
            continue
        if char == close_char:
            depth -= 1
            if depth == 0:
                return index
    return -1


def _find_top_level_char(source: str, target: str) -> int:
    quote: str | None = None
    escaped = False
    paren = bracket = brace = 0
    for index, char in enumerate(source):
        if quote is not None:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
            continue
        if char == "(":
            paren += 1
            continue
        if char == ")":
            paren = max(0, paren - 1)
            continue
        if char == "[":
            bracket += 1
            continue
        if char == "]":
            bracket = max(0, bracket - 1)
            continue
        if char == "{":
            brace += 1
            continue
        if char == "}":
            brace = max(0, brace - 1)
            continue
        if char == target and paren == 0 and bracket == 0 and brace == 0:
            return index
    return -1


def _find_statement_end(source: str, start_index: int) -> int:
    quote: str | None = None
    escaped = False
    paren = bracket = brace = 0
    for index in range(start_index, len(source)):
        char = source[index]
        if quote is not None:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
            continue
        if char == "(":
            paren += 1
            continue
        if char == ")":
            paren = max(0, paren - 1)
            continue
        if char == "[":
            bracket += 1
            continue
        if char == "]":
            bracket = max(0, bracket - 1)
            continue
        if char == "{":
            brace += 1
            continue
        if char == "}":
            brace = max(0, brace - 1)
            continue
        if char == ";" and paren == 0 and bracket == 0 and brace == 0:
            return index
    return -1


def _split_top_level(source: str, delimiter: str) -> list[str]:
    items: list[str] = []
    quote: str | None = None
    escaped = False
    paren = bracket = brace = 0
    token_start = 0
    for index, char in enumerate(source):
        if quote is not None:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
            continue
        if char == "(":
            paren += 1
            continue
        if char == ")":
            paren = max(0, paren - 1)
            continue
        if char == "[":
            bracket += 1
            continue
        if char == "]":
            bracket = max(0, bracket - 1)
            continue
        if char == "{":
            brace += 1
            continue
        if char == "}":
            brace = max(0, brace - 1)
            continue
        if char == delimiter and paren == 0 and bracket == 0 and brace == 0:
            items.append(source[token_start:index])
            token_start = index + 1
    items.append(source[token_start:])
    return items
