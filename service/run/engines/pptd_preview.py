from __future__ import annotations

import base64
import html
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import yaml

from .pptd_contracts import PptdSlideContent


class _PlainTextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.parts.append(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "li":
            self.parts.append("•")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "li", "br"}:
            self.parts.append("\n")

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", " ".join(self.parts).replace(" \n ", "\n")).strip()


class PptdProjectPreviewRenderer:
    def preview_manifest(self, *, pptd_path: Path) -> dict[str, Any]:
        deck = self._read_yaml(pptd_path)
        width, height = self._deck_size(deck)
        theme = deck.get("theme") if isinstance(deck.get("theme"), dict) else {}
        pages: list[dict[str, Any]] = []
        page_paths = deck.get("pages") if isinstance(deck.get("pages"), list) else []
        for index, page_ref in enumerate(page_paths):
            if not isinstance(page_ref, str) or not page_ref.strip():
                continue
            page_path = pptd_path.parent / page_ref
            if not page_path.is_file():
                continue
            page = self._read_yaml(page_path)
            svg = self._page_svg(page=page, theme=theme, width=width, height=height)
            pages.append(
                {
                    "index": index,
                    "slide_id": page_path.stem,
                    "format": "svg",
                    "svg_data_url": self._svg_data_url(svg),
                    "width": width,
                    "height": height,
                    "status": "rendered_from_pptd",
                }
            )
        return {
            "schema_version": "pagevra.preview_manifest.v1",
            "page_count": len(pages),
            "pages": pages,
            "source": "pptd_project",
        }

    def _read_yaml(self, path: Path) -> dict[str, Any]:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}

    def _deck_size(self, deck: dict[str, Any]) -> tuple[int, int]:
        size = deck.get("size")
        if (
            isinstance(size, list)
            and len(size) == 2
            and all(isinstance(item, (int, float)) for item in size)
        ):
            return max(1, int(size[0])), max(1, int(size[1]))
        return 1280, 720

    def _page_svg(
        self,
        *,
        page: dict[str, Any],
        theme: dict[str, Any],
        width: int,
        height: int,
    ) -> str:
        lines = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
            f'<rect width="{width}" height="{height}" fill="{self._background_color(page, theme)}"/>',
        ]
        elements = page.get("elements") if isinstance(page.get("elements"), list) else []
        for element in elements:
            if not isinstance(element, dict):
                continue
            element_type = str(element.get("elementType") or "")
            if element_type == "shape":
                lines.extend(self._shape_element(element, theme=theme))
            elif element_type == "text":
                lines.extend(self._text_element(element, theme=theme))
            elif element_type == "image":
                image = self._image_element(element)
                if image:
                    lines.append(image)
        lines.append("</svg>")
        return "\n".join(lines)

    def _background_color(self, page: dict[str, Any], theme: dict[str, Any]) -> str:
        background = page.get("background")
        if isinstance(background, dict):
            fill_type = str(background.get("type") or "solid")
            if fill_type == "solid":
                return self._color(background.get("color"), theme, "#ffffff")
        return "#ffffff"

    def _shape_element(self, element: dict[str, Any], *, theme: dict[str, Any]) -> list[str]:
        bounds = self._bounds(element)
        if bounds is None:
            return []
        x, y, w, h = bounds
        shape_name = str(element.get("shapeName") or "rect")
        fill = element.get("fill") if isinstance(element.get("fill"), dict) else {}
        border = element.get("border") if isinstance(element.get("border"), dict) else {}
        fill_color = self._color(fill.get("color"), theme, "#ffffff") if fill.get("type", "solid") == "solid" else "#ffffff"
        stroke = self._color(border.get("color"), theme, "none") if border else "none"
        stroke_width = self._number(border.get("width"), 0) if border else 0
        opacity = self._number(element.get("opacity"), self._number(fill.get("opacity"), 1.0))
        if shape_name in {"straightConnector1", "line"}:
            x1, y1 = x, y
            x2, y2 = x + w, y + h
            flip = element.get("flip")
            if isinstance(flip, list) and len(flip) >= 2:
                if flip[0]:
                    x1, x2 = x + w, x
                if flip[1]:
                    y1, y2 = y + h, y
            return [
                f'<line x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" '
                f'stroke="{stroke if stroke != "none" else "#64748b"}" stroke-width="{stroke_width or 1:g}" '
                f'opacity="{opacity:g}"/>'
            ]
        if shape_name == "custom":
            path_d = self._custom_path_d(element.get("path"))
            if path_d:
                return [
                    f'<path d="{html.escape(path_d)}" transform="translate({x:g} {y:g})" '
                    f'fill="{fill_color}" stroke="{stroke}" stroke-width="{stroke_width:g}" opacity="{opacity:g}"/>'
                ]
        if shape_name == "ellipse":
            return [
                f'<ellipse cx="{x + w / 2:g}" cy="{y + h / 2:g}" rx="{w / 2:g}" ry="{h / 2:g}" '
                f'fill="{fill_color}" stroke="{stroke}" stroke-width="{stroke_width:g}" opacity="{opacity:g}"/>'
            ]
        rx = 0
        if shape_name == "roundRect":
            adjustments = element.get("adjustments")
            ratio = 0.12
            if isinstance(adjustments, list) and adjustments and isinstance(adjustments[0], (int, float)):
                ratio = max(0.02, min(0.5, float(adjustments[0]) / 100000))
            rx = min(w, h) * ratio
        return [
            f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{rx:g}" '
            f'fill="{fill_color}" stroke="{stroke}" stroke-width="{stroke_width:g}" opacity="{opacity:g}"/>'
        ]

    def _text_element(self, element: dict[str, Any], *, theme: dict[str, Any]) -> list[str]:
        bounds = self._bounds(element)
        if bounds is None:
            return []
        x, y, w, h = bounds
        content = element.get("content") if isinstance(element.get("content"), dict) else {}
        style = self._text_style(content, theme=theme)
        text = self._plain_text(str(content.get("text") or ""))
        if not text:
            return []
        align = content.get("align")
        horizontal = align[0] if isinstance(align, list) and align else "left"
        vertical = align[1] if isinstance(align, list) and len(align) > 1 else "top"
        anchor = {"center": "middle", "right": "end"}.get(str(horizontal), "start")
        line_height = max(1.05, self._number(style.get("lineHeight"), 1.2))
        font_size = max(8, self._number(style.get("fontSize"), 18))
        fill = self._color(style.get("color"), theme, "#111827")
        font_weight = "700" if "<strong>" in str(content.get("text") or "") else "400"
        lines = self._wrap_lines(text, max_chars=max(1, int(w / max(font_size * 0.58, 1))))
        if vertical == "middle":
            start_y = y + (h - (len(lines) - 1) * font_size * line_height) / 2
        elif vertical == "bottom":
            start_y = y + h - (len(lines) - 1) * font_size * line_height
        else:
            start_y = y + font_size
        text_x = x + (w / 2 if anchor == "middle" else w if anchor == "end" else 0)
        output = [
            f'<text x="{text_x:g}" y="{start_y:g}" font-size="{font_size:g}" '
            f'font-family="{html.escape(str(style.get("fontFamily") or "MiSans, Arial, sans-serif"))}" '
            f'font-weight="{font_weight}" text-anchor="{anchor}" fill="{fill}">'
        ]
        for idx, line in enumerate(lines):
            dy = 0 if idx == 0 else font_size * line_height
            output.append(f'<tspan x="{text_x:g}" dy="{dy:g}">{html.escape(line)}</tspan>')
        output.append("</text>")
        return output

    def _image_element(self, element: dict[str, Any]) -> str:
        bounds = self._bounds(element)
        src = str(element.get("src") or "")
        if bounds is None or not src.startswith(("data:", "http://", "https://")):
            return ""
        x, y, w, h = bounds
        return f'<image href="{html.escape(src)}" x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" preserveAspectRatio="xMidYMid meet"/>'

    def _text_style(self, content: dict[str, Any], *, theme: dict[str, Any]) -> dict[str, Any]:
        style: dict[str, Any] = {}
        text_styles = theme.get("textStyles") if isinstance(theme.get("textStyles"), dict) else {}
        style_ref = str(content.get("style") or "")
        if style_ref.startswith("$"):
            referenced = text_styles.get(style_ref[1:])
            if isinstance(referenced, dict):
                style.update(referenced)
        inline_style = self._inline_text_style(str(content.get("text") or ""))
        style.update(inline_style)
        for key in ("fontSize", "fontFamily", "color", "lineHeight", "lineHeightPx"):
            if key in content:
                style[key] = content[key]
        if "lineHeightPx" in style and "fontSize" in style:
            style["lineHeight"] = self._number(style["lineHeightPx"], 0) / max(
                self._number(style["fontSize"], 18), 1
            )
        return style

    def _custom_path_d(self, value: Any) -> str:
        path = str(value or "").strip()
        if ";" in path:
            path = path.split(";", 1)[1].strip()
        if not path or not re.fullmatch(r"[MmLlHhVvCcSsQqTtAaZz0-9, .\\-]+", path):
            return ""
        return path

    def _inline_text_style(self, value: str) -> dict[str, Any]:
        style: dict[str, Any] = {}
        styles = re.findall(r"style=[\"']([^\"']+)[\"']", value)
        for raw_style in styles:
            for declaration in raw_style.split(";"):
                if ":" not in declaration:
                    continue
                key, raw_value = [part.strip() for part in declaration.split(":", 1)]
                if key == "font-size":
                    match = re.match(r"([0-9]+(?:\\.[0-9]+)?)px", raw_value)
                    if match:
                        style["fontSize"] = float(match.group(1))
                elif key == "color":
                    style["color"] = raw_value
                elif key == "font-family":
                    style["fontFamily"] = raw_value
        return style

    def _bounds(self, element: dict[str, Any]) -> tuple[float, float, float, float] | None:
        bounds = element.get("bounds")
        if (
            not isinstance(bounds, list)
            or len(bounds) != 4
            or not all(isinstance(item, (int, float)) for item in bounds)
        ):
            return None
        return float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3])

    def _color(self, value: Any, theme: dict[str, Any], fallback: str) -> str:
        color = str(value or "").strip()
        if color.startswith("$"):
            colors = theme.get("colors") if isinstance(theme.get("colors"), dict) else {}
            color = str(colors.get(color[1:]) or "").strip()
        if color.startswith("#"):
            return html.escape(color)
        lowered = color.lower()
        if len(lowered) in {3, 6} and all(char in "0123456789abcdef" for char in lowered):
            return f"#{html.escape(color)}"
        return fallback

    def _plain_text(self, value: str) -> str:
        parser = _PlainTextHTMLParser()
        parser.feed(value)
        parsed = parser.text()
        return html.unescape(parsed or re.sub("<[^>]+>", "", value)).strip()

    def _wrap_lines(self, text: str, *, max_chars: int) -> list[str]:
        lines: list[str] = []
        for paragraph in text.splitlines():
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            while len(paragraph) > max_chars:
                lines.append(paragraph[:max_chars])
                paragraph = paragraph[max_chars:]
            lines.append(paragraph)
        return lines[:12] or [text[:max_chars]]

    def _number(self, value: Any, fallback: float) -> float:
        return float(value) if isinstance(value, (int, float)) else fallback

    def _svg_data_url(self, svg: str) -> str:
        encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        return f"data:image/svg+xml;base64,{encoded}"


