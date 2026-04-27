from __future__ import annotations

import hashlib
import json

from ...models import EditableSlideNode, EditableSlideNodeBBox, EditableSlideScene, OutlineNode
from .bindings import (
    parse_image_nodes,
    parse_slide_config,
    parse_text_nodes,
    parse_variable_bindings,
)
from .types import _Binding, _ParsedScene


class SlideSceneError(RuntimeError):
    """Base error for deterministic slide scene parsing and save."""


class SlideSceneConflictError(SlideSceneError):
    """Raised when the caller saves against a stale scene version."""


class SlideSceneUnsupportedError(SlideSceneError):
    """Raised when a slide cannot be edited deterministically."""


class SlideSceneNodeNotFoundError(SlideSceneError):
    """Raised when an operation references a missing node."""


def build_slide_scene(*, js_code: str, run_id: str, slide_no: int) -> _ParsedScene:
    scene_version = _scene_version(js_code)
    slide_index = max(0, slide_no - 1)
    slide_id = f"{run_id}-slide-{slide_index}"
    config = parse_slide_config(js_code)
    variable_bindings = parse_variable_bindings(js_code, config)
    text_nodes = parse_text_nodes(
        js_code=js_code,
        config=config,
        variable_bindings=variable_bindings,
    )
    image_nodes = parse_image_nodes(js_code=js_code)

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


def scene_to_outline_node(
    *, existing: OutlineNode | None, scene: EditableSlideScene
) -> OutlineNode | None:
    if existing is None:
        return None
    title, bullets = scene_outline_values(scene)
    return OutlineNode(
        title=title or existing.title,
        bullets=bullets if bullets is not None else list(existing.bullets),
        page_type=existing.page_type,
        layout_hint=existing.layout_hint,
    )


def _scene_version(js_code: str) -> str:
    return hashlib.sha256(js_code.encode("utf-8")).hexdigest()[:16]


def _serialize_binding_value(*, binding_kind: str, value: str) -> str:
    if binding_kind == "text_array":
        items = [item.strip() for item in value.replace("\r\n", "\n").split("\n") if item.strip()]
        return json.dumps(items, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)
