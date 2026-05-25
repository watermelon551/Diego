from __future__ import annotations

import html

from .pptd_contracts import PptdSlideContent


class PptdPageYamlRenderer:
    def page_yaml(self, *, slide: PptdSlideContent) -> str:
        if slide.index == 0:
            return self._cover_yaml(slide)
        return self._content_yaml(slide)

    def _cover_yaml(self, slide: PptdSlideContent) -> str:
        subtitle = " / ".join(slide.bullets[:2]) or f"{slide.total} 页课程概要"
        return "\n".join(
            [
                "pageType: cover",
                "background:",
                "  type: solid",
                '  color: "$background"',
                "elements:",
                *self._shape("cover-rail", [0, 0, 360, 720], "$primary"),
                *self._shape("cover-accent", [360, 0, 920, 18], "$accent"),
                *self._shape("cover-card", [460, 150, 700, 360], "$card", shadow=True),
                *self._text("cover-label", [500, 190, 600, 30], "课程课件 / Courseware", font_size=17, color="$muted"),
                *self._text(
                    "title",
                    [500, 242, 620, 130],
                    f"<p><strong>{self._escape(slide.title)}</strong></p>",
                    font_size=42,
                    color="$text",
                    line_height=1.12,
                ),
                *self._text(
                    "subtitle",
                    [502, 390, 560, 82],
                    f"<p>{self._escape(subtitle)}</p>",
                    font_size=21,
                    color="$muted",
                    line_height=1.35,
                ),
                *self._text("cover-no", [64, 610, 220, 40], f"{slide.page_no:02d} / {slide.total:02d}", font_size=24, color="$textWhite"),
                "",
            ]
        )

    def _content_yaml(self, slide: PptdSlideContent) -> str:
        return "\n".join(
            [
                "pageType: content",
                "background:",
                "  type: solid",
                '  color: "$background"',
                "elements:",
                *self._shape("top-band", [0, 0, 1280, 72], "$primary"),
                *self._shape("accent-line", [0, 72, 1280, 6], "$accent"),
                *self._text("section-no", [68, 16, 70, 36], f"{slide.page_no:02d}", font_size=23, color="$textWhite", align="[center, middle]"),
                *self._text(
                    "title",
                    [150, 14, 950, 42],
                    f"<p><strong>{self._escape(slide.title)}</strong></p>",
                    font_size=28,
                    color="$textWhite",
                    wrap=False,
                ),
                *self._shape("insight-panel", [878, 128, 306, 460], "$surface", shadow=True),
                *self._text("insight-label", [908, 158, 246, 30], "学习抓手", font_size=17, color="$primary"),
                *self._text("insight-body", [908, 204, 236, 310], self._insight_text(), font_size=18, color="$text", line_height=1.35),
                *self._card_elements(slide),
                *self._text(
                    "footer",
                    [96, 642, 1040, 26],
                    self._footer_text(slide),
                    font_size=16,
                    color="$muted",
                ),
                "",
            ]
        )

    def _card_elements(self, slide: PptdSlideContent) -> list[str]:
        items = self._display_items(slide)
        elements: list[str] = []
        card_height = 92 if len(items) <= 4 else 78
        gap = 18 if len(items) <= 4 else 12
        for idx, item in enumerate(items[:5]):
            y = 128 + idx * (card_height + gap)
            elements.extend(self._shape(f"point-{idx + 1}-card", [96, y, 720, card_height], "$card", shadow=True))
            elements.extend(self._shape(f"point-{idx + 1}-chip", [118, y + 22, 48, 48], "$primary"))
            elements.extend(
                self._text(
                    f"point-{idx + 1}-no",
                    [118, y + 22, 48, 48],
                    f"{idx + 1}",
                    font_size=20,
                    color="$textWhite",
                    align="[center, middle]",
                    wrap=False,
                )
            )
            elements.extend(
                self._text(
                    f"point-{idx + 1}-text",
                    [188, y + 18, 590, card_height - 28],
                    f"<p>{self._escape(item)}</p>",
                    font_size=20 if len(item) < 42 else 18,
                    color="$text",
                    line_height=1.28,
                )
            )
        return elements

    def _insight_text(self) -> str:
        return "\n".join(
            [
                "<p><strong>先问：</strong>这个机制解决什么问题？</p>",
                '<p style="margin-top:14px"><strong>再看：</strong>触发条件和状态变化。</p>',
                '<p style="margin-top:14px"><strong>最后：</strong>用自己的话复述流程。</p>',
            ]
        )

    def _display_items(self, slide: PptdSlideContent) -> list[str]:
        items = [item.strip() for item in slide.bullets if item.strip()]
        if not items:
            return [f"围绕“{slide.title}”建立一个清晰的知识点。"]
        if len(items) <= 5:
            return items
        return [*items[:4], "；".join(items[4:])]

    def _footer_text(self, slide: PptdSlideContent) -> str:
        footer = f"{slide.page_no:02d} / {slide.total:02d}"
        note = str(getattr(slide, "source_note", "") or "").strip()
        if note:
            footer = f"{footer} · 资料依据：{self._escape(note[:56])}"
        return footer

    def _shape(self, element_id: str, bounds: list[int], color: str, *, shadow: bool = False) -> list[str]:
        lines = [
            f"  - elementId: {element_id}",
            "    elementType: shape",
            f"    bounds: {bounds}",
            "    shapeName: roundRect",
            "    adjustments: [7000]",
            "    fill:",
            "      type: solid",
            f'      color: "{color}"',
        ]
        if shadow:
            lines.extend(["    shadow:", "      blur: 12", '      color: "#00000014"', "      offset: [0, 4]"])
        return lines

    def _text(
        self,
        element_id: str,
        bounds: list[int],
        text: str,
        *,
        font_size: int,
        color: str,
        line_height: float = 1.25,
        align: str = "[left, top]",
        wrap: bool = True,
    ) -> list[str]:
        return [
            f"  - elementId: {element_id}",
            "    elementType: text",
            f"    bounds: {bounds}",
            "    content:",
            f"      fontSize: {font_size}",
            f'      color: "{color}"',
            '      fontFamily: "Liter, MiSans"',
            f"      lineHeight: {line_height}",
            f"      align: {align}",
            f"      wrap: {'true' if wrap else 'false'}",
            "      text: |",
            self._block_text(text, indent=8),
        ]

    def _block_text(self, value: str, *, indent: int) -> str:
        prefix = " " * indent
        return "\n".join(f"{prefix}{line}" for line in value.splitlines() or [""])

    def _escape(self, value: str) -> str:
        return html.escape(value, quote=False)