class PptdPreviewRenderer:
    def svg_data_url(self, *, slide: PptdSlideContent, theme: dict[str, Any]) -> str:
        svg = self._cover_svg(slide, theme) if slide.index == 0 else self._content_svg(slide, theme)
        encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        return f"data:image/svg+xml;base64,{encoded}"

    def _cover_svg(self, slide: PptdSlideContent, theme: dict[str, Any]) -> str:
        primary = self._color(theme.get("primary"), "#1C4D5F")
        accent = self._color(theme.get("accent"), "#E07A5F")
        text_gray = self._color(theme.get("textGray"), "#A0A0A0")
        subtitle = html.escape(self._truncate(" / ".join(slide.bullets[:2]) or f"{slide.total} 页课程概要", max_len=52))
        return "\n".join(
            [
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',
                f'<rect width="1280" height="720" fill="{primary}"/>',
                '<g opacity="0.12">',
                *self._grid_lines(),
                "</g>",
                f'<text x="640" y="300" font-size="48" font-weight="700" text-anchor="middle" fill="#fff">{html.escape(self._truncate(slide.title, max_len=24))}</text>',
                f'<text x="640" y="370" font-size="20" text-anchor="middle" fill="#E0E0E0">{subtitle}</text>',
                f'<rect x="440" y="420" width="400" height="40" rx="18" fill="{accent}"/>',
                '<text x="640" y="446" font-size="18" text-anchor="middle" fill="#fff">结构化路径 · 启发式引导</text>',
                f'<text x="640" y="646" font-size="16" text-anchor="middle" fill="{text_gray}">NeoSpectra · PPTD Courseware</text>',
                "</svg>",
            ]
        )

    def _content_svg(self, slide: PptdSlideContent, theme: dict[str, Any]) -> str:
        if slide.index == slide.total - 1:
            return self._final_svg(slide, theme)
        primary = self._color(theme.get("primary"), "#1C4D5F")
        accent = self._color(theme.get("accent"), "#E07A5F")
        accent2 = self._color(theme.get("accent2"), "#6B8E23")
        background = self._color(theme.get("background"), "#F5F5F0")
        text = self._color(theme.get("text"), "#333333")
        return "\n".join(
            [
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',
                f'<rect width="1280" height="720" fill="{background}"/>',
                f'<text x="80" y="94" font-size="36" font-weight="700" fill="{primary}">{html.escape(self._truncate(slide.title, max_len=30))}</text>',
                '<rect x="80" y="140" width="480" height="380" rx="16" fill="#fff"/>',
                *self._body_lines(slide, text=text, accent=accent),
                '<rect x="600" y="140" width="600" height="380" rx="16" fill="#fff"/>',
                f'<circle cx="900" cy="330" r="60" fill="{primary}"/>',
                '<text x="900" y="324" font-size="18" font-weight="700" text-anchor="middle" fill="#fff">核心</text>',
                '<text x="900" y="348" font-size="18" font-weight="700" text-anchor="middle" fill="#fff">概念</text>',
                *self._node_lines(slide, primary=primary, accent=accent, accent2=accent2),
                f'<rect x="80" y="560" width="1120" height="80" rx="16" fill="{accent}"/>',
                '<text x="180" y="610" font-size="18" fill="#fff"><tspan font-weight="700">关键洞察：</tspan>把触发条件、窗口变化和恢复策略连成一条可解释链路。</text>',
                "</svg>",
            ]
        )

    def _final_svg(self, slide: PptdSlideContent, theme: dict[str, Any]) -> str:
        primary = self._color(theme.get("primary"), "#1C4D5F")
        text_gray = self._color(theme.get("textGray"), "#A0A0A0")
        items = self._items(slide)[:4]
        action_lines = [
            f'<text x="640" y="{430 + idx * 34}" font-size="18" text-anchor="middle" fill="#fff">• {html.escape(self._truncate(item, max_len=42))}</text>'
            for idx, item in enumerate(items)
        ]
        return "\n".join(
            [
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',
                f'<rect width="1280" height="720" fill="{primary}"/>',
                '<circle cx="100" cy="100" r="200" fill="#fff" opacity="0.05"/>',
                '<circle cx="1180" cy="620" r="200" fill="#fff" opacity="0.04"/>',
                f'<text x="640" y="270" font-size="56" font-weight="700" text-anchor="middle" fill="#fff">{html.escape(self._truncate(slide.title, max_len=20))}</text>',
                '<text x="640" y="338" font-size="24" text-anchor="middle" fill="#E0E0E0">复盘、迁移、应用</text>',
                '<rect x="340" y="370" width="600" height="220" rx="24" fill="#fff" opacity="0.12"/>',
                *action_lines,
                f'<text x="640" y="650" font-size="16" text-anchor="middle" fill="{text_gray}">NeoSpectra · Generated Courseware</text>',
                "</svg>",
            ]
        )

    def _body_lines(self, slide: PptdSlideContent, *, text: str, accent: str) -> list[str]:
        items = self._items(slide)[:4]
        lines = [
            f'<text x="110" y="205" font-size="18" font-weight="700" fill="{text}">{html.escape(self._truncate(slide.title, max_len=26))}</text>'
        ]
        for idx, item in enumerate(items):
            y = 252 + idx * 54
            lines.append(f'<text x="110" y="{y}" font-size="17" fill="{text}"><tspan fill="{accent}">•</tspan> {html.escape(self._truncate(item, max_len=28))}</text>')
        return lines

    def _node_lines(self, slide: PptdSlideContent, *, primary: str, accent: str, accent2: str) -> list[str]:
        labels = [self._short_label(item) for item in self._items(slide)[:4]]
        nodes = [
            (680, 180, accent, labels[0] if len(labels) > 0 else "概念"),
            (1000, 180, accent2, labels[1] if len(labels) > 1 else "机制"),
            (680, 420, accent, labels[2] if len(labels) > 2 else "判断"),
            (1000, 420, accent2, labels[3] if len(labels) > 3 else "应用"),
        ]
        lines: list[str] = []
        for x, y, color, label in nodes:
            lines.extend(
                [
                    f'<rect x="{x}" y="{y}" width="120" height="56" rx="18" fill="{color}"/>',
                    f'<text x="{x + 60}" y="{y + 35}" font-size="14" text-anchor="middle" fill="#fff">{html.escape(label)}</text>',
                    f'<line x1="{x + 120 if x < 900 else x}" y1="{y + 28}" x2="{900}" y2="{330}" stroke="{primary}" stroke-width="2"/>',
                ]
            )
        return lines

    def _grid_lines(self) -> list[str]:
        lines: list[str] = []
        for pos in range(0, 1281, 60):
            lines.append(f'<line x1="{pos}" y1="0" x2="{pos}" y2="720" stroke="#fff" stroke-width="0.6"/>')
        for pos in range(0, 721, 60):
            lines.append(f'<line x1="0" y1="{pos}" x2="1280" y2="{pos}" stroke="#fff" stroke-width="0.6"/>')
        return lines

    def _items(self, slide: PptdSlideContent) -> list[str]:
        items = [item.strip() for item in slide.bullets if item.strip()] or [
            f"围绕“{slide.title}”建立一个清晰的知识点。"
        ]
        if len(items) > 5:
            items = [*items[:4], "；".join(items[4:])]
        return [self._truncate(item, max_len=46) for item in items]

    def _short_label(self, item: str) -> str:
        head = item.split("：", 1)[0].split(":", 1)[0]
        return head if len(head) <= 8 else f"{head[:7]}…"

    def _truncate(self, value: str, *, max_len: int) -> str:
        text = value.strip()
        return text if len(text) <= max_len else f"{text[:max_len - 1]}…"

    def _color(self, value: Any, fallback: str) -> str:
        color = str(value or "").strip() or fallback
        if color.startswith("#"):
            return html.escape(color)
        lowered = color.lower()
        if len(lowered) in {3, 6} and all(char in "0123456789abcdef" for char in lowered):
            return f"#{html.escape(color)}"
        return fallback
