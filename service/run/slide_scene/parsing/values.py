from __future__ import annotations

import json
from typing import Any

from .scanning import find_top_level_char, split_top_level


def parse_object_literal(source: str, *, absolute_start: int) -> dict[str, dict[str, Any]]:
    stripped = source.strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        return {}
    content = stripped[1:-1]
    result: dict[str, dict[str, Any]] = {}
    cursor = source.index("{") + 1
    for item in split_top_level(content, ","):
        if not item.strip():
            cursor += len(item) + 1
            continue
        colon_index = find_top_level_char(item, ":")
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
            "value": parse_js_value(raw_value),
            "span": (absolute_value_start, absolute_value_end),
        }
        cursor = max(cursor, local_value_start + len(raw_value))
    return result


def parse_js_value(raw_value: str) -> Any:
    stripped = raw_value.strip()
    decoded = decode_js_string(stripped)
    if decoded is not None:
        return decoded
    if stripped in {"true", "false"}:
        return stripped == "true"
    if _is_number_literal(stripped):
        return float(stripped) if "." in stripped else int(stripped)
    if stripped.startswith("[") and stripped.endswith("]"):
        items = split_top_level(stripped[1:-1], ",")
        return [parse_js_value(item) for item in items if item.strip()]
    return stripped


def decode_js_string(source: str) -> str | None:
    stripped = source.strip()
    if not is_quoted_string(stripped):
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
                escaped = stripped[1:-1].replace("\\", "\\\\").replace('"', '\\"')
                return json.loads('"' + escaped + '"')
            except json.JSONDecodeError:
                return stripped[1:-1]
        return None


def is_quoted_string(source: str) -> bool:
    stripped = source.strip()
    return len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"', "`"}


def _is_number_literal(source: str) -> bool:
    if not source:
        return False
    if source[0] == "-":
        source = source[1:]
    if not source:
        return False
    parts = source.split(".")
    if len(parts) > 2:
        return False
    return all(part.isdigit() for part in parts if part != "")
