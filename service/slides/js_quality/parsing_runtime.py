from __future__ import annotations

import re
from typing import Any


def render_js_with_line_numbers(js_code: str, *, max_js_lines: int) -> str:
    lines = str(js_code or "").splitlines()
    max_lines = max(40, max_js_lines)
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [
            f"... [truncated {len(str(js_code or '').splitlines()) - max_lines} lines]"
        ]
    return "\n".join(f"{idx + 1:04d}| {line}" for idx, line in enumerate(lines))


def extract_line_numbers(text: str) -> list[int]:
    line_numbers: list[int] = []
    for match in re.finditer(r":(\d+)(?::\d+)?\b", str(text or "")):
        try:
            value = int(match.group(1))
        except ValueError:
            continue
        if value > 0:
            line_numbers.append(value)
    seen: set[int] = set()
    deduped: list[int] = []
    for item in line_numbers:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped[:8]


def extract_js_focus_windows(
    js_code: str,
    *,
    line_numbers: list[int],
    radius: int = 4,
) -> list[dict[str, Any]]:
    lines = str(js_code or "").splitlines()
    if not lines:
        return []
    windows: list[dict[str, Any]] = []
    for line_no in line_numbers[:6]:
        idx = max(1, line_no)
        start = max(1, idx - radius)
        end = min(len(lines), idx + radius)
        snippet = "\n".join(f"{n:04d}| {lines[n - 1]}" for n in range(start, end + 1))
        windows.append({"line": idx, "start": start, "end": end, "snippet": snippet})
    return windows[:4]


def find_matching_delimiter(
    text: str,
    *,
    start_idx: int,
    open_char: str,
    close_char: str,
) -> int:
    depth = 0
    quote: str | None = None
    escape = False
    for idx in range(start_idx, len(text)):
        ch = text[idx]
        if quote is not None:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in {"'", '"', "`"}:
            quote = ch
            continue
        if ch == open_char:
            depth += 1
            continue
        if ch == close_char:
            depth -= 1
            if depth == 0:
                return idx
    return -1


def split_top_level_args(raw_args: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth_round = 0
    depth_curly = 0
    depth_square = 0
    quote: str | None = None
    escape = False

    for ch in raw_args:
        if quote is not None:
            buf.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in {"'", '"', "`"}:
            quote = ch
            buf.append(ch)
            continue
        if ch == "(":
            depth_round += 1
        elif ch == ")":
            depth_round = max(0, depth_round - 1)
        elif ch == "{":
            depth_curly += 1
        elif ch == "}":
            depth_curly = max(0, depth_curly - 1)
        elif ch == "[":
            depth_square += 1
        elif ch == "]":
            depth_square = max(0, depth_square - 1)
        elif ch == "," and depth_round == 0 and depth_curly == 0 and depth_square == 0:
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)

    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def dedupe_preserve_order(issues: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in issues:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out
