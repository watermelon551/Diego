from __future__ import annotations


def find_matching(source: str, start_index: int, open_char: str, close_char: str) -> int:
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


def find_top_level_char(source: str, target: str) -> int:
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


def find_statement_end(source: str, start_index: int) -> int:
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


def split_top_level(source: str, delimiter: str) -> list[str]:
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
