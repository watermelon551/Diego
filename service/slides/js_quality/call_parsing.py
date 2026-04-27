from __future__ import annotations

import re


def extract_method_call_args(
    js_code: str,
    *,
    method_expr: str,
    split_top_level_args,
) -> list[list[str]]:
    payload = str(js_code or "")
    pattern = re.compile(method_expr)
    calls: list[list[str]] = []
    idx = 0
    n = len(payload)
    while idx < n:
        match = pattern.search(payload, idx)
        if not match:
            break
        open_idx = payload.find("(", match.start())
        if open_idx < 0:
            idx = match.end()
            continue

        depth = 0
        in_single = False
        in_double = False
        in_backtick = False
        escaped = False
        close_idx = -1
        pos = open_idx
        while pos < n:
            ch = payload[pos]
            if escaped:
                escaped = False
                pos += 1
                continue
            if ch == "\\":
                escaped = True
                pos += 1
                continue
            if in_single:
                if ch == "'":
                    in_single = False
                pos += 1
                continue
            if in_double:
                if ch == '"':
                    in_double = False
                pos += 1
                continue
            if in_backtick:
                if ch == "`":
                    in_backtick = False
                pos += 1
                continue
            if ch == "'":
                in_single = True
                pos += 1
                continue
            if ch == '"':
                in_double = True
                pos += 1
                continue
            if ch == "`":
                in_backtick = True
                pos += 1
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    close_idx = pos
                    break
            pos += 1

        if close_idx <= open_idx:
            idx = match.end()
            continue

        raw_args = payload[open_idx + 1 : close_idx]
        calls.append(split_top_level_args(raw_args))
        idx = close_idx + 1

    return calls
