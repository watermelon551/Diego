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
        primary = self._color(theme.get("primary") or theme.get("accent"), "#2563eb")
        accent = self._color(theme.get("accent"), "#16a34a")
        background = self._color(theme.get("background"), "#ffffff")
        text = self._color(theme.get("text"), "#111827")
        muted = self._color(theme.get("muted"), "#64748b")
        subtitle = html.escape(" / ".join(slide.bullets[:2]) or f"{slide.total} 页课程概要")
        return "\n".join(
            [
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',
                f'<rect width="1280" height="720" fill="{background}"/>',
                f'<rect width="360" height="720" fill="{primary}"/>',
                f'<rect x="360" width="920" height="18" fill="{accent}"/>',
                '<rect x="460" y="150" width="700" height="360" rx="18" fill="#ffffff"/>',
                f'<text x="500" y="215" font-size="17" fill="{muted}">课程课件 / Courseware</text>',
                f'<text x="500" y="305" font-size="42" font-weight="700" fill="{text}">{html.escape(slide.title)}</text>',
                f'<text x="502" y="420" font-size="21" fill="{muted}">{subtitle}</text>',
                f'<text x="64" y="640" font-size="24" fill="#fff">{slide.page_no:02d} / {slide.total:02d}</text>',
                "</svg>",
            ]
        )

    def _content_svg(self, slide: PptdSlideContent, theme: dict[str, Any]) -> str:
        primary = self._color(theme.get("primary") or theme.get("accent"), "#2563eb")
        accent = self._color(theme.get("accent"), "#16a34a")
        background = self._color(theme.get("background"), "#ffffff")
        text = self._color(theme.get("text"), "#111827")
        muted = self._color(theme.get("muted"), "#64748b")
        return "\n".join(
            [
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',
                f'<rect width="1280" height="720" fill="{background}"/>',
                f'<rect width="1280" height="72" fill="{primary}"/>',
                f'<rect y="72" width="1280" height="6" fill="{accent}"/>',
                f'<text x="68" y="45" font-size="23" fill="#fff">{slide.page_no:02d}</text>',
                f'<text x="150" y="46" font-size="28" font-weight="700" fill="#fff">{html.escape(slide.title)}</text>',
                *self._card_svg_lines(slide, text=text, primary=primary),
                '<rect x="878" y="128" width="306" height="460" rx="16" fill="#f8fafc"/>',
                f'<text x="908" y="184" font-size="17" fill="{primary}">学习抓手</text>',
                f'<text x="908" y="232" font-size="20" fill="{text}">先问：核心概念是什么？</text>',
                f'<text x="908" y="284" font-size="20" fill="{text}">再看：概念如何连接？</text>',
                f'<text x="908" y="336" font-size="20" fill="{text}">最后：能否复述一遍？</text>',
                f'<text x="96" y="662" font-size="16" fill="{muted}">{slide.page_no:02d} / {slide.total:02d}</text>',
                "</svg>",
            ]
        )

    def _card_svg_lines(self, slide: PptdSlideContent, *, text: str, primary: str) -> list[str]:
        items = [item.strip() for item in slide.bullets if item.strip()] or [
            f"围绕“{slide.title}”建立一个清晰的知识点。"
        ]
        if len(items) > 5:
            items = [*items[:4], "；".join(items[4:])]
        card_height = 92 if len(items) <= 4 else 78
        gap = 18 if len(items) <= 4 else 12
        lines: list[str] = []
        for idx, item in enumerate(items[:5]):
            y = 128 + idx * (card_height + gap)
            font_size = 20 if len(item) < 42 else 18
            lines.extend(
                [
                    f'<rect x="96" y="{y}" width="720" height="{card_height}" rx="16" fill="#ffffff"/>',
                    f'<rect x="118" y="{y + 22}" width="48" height="48" rx="12" fill="{primary}"/>',
                    f'<text x="134" y="{y + 53}" font-size="20" fill="#fff">{idx + 1}</text>',
                    f'<text x="188" y="{y + 50}" font-size="{font_size}" fill="{text}">{html.escape(item)}</text>',
                ]
            )
        return lines

    def _color(self, value: Any, fallback: str) -> str:
        color = str(value or "").strip() or fallback
        if color.startswith("#"):
            return html.escape(color)
        lowered = color.lower()
        if len(lowered) in {3, 6} and all(char in "0123456789abcdef" for char in lowered):
            return f"#{html.escape(color)}"
        return fallback

