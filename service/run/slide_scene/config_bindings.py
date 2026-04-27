from __future__ import annotations

from typing import Any

from .js_parsing import (
    find_matching,
    find_top_level_char,
    parse_js_value,
    split_top_level,
)


def parse_slide_config(js_code: str) -> dict[str, dict[str, Any]]:
    start = js_code.find("const slideConfig")
    if start < 0:
        return {}
    brace_start = js_code.find("{", start)
    if brace_start < 0:
        return {}
    brace_end = find_matching(js_code, brace_start, "{", "}")
    if brace_end < 0:
        return {}

    body_start = brace_start + 1
    body_end = brace_end
    config_body = js_code[body_start:body_end]
    entries: dict[str, dict[str, Any]] = {}
    for item in split_top_level(config_body, ","):
        if not item.strip():
            continue
        colon_index = find_top_level_char(item, ":")
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
        parsed_value = parse_js_value(raw_value)
        entries[key] = {
            "span": (absolute_value_start, absolute_value_end),
            "raw": raw_value,
            "value": parsed_value,
        }
    return entries
