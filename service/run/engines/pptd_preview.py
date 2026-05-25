from __future__ import annotations

import base64
import html
from typing import Any

from .pptd_contracts import PptdSlideContent


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
