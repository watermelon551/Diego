from __future__ import annotations

import re
from typing import Any

from .config_bindings import parse_slide_config
from .js_parsing import (
    decode_js_string,
    find_statement_end,
    parse_js_value,
)


def parse_variable_bindings(
    js_code: str,
    config: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    bindings: dict[str, dict[str, Any]] = {}
    for name, expr, span in iter_variable_declarations(js_code):
        binding = resolve_variable_binding(
            expr=expr,
            span=span,
            config=config,
            variable_bindings=bindings,
        )
        if binding is not None:
            bindings[name] = binding
    return bindings


def iter_variable_declarations(js_code: str) -> list[tuple[str, str, tuple[int, int]]]:
    declarations: list[tuple[str, str, tuple[int, int]]] = []
    pattern = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=")
    offset = 0
    while True:
        match = pattern.search(js_code, offset)
        if match is None:
            break
        name = str(match.group(1))
        expr_start = match.end()
        expr_end = find_statement_end(js_code, expr_start)
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


def resolve_variable_binding(
    *,
    expr: str,
    span: tuple[int, int],
    config: dict[str, dict[str, Any]],
    variable_bindings: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    stripped = expr.strip()
    if not stripped:
        return None

    direct_binding = binding_from_literal_or_reference(
        stripped,
        span=span,
        config=config,
        variable_bindings=variable_bindings,
    )
    if direct_binding is not None:
        return direct_binding

    return resolve_map_source_binding(
        stripped,
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
    decoded = decode_js_string(source)
    if decoded is not None:
        return {
            "binding_kind": "text_string",
            "value": decoded,
            "span": span,
            "prop_name": "",
        }

    parsed_value = parse_js_value(source)
    if isinstance(parsed_value, list) and all(isinstance(item, str) for item in parsed_value):
        return {
            "binding_kind": "text_array",
            "value": "\n".join(item for item in parsed_value if item.strip()),
            "span": span,
            "prop_name": "",
        }

    prop_match = re.fullmatch(r"slideConfig\.([A-Za-z_$][\w$]*)", source)
    if prop_match is not None:
        return binding_from_config_entry(config, str(prop_match.group(1)))

    if source in variable_bindings:
        return dict(variable_bindings[source])
    return None


def binding_from_config_entry(
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


def resolve_map_source_binding(
    source: str,
    *,
    config: dict[str, dict[str, Any]],
    variable_bindings: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if ".map" not in source:
        return None

    prop_match = re.search(r"slideConfig\.([A-Za-z_$][\w$]*)", source)
    if prop_match is not None:
        binding = binding_from_config_entry(config, str(prop_match.group(1)))
        if binding is not None and binding.get("binding_kind") == "text_array":
            return binding

    ident_match = re.search(r"([A-Za-z_$][\w$]*)\s*\.map\s*\(", source)
    if ident_match is None:
        return None
    binding = variable_bindings.get(str(ident_match.group(1)))
    if binding is None or binding.get("binding_kind") != "text_array":
        return None
    return dict(binding)
