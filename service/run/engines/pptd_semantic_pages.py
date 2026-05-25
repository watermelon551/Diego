from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Iterable

from .pptd_contracts import PptdSlideContent


@dataclass(frozen=True)
class _TextSpec:
    element_id: str
    bounds: list[int]
    text: str
    font_size: int
    color: str = "$text"
    align: str = "[left, top]"
    line_height: float = 1.25
    bold: bool = False
    wrap: bool = True


@dataclass(frozen=True)
class _ShapeSpec:
    element_id: str
    bounds: list[int]
    color: str
    shape_name: str = "roundRect"
    border_color: str = "transparent"
    border_width: int = 0
    opacity: float = 1.0


class PptdSemanticPageRenderer:
    """Writes high-signal PPTD pages instead of filling fragile template placeholders."""

    semantic_templates = {
        "content1.page",
        "content_bullets.page",
        "content-bullets.page",
        "bullets.page",
        "content2.page",
        "comparison.page",
        "two_column.page",
        "content_two_col.page",
        "market_comparison.page",
        "content3.page",
        "process.page",
        "content-process.page",
        "process_flow.page",
        "process_timeline.page",
        "timeline.page",
        "content4.page",
        "content-data.page",
        "content_data.page",
        "data_highlight.page",
        "data_analysis.page",
        "results_chart.page",
    }

    def can_render(self, *, template_page_name: str) -> bool:
        return template_page_name in self.semantic_templates

    def page_yaml(self, *, slide: PptdSlideContent, template_page_name: str) -> str:
        if template_page_name in {
            "content1.page",
            "content_bullets.page",
            "content-bullets.page",
            "bullets.page",
        }:
            return self._concept_page(slide=slide, template_page_name=template_page_name)
        if template_page_name in {
            "content2.page",
            "comparison.page",
            "two_column.page",
            "content_two_col.page",
            "market_comparison.page",
        }:
            return self._comparison_page(slide=slide, template_page_name=template_page_name)
        if template_page_name in {
            "content3.page",
            "process.page",
            "content-process.page",
            "process_flow.page",
            "process_timeline.page",
            "timeline.page",
        }:
            return self._process_page(slide=slide, template_page_name=template_page_name)
        return self._metrics_page(slide=slide, template_page_name=template_page_name)

    def _concept_page(self, *, slide: PptdSlideContent, template_page_name: str) -> str:
        items = self._display_items(slide, count=5)
        concept, concept_desc = self._split_item(items[0])
        shapes: list[_ShapeSpec] = [
            self._top_band(),
            _ShapeSpec("concept-definition-card", [58, 118, 430, 188], "#ffffff", border_color="#dbe4ee", border_width=1),
            _ShapeSpec("concept-diagram-area", [536, 118, 686, 378], "#f8fafc", border_color="#dbe4ee", border_width=1),
            _ShapeSpec("concept-takeaway-card", [58, 538, 1164, 92], "#ecfdf5", border_color="#bbf7d0", border_width=1),
            _ShapeSpec("concept-core-node", [790, 218, 178, 104], "$primary", "roundRect"),
            _ShapeSpec("concept-left-node", [594, 236, 142, 68], "#ffffff", "roundRect", border_color="#dbe4ee", border_width=1),
            _ShapeSpec("concept-right-node", [1020, 236, 142, 68], "#ffffff", "roundRect", border_color="#dbe4ee", border_width=1),
            _ShapeSpec("concept-bottom-node", [808, 382, 142, 68], "#ffffff", "roundRect", border_color="#dbe4ee", border_width=1),
            _ShapeSpec("concept-left-link", [736, 270, 54, 0], "#64748b", "straightConnector1", border_color="#64748b", border_width=3),
            _ShapeSpec("concept-right-link", [968, 270, 52, 0], "#64748b", "straightConnector1", border_color="#64748b", border_width=3),
            _ShapeSpec("concept-bottom-link", [879, 322, 0, 60], "#64748b", "straightConnector1", border_color="#64748b", border_width=3),
        ]
        texts: list[_TextSpec] = [
            self._title_text(self._short_label(slide.title, max_len=34)),
            self._badge_text("概念图解"),
            self._page_no_text(slide),
            _TextSpec("concept-definition-label", [88, 146, 360, 26], "先给一句可复述的定义", 18, "$primary", bold=True, wrap=False),
            _TextSpec("concept-definition-title", [88, 188, 360, 38], concept, 24, "$text", bold=True),
            _TextSpec("concept-definition-desc", [88, 236, 360, 46], concept_desc, 17, "#64748b", line_height=1.16),
            _TextSpec("concept-core-text", [812, 244, 134, 52], self._short_label(slide.title, max_len=6), 18, "#ffffff", "[center, middle]", bold=True, wrap=False),
            _TextSpec("concept-left-text", [608, 250, 114, 40], self._node_label(items[1]), 15, "$text", "[center, middle]", bold=True, wrap=False),
            _TextSpec("concept-right-text", [1034, 250, 114, 40], self._node_label(items[2]), 15, "$text", "[center, middle]", bold=True, wrap=False),
            _TextSpec("concept-bottom-text", [822, 396, 114, 40], self._node_label(items[3]), 15, "$text", "[center, middle]", bold=True, wrap=False),
            _TextSpec(
                "concept-takeaway-text",
                [92, 564, 1100, 40],
                f"课堂判断：{self._join_brief(items[1:5], max_len=48)}",
                18,
                "$text",
                "[center, middle]",
                bold=True,
            ),
        ]
        for idx, item in enumerate(items[1:4], start=1):
            y = 334 + (idx - 1) * 54
            shapes.append(_ShapeSpec(f"concept-point-dot-{idx}", [78, y + 8, 16, 16], "$accent", "ellipse"))
            texts.append(
                _TextSpec(
                    f"concept-point-{idx}",
                    [112, y, 386, 40],
                    self._short_label(item, max_len=28),
                    17,
                    "$text",
                    line_height=1.14,
                )
            )
        return self._page(
            page_type="content",
            source_template=template_page_name,
            shapes=shapes,
            texts=texts,
        )

    def _comparison_page(self, *, slide: PptdSlideContent, template_page_name: str) -> str:
        left_title, left_desc, left_items, right_title, right_desc, right_items = self._two_panel_groups(slide)
        title = self._short_label(slide.title, max_len=34)
        shapes: list[_ShapeSpec] = [
            self._top_band(),
            _ShapeSpec("comparison-left-card", [52, 124, 548, 438], "#ffffff", border_color="#dbeafe", border_width=1),
            _ShapeSpec("comparison-right-card", [680, 124, 548, 438], "#ffffff", border_color="#dcfce7", border_width=1),
            _ShapeSpec("comparison-left-rule", [52, 124, 548, 10], "$primary", shape_name="rect"),
            _ShapeSpec("comparison-right-rule", [680, 124, 548, 10], "$accent", shape_name="rect"),
            _ShapeSpec("comparison-summary", [96, 594, 1088, 72], "#eef2ff", border_color="#c7d2fe", border_width=1),
        ]
        texts: list[_TextSpec] = [
            self._title_text(title),
            self._badge_text("对比分析"),
            self._page_no_text(slide),
            _TextSpec("comparison-left-title", [88, 156, 460, 44], left_title, 28, "$primary", bold=True, wrap=False),
            _TextSpec("comparison-left-desc", [88, 208, 460, 68], left_desc, 18, "$text", line_height=1.2),
            _TextSpec("comparison-right-title", [716, 156, 460, 44], right_title, 28, "$accent", bold=True, wrap=False),
            _TextSpec("comparison-right-desc", [716, 208, 460, 68], right_desc, 18, "$text", line_height=1.2),
            _TextSpec(
                "comparison-summary-text",
                [124, 606, 1032, 48],
                f"课堂判断：{self._join_brief([left_items[-1], right_items[-1]], max_len=40)}",
                18,
                "$text",
                "[center, middle]",
                bold=True,
            ),
        ]
        for idx, item in enumerate(left_items[:3], start=1):
            y = 292 + (idx - 1) * 72
            shapes.append(_ShapeSpec(f"comparison-left-bullet-dot-{idx}", [90, y + 7, 18, 18], "$primary", "ellipse"))
            texts.append(_TextSpec(f"comparison-left-bullet-{idx}", [124, y, 410, 58], self._short_label(item, max_len=30), 17, "$text", line_height=1.18))
        for idx, item in enumerate(right_items[:3], start=1):
            y = 292 + (idx - 1) * 72
            shapes.append(_ShapeSpec(f"comparison-right-bullet-dot-{idx}", [718, y + 7, 18, 18], "$accent", "ellipse"))
            texts.append(_TextSpec(f"comparison-right-bullet-{idx}", [752, y, 410, 58], self._short_label(item, max_len=30), 17, "$text", line_height=1.18))
        return self._page(
            page_type="content",
            source_template=template_page_name,
            shapes=shapes,
            texts=texts,
        )

    def _process_page(self, *, slide: PptdSlideContent, template_page_name: str) -> str:
        items = self._process_items(slide)
        shapes: list[_ShapeSpec] = [self._top_band()]
        texts: list[_TextSpec] = [
            self._title_text(self._short_label(slide.title, max_len=34)),
            self._badge_text("流程推演"),
            self._page_no_text(slide),
            _TextSpec(
                "process-question",
                [96, 100, 1088, 36],
                f"问题：如何把“{self._short_label(slide.title, max_len=18)}”拆成可观察的状态变化？",
                21,
                "#64748b",
                "[center, middle]",
            ),
            _TextSpec(
                "process-takeaway",
                [124, 592, 1032, 54],
                f"结论：{self._join_brief(items, max_len=44)}",
                18,
                "$text",
                "[center, middle]",
                bold=True,
            ),
        ]
        card_width = 258
        gap = 42
        start_x = 68
        for idx, item in enumerate(items[:4], start=1):
            x = start_x + (idx - 1) * (card_width + gap)
            head, desc = self._split_item(item)
            shapes.extend(
                [
                    _ShapeSpec(f"process-card-{idx}", [x, 170, card_width, 318], "#ffffff", border_color="#dbe4ee", border_width=1),
                    _ShapeSpec(f"process-step-badge-{idx}", [x + 24, 198, 74, 34], "$primary", shape_name="rect"),
                ]
            )
            texts.extend(
                [
                    _TextSpec(f"process-step-label-{idx}", [x + 24, 205, 74, 20], f"STEP {idx}", 14, "#ffffff", "[center, middle]", bold=True, wrap=False),
                    _TextSpec(f"process-step-title-{idx}", [x + 24, 254, card_width - 48, 64], head, 24, "$text", bold=True),
                    _TextSpec(f"process-step-desc-{idx}", [x + 24, 336, card_width - 48, 72], self._teaching_step_desc(head, desc), 16, "#64748b", line_height=1.18),
                ]
            )
            if idx < 4:
                line_x = x + card_width + 9
                shapes.append(_ShapeSpec(f"process-arrow-{idx}", [line_x, 326, gap - 18, 0], "#64748b", "straightConnector1", border_color="#64748b", border_width=3))
        shapes.append(_ShapeSpec("process-takeaway-card", [96, 574, 1088, 84], "#ecfdf5", border_color="#bbf7d0", border_width=1))
        return self._page(
            page_type="content",
            source_template=template_page_name,
            shapes=shapes,
            texts=texts,
        )

    def _metrics_page(self, *, slide: PptdSlideContent, template_page_name: str) -> str:
        metrics = self._metric_items(slide)
        rows = self._table_rows(slide.bullets)
        if not rows:
            rows = [
                ("维度", "GBN", "SR"),
                ("重传范围", "从丢失帧开始批量重传", "只重传出错帧"),
                ("接收缓存", "通常不缓存乱序帧", "缓存乱序帧"),
                ("适用场景", "实现简单、误码率低", "链路质量波动更友好"),
            ]
        shapes: list[_ShapeSpec] = [self._top_band()]
        texts: list[_TextSpec] = [
            self._title_text(self._short_label(slide.title, max_len=34)),
            self._badge_text("量化观察"),
            self._page_no_text(slide),
        ]
        for idx, item in enumerate(metrics[:3], start=1):
            number, unit, desc = self._metric_parts(item, fallback=str(idx))
            x = 64 + (idx - 1) * 408
            shapes.append(_ShapeSpec(f"metric-card-{idx}", [x, 114, 354, 158], "#ffffff", border_color="#dbe4ee", border_width=1))
            texts.extend(
                [
                    _TextSpec(f"metric-number-{idx}", [x + 28, 142, 130, 58], number, 44, "$primary", bold=True, wrap=False),
                    _TextSpec(f"metric-unit-{idx}", [x + 166, 158, 128, 30], unit, 20, "$accent", "[left, middle]", bold=True, wrap=False),
                    _TextSpec(f"metric-desc-{idx}", [x + 28, 204, 292, 54], desc, 15, "#64748b", line_height=1.16),
                ]
            )
        shapes.append(_ShapeSpec("metric-matrix-card", [70, 330, 1140, 284], "#ffffff", border_color="#dbe4ee", border_width=1))
        rows = rows[:4]
        col_x = [102, 380, 708]
        col_w = [210, 282, 420]
        row_y = [358, 420, 482, 544]
        for idx, y in enumerate(row_y[: len(rows)]):
            fill = "#f1f5f9" if idx == 0 else "#ffffff"
            shapes.append(_ShapeSpec(f"metric-row-bg-{idx}", [90, y - 12, 1100, 52], fill, "rect"))
            for col, value in enumerate(rows[idx][:3]):
                texts.append(
                    _TextSpec(
                        f"metric-table-{idx}-{col}",
                        [col_x[col], y, col_w[col], 28],
                        value,
                        18 if idx else 17,
                        "$text" if idx else "#64748b",
                        "[left, middle]",
                        bold=idx == 0,
                    )
                )
        return self._page(
            page_type="content",
            source_template=template_page_name,
            shapes=shapes,
            texts=texts,
        )

    def _page(
        self,
        *,
        page_type: str,
        source_template: str,
        shapes: Iterable[_ShapeSpec],
        texts: Iterable[_TextSpec],
    ) -> str:
        lines = [
            f"pageType: {page_type}",
            f"# sourceTemplate: {source_template}",
            "background:",
            "  type: solid",
            '  color: "$background"',
            "elements:",
        ]
        for shape in shapes:
            lines.extend(self._shape_lines(shape))
        for text in texts:
            lines.extend(self._text_lines(text))
        return "\n".join(lines) + "\n"

    def _top_band(self) -> _ShapeSpec:
        return _ShapeSpec("common-top-band", [0, 0, 1280, 70], "$primary", "rect")

    def _title_text(self, title: str) -> _TextSpec:
        return _TextSpec("page-title", [42, 18, 820, 34], title, 26, "#ffffff", bold=True, wrap=False)

    def _badge_text(self, label: str) -> _TextSpec:
        return _TextSpec("page-mode-badge", [968, 19, 132, 28], label, 16, "#ffffff", "[center, middle]", bold=True, wrap=False)

    def _page_no_text(self, slide: PptdSlideContent) -> _TextSpec:
        return _TextSpec("page-number", [1148, 18, 88, 32], f"{slide.page_no:02d} / {slide.total:02d}", 13, "#ffffff", "[right, middle]", wrap=False)

    def _shape_lines(self, spec: _ShapeSpec) -> list[str]:
        lines = [
            f"  - elementId: {spec.element_id}",
            "    elementType: shape",
            f"    bounds: {self._bounds(spec.bounds)}",
            f"    shapeName: {spec.shape_name}",
            "    fill:",
            "      type: solid",
            f'      color: "{spec.color}"',
        ]
        if spec.opacity != 1.0:
            lines.append(f"      opacity: {spec.opacity:g}")
        if spec.border_color != "transparent" or spec.border_width:
            lines.extend(
                [
                    "    border:",
                    f'      color: "{spec.border_color}"',
                    f"      width: {spec.border_width}",
                ]
            )
        return lines

    def _text_lines(self, spec: _TextSpec) -> list[str]:
        lines = [
            f"  - elementId: {spec.element_id}",
            "    elementType: text",
            f"    bounds: {self._bounds(spec.bounds)}",
        ]
        if not spec.wrap:
            lines.append("    wrap: false")
        lines.extend(
            [
                "    content:",
                f"      align: {spec.align}",
                f"      fontSize: {spec.font_size}",
                f'      color: "{spec.color}"',
                f"      lineHeight: {spec.line_height:g}",
                "      text: |",
                f"        {self._paragraph(spec.text, bold=spec.bold)}",
            ]
        )
        return lines

    def _paragraph(self, value: str, *, bold: bool = False) -> str:
        body = self._plain(value)
        if bold:
            body = f"<strong>{body}</strong>"
        return f"<p>{body}</p>"

    def _bounds(self, bounds: list[int]) -> str:
        return "[" + ", ".join(str(item) for item in bounds) + "]"

    def _two_panel_groups(
        self, slide: PptdSlideContent
    ) -> tuple[str, str, list[str], str, str, list[str]]:
        groups = self._content_groups(slide.bullets)
        if len(groups) >= 2:
            left_name, left_items = groups[0]
            right_name, right_items = groups[1]
            return (
                self._short_label(left_name, max_len=14),
                self._short_label(left_items[0] if left_items else left_name, max_len=46),
                self._pad_items(left_items, count=3),
                self._short_label(right_name, max_len=14),
                self._short_label(right_items[0] if right_items else right_name, max_len=46),
                self._pad_items(right_items, count=3),
            )
        inline_groups = self._inline_comparison_groups(slide.bullets)
        if len(inline_groups) >= 2:
            left_name, left_items = inline_groups[0]
            right_name, right_items = inline_groups[1]
            return (
                self._short_label(left_name, max_len=14),
                self._short_label(left_items[0] if left_items else left_name, max_len=46),
                self._pad_items(left_items, count=3),
                self._short_label(right_name, max_len=14),
                self._short_label(right_items[0] if right_items else right_name, max_len=46),
                self._pad_items(right_items, count=3),
            )
        items = self._display_items(slide, count=6)
        if len({self._plain_text(item) for item in items}) <= 3:
            left = self._pad_items(items[:3], count=3)
            right = self._pad_items(
                [
                    f"适用判断：{self._short_label(items[0], max_len=22)}",
                    "操作路径：先识别边界，再确认控制条件",
                    "课堂追问：这种机制在哪些场景会失效？",
                ],
                count=3,
            )
            left_head, left_desc = "方法拆解", self._short_label(items[0], max_len=46)
            right_head, right_desc = "课堂判断", "把方法转成可验证的场景条件"
            return left_head, left_desc, left, right_head, right_desc, right
        split_at = max(1, min(3, len(items) // 2))
        left = self._pad_items(items[:split_at], count=3)
        right = self._pad_items(items[split_at:], count=3)
        left_head, left_desc = self._split_item(left[0])
        right_head, right_desc = self._split_item(right[0])
        return left_head, left_desc, left, right_head, right_desc, right

    def _inline_comparison_groups(self, bullets: list[str]) -> list[tuple[str, list[str]]]:
        aliases = (
            ("GBN", ("gbn", "后退n", "回退n", "go-back-n")),
            ("SR", ("sr", "选择重传", "selective repeat")),
        )
        collected: dict[str, list[str]] = {name: [] for name, _ in aliases}
        for raw in bullets:
            item = self._clean_bullet(raw)
            if not item:
                continue
            lowered = item.lower()
            for name, tokens in aliases:
                if any(token in lowered for token in tokens):
                    _, desc = self._split_item(item)
                    collected[name].append(desc)
                    break
        return [(name, items) for name, items in collected.items() if items]

    def _process_items(self, slide: PptdSlideContent) -> list[str]:
        groups = self._content_groups(slide.bullets)
        if groups and len(groups) >= 2:
            candidates = [f"{name}：{items[0]}" if items else name for name, items in groups]
            return self._pad_items(candidates, count=4)
        return self._display_items(slide, count=4)

    def _metric_items(self, slide: PptdSlideContent) -> list[str]:
        groups = self._content_groups(slide.bullets)
        if groups:
            flattened = [f"{name}：{items[0]}" if items else name for name, items in groups]
            return self._pad_items(flattened, count=3)
        return self._display_items(slide, count=3)

    def _table_rows(self, bullets: list[str]) -> list[tuple[str, ...]]:
        rows: list[tuple[str, ...]] = []
        for item in bullets:
            text = self._clean_bullet(item)
            if not (text.startswith("|") and text.endswith("|")):
                continue
            cells = tuple(cell.strip() for cell in text.strip("|").split("|") if cell.strip())
            if cells and not all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells):
                rows.append(cells)
        return rows

    def _content_groups(self, bullets: list[str]) -> list[tuple[str, list[str]]]:
        groups: list[tuple[str, list[str]]] = []
        current_name = ""
        current_items: list[str] = []
        for raw in bullets:
            item = self._clean_bullet(raw)
            if not item or (item.startswith("|") and item.endswith("|")):
                continue
            if self._is_heading(item):
                if current_name or current_items:
                    groups.append((current_name or "要点", current_items))
                current_name = item.rstrip("：:")
                current_items = []
                continue
            current_items.append(item)
        if current_name or current_items:
            groups.append((current_name or "要点", current_items))
        return [(name, items) for name, items in groups if name or items]

    def _display_items(self, slide: PptdSlideContent, *, count: int) -> list[str]:
        items = [self._plain_text(item) for item in slide.bullets if str(item).strip()]
        if not items:
            items = [f"围绕“{slide.title}”建立关键概念。"]
        return self._pad_items(items, count=count)

    def _split_item(self, item: str) -> tuple[str, str]:
        for sep in ("：", ":", "，", ","):
            if sep in item:
                head, desc = item.split(sep, 1)
                return self._short_label(head, max_len=12), self._short_label(desc, max_len=58)
        return self._short_label(item, max_len=12), self._short_label(item, max_len=58)

    def _metric_parts(self, item: str, *, fallback: str) -> tuple[str, str, str]:
        plain = self._plain_text(item)
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)(\s*%|倍|帧|bit|ms|s|Mbps)?", plain)
        if match:
            number = match.group(1)
            unit = (match.group(2) or "").strip() or "指标"
            desc = plain.replace(match.group(0), "", 1).strip(" ：:-，,") or plain
            return number, unit, self._short_label(desc, max_len=30)
        head, desc = self._split_item(plain)
        return fallback.zfill(2), head, self._short_label(desc, max_len=30)

    def _join_brief(self, items: list[str], *, max_len: int) -> str:
        text = "；".join(self._plain_text(item) for item in items if item)
        return self._short_label(text, max_len=max_len)

    def _node_label(self, value: str) -> str:
        head, _desc = self._split_item(value)
        return self._short_label(head, max_len=6)

    def _teaching_step_desc(self, head: str, desc: str) -> str:
        clean_head = self._plain_text(head)
        clean_desc = self._plain_text(desc)
        cjk_count = sum(1 for char in clean_desc if "\u4e00" <= char <= "\u9fff")
        formula_like = any(mark in clean_desc for mark in ("=", "/", "τ", "^", "<", ">")) and cjk_count < 6
        if formula_like:
            return "用该公式估算效率，结合发送时延和传播时延说明适用条件。"
        if len(clean_desc) < 18 or clean_desc == clean_head:
            return f"观察{clean_head}前后的状态变化，并说明触发条件。"
        return clean_desc

    def _pad_items(self, items: list[str], *, count: int) -> list[str]:
        cleaned = [self._plain_text(item) for item in items if str(item).strip()]
        if not cleaned:
            cleaned = ["建立概念、识别条件、迁移应用。"]
        return [*cleaned[:count], *([cleaned[-1]] * max(0, count - len(cleaned)))]

    def _short_label(self, value: str, *, max_len: int) -> str:
        plain = self._plain_text(value)
        return plain if len(plain) <= max_len else f"{plain[:max_len - 1]}..."

    def _clean_bullet(self, value: str) -> str:
        text = str(value or "").strip()
        text = re.sub(r"^\s*[-•]\s*", "", text)
        text = re.sub(r"^\s*\d+[.)、]\s*", "", text)
        return text.strip()

    def _is_heading(self, value: str) -> bool:
        text = value.strip()
        return len(text) <= 22 and text.endswith(("：", ":"))

    def _plain_text(self, value: str) -> str:
        text = str(value or "").strip()
        text = re.sub(r"<[^>]+>", "", text)
        return html.unescape(text)

    def _plain(self, value: str) -> str:
        return html.escape(self._plain_text(value), quote=False)
