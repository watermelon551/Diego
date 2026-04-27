from __future__ import annotations

import html
import re
from typing import Any

from ...models import OutlineNode


def rewrite_template_text_runs(
    *,
    content: str,
    node: OutlineNode,
    xml_escape,
) -> str:
    replacements = [node.title] + node.bullets
    matches = list(re.finditer(r"<a:t>.*?</a:t>", content, flags=re.DOTALL))
    if not matches:
        return content

    placeholder_re = re.compile(
        r"(placeholder|lorem|ipsum|xxxx|template|caption|insert|click to add|text here|your text)",
        flags=re.IGNORECASE,
    )
    has_explicit_placeholder = False
    for match in matches:
        inner = re.sub(r"^<a:t>|</a:t>$", "", match.group(0), flags=re.DOTALL)
        inner_plain = re.sub(r"<[^>]+>", "", inner).strip()
        if placeholder_re.search(inner_plain):
            has_explicit_placeholder = True
            break
    out: list[str] = []
    cursor = 0
    replacement_idx = 0
    for match in matches:
        out.append(content[cursor:match.start()])
        segment = match.group(0)
        inner = re.sub(r"^<a:t>|</a:t>$", "", segment, flags=re.DOTALL)
        inner_plain = re.sub(r"<[^>]+>", "", inner).strip()

        use_replacement = replacement_idx < len(replacements)
        if has_explicit_placeholder:
            use_replacement = use_replacement and bool(
                placeholder_re.search(inner_plain)
            )
        if use_replacement:
            replacement = replacements[replacement_idx]
            out.append(f"<a:t>{xml_escape(replacement)}</a:t>")
            replacement_idx += 1
        else:
            out.append(segment)
        cursor = match.end()
    out.append(content[cursor:])
    return "".join(out)


def rewrite_template_table_cells(
    *,
    content: str,
    node: OutlineNode,
    xml_escape,
) -> str:
    bullets = node.bullets or [node.title]
    bullet_iter = iter(bullets)

    def replace_table(match: re.Match[str]) -> str:
        block = match.group(0)

        def repl_text(text_match: re.Match[str]) -> str:
            current = text_match.group(1)
            if re.search(
                r"(placeholder|lorem|ipsum|xxxx|template|caption|insert)",
                current,
                flags=re.IGNORECASE,
            ):
                value = next(bullet_iter, node.title)
                return f"<a:t>{xml_escape(value)}</a:t>"
            return text_match.group(0)

        return re.sub(r"<a:t>(.*?)</a:t>", repl_text, block, flags=re.DOTALL)

    return re.sub(r"<a:tbl>[\s\S]*?</a:tbl>", replace_table, content, flags=re.DOTALL)


def rewrite_template_media_metadata(
    *,
    content: str,
    node: OutlineNode,
    slide_no: int,
    parse_xml_attrs,
    xml_escape,
    xml_attr_escape,
) -> str:
    def repl_cnvpr(match: re.Match[str]) -> str:
        tag = match.group(0)
        attrs = parse_xml_attrs(tag)
        name = attrs.get("name", "")
        descr = attrs.get("descr", "")
        hint = f"{name} {descr}".lower()
        looks_media = any(
            word in hint
            for word in ("pic", "image", "icon", "logo", "placeholder", "template")
        )
        if not looks_media:
            return tag

        if "icon" in hint:
            semantic = f"{node.title} icon"
        elif "logo" in hint:
            semantic = f"{node.title} logo"
        else:
            semantic = f"{node.title} image"
        caption = node.bullets[0] if node.bullets else node.title
        attrs["name"] = semantic[:80]
        attrs["descr"] = caption[:160]
        attrs_str = " ".join(f'{k}="{xml_attr_escape(v)}"' for k, v in attrs.items())
        return f"<p:cNvPr {attrs_str}/>"

    content = re.sub(r"<p:cNvPr\b[^>]*/>", repl_cnvpr, content)
    caption_re = re.compile(r"<a:t>(.*?)</a:t>", flags=re.DOTALL | re.IGNORECASE)

    def repl_caption(match: re.Match[str]) -> str:
        text = match.group(1).strip()
        if re.search(r"(caption|placeholder|lorem|ipsum|xxxx)", text, flags=re.IGNORECASE):
            caption = (
                node.bullets[min(slide_no - 1, max(len(node.bullets) - 1, 0))]
                if node.bullets
                else node.title
            )
            return f"<a:t>{xml_escape(caption)}</a:t>"
        return match.group(0)

    return caption_re.sub(repl_caption, content)


def remove_ranges(text: str, ranges: list[tuple[int, int]]) -> str:
    if not ranges:
        return text
    normalized = sorted(ranges, key=lambda item: item[0])
    out: list[str] = []
    cursor = 0
    for start, end in normalized:
        out.append(text[cursor:start])
        cursor = max(cursor, end)
    out.append(text[cursor:])
    return "".join(out)


def xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def xml_unescape(text: str) -> str:
    return html.unescape(text)


def xml_attr_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
