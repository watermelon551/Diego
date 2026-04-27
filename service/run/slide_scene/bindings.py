from __future__ import annotations

from typing import Any

from .config_bindings import parse_slide_config as parse_slide_config_impl
from .image_bindings import (
    parse_image_nodes as parse_image_nodes_impl,
    parse_style_and_bbox as parse_style_and_bbox_impl,
)
from .text_bindings import (
    parse_text_nodes as parse_text_nodes_impl,
    resolve_text_binding as resolve_text_binding_impl,
)
from .variable_bindings import (
    binding_from_config_entry as binding_from_config_entry_impl,
    binding_from_literal_or_reference as binding_from_literal_or_reference_impl,
    iter_variable_declarations as iter_variable_declarations_impl,
    parse_variable_bindings as parse_variable_bindings_impl,
    resolve_map_source_binding as resolve_map_source_binding_impl,
    resolve_variable_binding as resolve_variable_binding_impl,
)


def parse_slide_config(js_code: str) -> dict[str, dict[str, Any]]:
    return parse_slide_config_impl(js_code)


def parse_variable_bindings(
    js_code: str,
    config: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return parse_variable_bindings_impl(js_code, config)


def iter_variable_declarations(js_code: str) -> list[tuple[str, str, tuple[int, int]]]:
    return iter_variable_declarations_impl(js_code)


def resolve_variable_binding(
    *,
    expr: str,
    span: tuple[int, int],
    config: dict[str, dict[str, Any]],
    variable_bindings: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    return resolve_variable_binding_impl(
        expr=expr,
        span=span,
        config=config,
        variable_bindings=variable_bindings,
    )


def binding_from_literal_or_reference(
    source: str,
    *,
    span: tuple[int, int],
    config: dict[str, dict[str, Any]],
    variable_bindings: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    return binding_from_literal_or_reference_impl(
        source,
        span=span,
        config=config,
        variable_bindings=variable_bindings,
    )


def binding_from_config_entry(
    config: dict[str, dict[str, Any]],
    prop_name: str,
) -> dict[str, Any] | None:
    return binding_from_config_entry_impl(config, prop_name)


def resolve_map_source_binding(
    source: str,
    *,
    config: dict[str, dict[str, Any]],
    variable_bindings: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    return resolve_map_source_binding_impl(
        source,
        config=config,
        variable_bindings=variable_bindings,
    )


def parse_text_nodes(
    *,
    js_code: str,
    config: dict[str, dict[str, Any]],
    variable_bindings: dict[str, dict[str, Any]],
):
    return parse_text_nodes_impl(
        js_code=js_code,
        config=config,
        variable_bindings=variable_bindings,
    )


def resolve_text_binding(
    *,
    expr: str,
    expr_start: int,
    config: dict[str, dict[str, Any]],
    variable_bindings: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    return resolve_text_binding_impl(
        expr=expr,
        expr_start=expr_start,
        config=config,
        variable_bindings=variable_bindings,
    )


def parse_image_nodes(*, js_code: str):
    return parse_image_nodes_impl(js_code=js_code)


def parse_style_and_bbox(options: str):
    return parse_style_and_bbox_impl(options)
