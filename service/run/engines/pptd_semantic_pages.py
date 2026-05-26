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
        "concept.page",
        "framework.page",
        "content5.page",
        "content-cards.page",
        "content-concepts.page",
        "content_grid.page",
        "methodology.page",
        "discussion.page",
        "strategic_framework.page",
        "content2.page",
        "comparison.page",
        "two_column.page",
        "content_two_col.page",
        "market_comparison.page",
        "three_column_analysis.page",
        "matrix_analysis.page",
        "content3.page",
        "process.page",
        "content-process.page",
        "process_flow.page",
        "process_timeline.page",
        "timeline.page",
        "content-timeline.page",
        "milestone_roadmap.page",
        "action_plan.page",
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
        hint = self._plain_text(slide.layout_hint).lower()
        title_signal = self._plain_text(slide.title).lower()
        content_signal = self._content_signal(slide)
        if self._has_comparison_signal(title_signal):
            return self._comparison_page(slide=slide, template_page_name=template_page_name)
        if self._has_case_signal(title_signal):
            return self._concept_page(slide=slide, template_page_name=template_page_name)
        if self._has_metric_signal(title_signal):
            return self._metrics_page(slide=slide, template_page_name=template_page_name)
        if self._has_protocol_concept_signal(title_signal):
            return self._concept_page(slide=slide, template_page_name=template_page_name)
        if any(token in hint for token in ("comparison", "compare", "two-column", "two_col")):
            return self._comparison_page(slide=slide, template_page_name=template_page_name)
        if any(token in hint for token in ("stat", "metric", "data", "chart", "kpi", "table")) and self._has_metric_signal(content_signal):
            return self._metrics_page(slide=slide, template_page_name=template_page_name)
        if any(token in hint for token in ("timeline", "process", "flow", "step")):
            return self._process_page(slide=slide, template_page_name=template_page_name)
        if template_page_name in {
            "content1.page",
            "content_bullets.page",
            "content-bullets.page",
            "bullets.page",
            "concept.page",
            "framework.page",
            "content5.page",
            "content-cards.page",
            "content-concepts.page",
            "content_grid.page",
            "methodology.page",
            "discussion.page",
            "strategic_framework.page",
        }:
            return self._concept_page(slide=slide, template_page_name=template_page_name)
        if template_page_name in {
            "content2.page",
            "comparison.page",
            "two_column.page",
            "content_two_col.page",
            "market_comparison.page",
            "three_column_analysis.page",
            "matrix_analysis.page",
        }:
            return self._comparison_page(slide=slide, template_page_name=template_page_name)
        if template_page_name in {
            "content3.page",
            "process.page",
            "content-process.page",
            "process_flow.page",
            "process_timeline.page",
            "timeline.page",
            "content-timeline.page",
            "milestone_roadmap.page",
            "action_plan.page",
        }:
            return self._process_page(slide=slide, template_page_name=template_page_name)
        return self._metrics_page(slide=slide, template_page_name=template_page_name)

    def _content_signal(self, slide: PptdSlideContent) -> str:
        return self._plain_text(" ".join([slide.title, *slide.bullets])).lower()

    def _has_comparison_signal(self, text: str) -> bool:
        return any(token in text for token in (" vs", "vs.", "对比", "比较", "差异", "gbn", "回退n", "后退n")) and (
            self._has_sr_token(text) or "选择重传" in text or "selective repeat" in text
        )

    def _has_metric_signal(self, text: str) -> bool:
        return any(
            token in text
            for token in (
                "指标",
                "量化",
                "利用率",
                "窗口大小",
                "吞吐",
                "rtt",
                "bdp",
                " min(",
                "u =",
                "%",
            )
        )

    def _has_case_signal(self, text: str) -> bool:
        return any(token in text for token in ("协议实例", "实例", "案例", "应用场景", "ppp", "pppoe"))

    def _has_protocol_concept_signal(self, text: str) -> bool:
        if any(token in text for token in ("流程", "过程", "步骤", "process", "flow")):
            return False
        return any(token in text for token in ("协议", "arq", "crc", "成帧", "滑动窗口"))

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
            *self._source_note_text(slide),
            _TextSpec("concept-definition-label", [88, 146, 360, 26], "先给一句可复述的定义", 18, "$primary", bold=True, wrap=False),
            _TextSpec("concept-definition-title", [88, 188, 360, 38], concept, 24, "$text", bold=True),
            _TextSpec("concept-definition-desc", [88, 236, 360, 58], concept_desc, 15, "#64748b", line_height=1.1),
            _TextSpec("concept-core-text", [812, 244, 134, 52], self._short_label(slide.title, max_len=6), 18, "#ffffff", "[center, middle]", bold=True, wrap=False),
            _TextSpec("concept-left-text", [608, 250, 114, 40], self._node_label(items[1]), 12, "$text", "[center, middle]", bold=True, wrap=False),
            _TextSpec("concept-right-text", [1034, 250, 114, 40], self._node_label(items[2]), 12, "$text", "[center, middle]", bold=True, wrap=False),
            _TextSpec("concept-bottom-text", [822, 396, 114, 40], self._node_label(items[3]), 12, "$text", "[center, middle]", bold=True, wrap=False),
            _TextSpec(
                "concept-takeaway-text",
                [92, 564, 1100, 40],
                self._classroom_judgment(items[1:4]),
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
                    [112, y, 386, 44],
                    self._short_label(item, max_len=22),
                    15,
                    "$text",
                    line_height=1.08,
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
        summary_items = self._cross_comparison_items(slide.bullets) or [left_items[-1], right_items[-1]]
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
            *self._source_note_text(slide),
            _TextSpec("comparison-left-title", [88, 156, 460, 44], left_title, 28, "$primary", bold=True, wrap=False),
            _TextSpec("comparison-left-desc", [88, 208, 460, 68], left_desc, 18, "$text", line_height=1.2),
            _TextSpec("comparison-right-title", [716, 156, 460, 44], right_title, 28, "$accent", bold=True, wrap=False),
            _TextSpec("comparison-right-desc", [716, 208, 460, 68], right_desc, 18, "$text", line_height=1.2),
            _TextSpec(
                "comparison-summary-text",
                [124, 606, 1032, 48],
                self._classroom_judgment(summary_items),
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
            *self._source_note_text(slide),
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
            rows = self._metric_summary_rows(metrics)
        shapes: list[_ShapeSpec] = [self._top_band()]
        texts: list[_TextSpec] = [
            self._title_text(self._short_label(slide.title, max_len=34)),
            self._badge_text("量化观察"),
            self._page_no_text(slide),
            *self._source_note_text(slide),
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
            shapes.append(_ShapeSpec(f"metric-row-bg-{idx}", [90, y - 12, 1100, 56], fill, "rect"))
            for col, value in enumerate(rows[idx][:3]):
                texts.append(
                    _TextSpec(
                        f"metric-table-{idx}-{col}",
                        [col_x[col], y, col_w[col], 34],
                        self._metric_table_cell(value, col=col, is_header=idx == 0),
                        16 if idx else 15,
                        "$text" if idx else "#64748b",
                        "[left, middle]",
                        bold=idx == 0,
                        line_height=1.12,
                        wrap=False,
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

    def _source_note_text(self, slide: PptdSlideContent) -> list[_TextSpec]:
        note = self._short_label(str(getattr(slide, "source_note", "") or ""), max_len=56)
        if not note:
            return []
        return [
            _TextSpec(
                "source-note",
                [52, 674, 760, 22],
                f"资料依据：{note}",
                11,
                "#64748b",
                "[left, middle]",
                line_height=1.1,
                wrap=False,
            )
        ]

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
            if self._is_protocol_pair(left_name, right_name):
                left_items = self._panel_specific_items(left_items, "gbn")
                right_items = self._panel_specific_items(right_items, "sr")
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

    def _is_protocol_pair(self, left_name: str, right_name: str) -> bool:
        names = {self._protocol_key(left_name), self._protocol_key(right_name)}
        return names == {"gbn", "sr"}

    def _protocol_key(self, value: str) -> str:
        normalized = self._plain_text(value).lower()
        if "gbn" in normalized or "回退n" in normalized or "后退n" in normalized:
            return "gbn"
        if self._has_sr_token(normalized) or "选择重传" in normalized:
            return "sr"
        return normalized.strip()

    def _panel_specific_items(self, items: list[str], protocol: str) -> list[str]:
        del protocol
        filtered = [
            item
            for item in items
            if not self._mentions_both_protocols(item)
        ]
        return filtered or items

    def _cross_comparison_items(self, bullets: list[str]) -> list[str]:
        return [
            self._clean_bullet(item)
            for item in bullets
            if self._mentions_both_protocols(item)
        ][:2]

    def _classroom_judgment(self, items: list[str]) -> str:
        labels = self._concept_labels(items, max_len=34)
        text = labels or self._join_brief(items, max_len=34).strip()
        if text.startswith(("课堂判断：", "课堂判断:")):
            return text
        return f"课堂判断：{text}"

    def _concept_labels(self, items: list[str], *, max_len: int) -> str:
        labels: list[str] = []
        seen: set[str] = set()
        for item in items:
            head, _desc = self._split_item(item)
            label = self._clean_phrase(head)
            if not label or label in seen:
                continue
            candidate = label if not labels else "、".join([*labels, label])
            if len(candidate) > max_len:
                break
            labels.append(label)
            seen.add(label)
        return "、".join(labels)

    def _mentions_both_protocols(self, value: str) -> bool:
        text = self._plain_text(value).lower()
        has_gbn = "gbn" in text or "回退n" in text or "后退n" in text
        has_sr = self._has_sr_token(text) or "选择重传" in text
        return has_gbn and has_sr

    def _has_sr_token(self, text: str) -> bool:
        return bool(re.search(r"(?<![a-z0-9])sr(?![a-z0-9])", text))

    def _process_items(self, slide: PptdSlideContent) -> list[str]:
        groups = self._content_groups(slide.bullets)
        if groups and len(groups) >= 2:
            candidates = [f"{name}：{items[0]}" if items else name for name, items in groups]
            return self._pad_items(candidates, count=4)
        return self._display_items(slide, count=4)

    def _metric_items(self, slide: PptdSlideContent) -> list[str]:
        groups = self._content_groups(slide.bullets)
        if len(groups) == 1 and groups[0][0] == "要点":
            return self._display_items(slide, count=3)
        if groups:
            flattened: list[str] = []
            extras: list[str] = []
            for name, items in groups:
                flattened.append(f"{name}：{items[0]}" if items else name)
                extras.extend(
                    item
                    for item in items[1:]
                    if self._has_metric_signal(item.lower()) or self._has_formula_operator(item)
                )
            return self._pad_items([*flattened, *extras], count=3)
        return self._display_items(slide, count=3)

    def _metric_summary_rows(self, metrics: list[str]) -> list[tuple[str, str, str]]:
        rows: list[tuple[str, str, str]] = [("指标", "含义", "课堂判断")]
        for item in metrics[:3]:
            formula_row = self._formula_metric_row(item)
            if formula_row:
                rows.append(formula_row)
                continue
            head, desc = self._split_item(item)
            desc_text = desc if desc != head else item
            if self._has_formula_operator(desc_text):
                compact_desc = self._short_formula(desc_text, max_len=30)
            else:
                compact_desc = self._short_label(desc_text, max_len=24)
            rows.append(
                (
                    self._short_label(head, max_len=16),
                    compact_desc,
                    self._metric_judgment(item),
                )
            )
        return rows

    def _formula_metric_row(self, item: str) -> tuple[str, str, str] | None:
        plain = self._plain_text(item)
        formula = self._formula_text(plain)
        if not formula:
            return None
        label = self._formula_metric_label(plain)
        if not label:
            label = "公式"
        return (
            self._short_label(label, max_len=16),
            self._short_formula(formula, max_len=30),
            self._metric_judgment(item),
        )

    def _formula_metric_label(self, plain: str) -> str:
        for sep in ("：", ":"):
            if sep in plain:
                prefix, suffix = plain.split(sep, 1)
                if self._has_formula_operator(suffix):
                    return re.sub(r"[（(][^）)]{1,24}[）)]", "", prefix).strip(" ：:-，,、；;。")
        operator_match = re.search(r"\s*[=≈≤≥]\s*", plain)
        before_formula = plain[: operator_match.start()] if operator_match else plain
        symbol_match = re.search(r"([A-Za-z][A-Za-z0-9_]*)\s*$", before_formula)
        if symbol_match:
            before_formula = before_formula[: symbol_match.start()]
        return before_formula.strip(" ：:-，,、；;。")

    def _metric_table_cell(self, value: str, *, col: int, is_header: bool) -> str:
        text = self._plain_text(value)
        if is_header:
            return self._short_label(text, max_len=(10 if col == 0 else 14))
        if "=" in text or any(mark in text for mark in ("≈", "/", "min(")):
            return self._short_formula(text, max_len=(20 if col == 1 else 22))
        return self._short_label(text, max_len=(14 if col == 0 else 22 if col == 1 else 24))

    def _metric_judgment(self, item: str) -> str:
        text = self._plain_text(item)
        if any(token in text for token in ("≈", "%", "低", "高")):
            return "用于判断效率瓶颈"
        if any(token in text for token in ("窗口", "W", "w")):
            return "用于确定窗口规模"
        if any(token in text for token in ("延迟", "RTT", "传播")):
            return "用于估算链路时延影响"
        return "用于量化协议效果"

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
        items = [self._clean_bullet(item) for item in slide.bullets if str(item).strip()]
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
        formula_parts = self._formula_metric_parts(plain)
        if formula_parts:
            symbol, unit, desc = formula_parts
            if symbol != "公式":
                return fallback.zfill(2), symbol, desc
            return fallback.zfill(2), unit, desc
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)(\s*%|倍|帧|bit|b|ms|s|Mbps)?", plain)
        if match:
            unit = (match.group(2) or "").strip() or "指标"
            desc = plain.replace(match.group(0), "", 1).strip(" ：:-，,") or plain
            return fallback.zfill(2), self._short_label(unit, max_len=6), self._short_label(desc, max_len=30)
        head, desc = self._split_item(plain)
        return fallback.zfill(2), self._short_label(head, max_len=6), self._short_label(desc, max_len=30)

    def _formula_metric_parts(self, plain: str) -> tuple[str, str, str] | None:
        if not self._has_formula_operator(plain):
            return None
        formula = self._formula_text(plain)
        if not formula:
            return None
        symbol_match = re.match(r"\s*([A-Za-z][A-Za-z0-9_]*)\s*[=≈≤≥]", formula)
        number = symbol_match.group(1) if symbol_match else "公式"
        return self._short_formula(number, max_len=4), "公式", self._short_formula(formula, max_len=34)

    def _has_formula_operator(self, value: str) -> bool:
        return any(operator in value for operator in ("=", "≈", "≤", "≥"))

    def _formula_text(self, plain: str) -> str:
        text = re.sub(r"\s+", " ", str(plain or "").strip())
        if "：" in text:
            prefix, suffix = text.split("：", 1)
            if self._has_formula_operator(suffix) and ("公式" in prefix or len(prefix) <= 14):
                text = suffix.strip()
            elif self._has_formula_operator(prefix) and not self._has_formula_operator(suffix):
                return ""
        elif ":" in text:
            prefix, suffix = text.split(":", 1)
            if self._has_formula_operator(suffix) and ("formula" in prefix.lower() or "公式" in prefix or len(prefix) <= 18):
                text = suffix.strip()
            elif self._has_formula_operator(prefix) and not self._has_formula_operator(suffix):
                return ""
        operator_match = re.search(r"\s*([=≈≤≥])\s*", text)
        if not operator_match:
            return ""
        operator = operator_match.group(1)
        before = text[: operator_match.start()]
        after = text[operator_match.end() :]
        symbol_match = re.search(r"([A-Za-z][A-Za-z0-9_]*)\s*$", before)
        if symbol_match:
            text = f"{symbol_match.group(1)} {operator} {after.strip()}"
        return self._clean_phrase(text)

    def _short_formula(self, value: str, *, max_len: int) -> str:
        text = self._plain_text(value).strip()
        if len(text) <= max_len:
            return text
        compact = self._compact_formula(text)
        if len(compact) <= max_len:
            return compact
        return self._trim_incomplete_formula(compact[:max_len]).strip(" ：:，,、；;。.!！?？")

    def _compact_formula(self, value: str) -> str:
        text = self._plain_text(value).strip()
        replacements = {
            "T_frame": "Tf",
            "T_prop": "Tp",
            "frame_bits": "bits",
            "link_rate": "rate",
            "W_max": "Wmax",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        text = re.sub(r"\s*/\s*", "/", text)
        text = re.sub(r"\s*([*+−-])\s*", r"\1", text)
        text = re.sub(r"\s*([=≈≤≥])\s*", r" \1 ", text)
        text = re.sub(r"\(\s*", "(", text)
        text = re.sub(r"\s*\)", ")", text)
        text = re.sub(r"\s+", " ", text).strip()
        formula_head = re.split(r"[，,；;。]", text, maxsplit=1)[0].strip()
        if self._has_formula_operator(formula_head) and len(formula_head) >= 4:
            return formula_head
        text = re.sub(r"(其中|where).*$", "", text, flags=re.IGNORECASE).strip(" ：:，,、；;。.!！?？")
        return text or formula_head

    def _trim_incomplete_formula(self, value: str) -> str:
        text = value.strip()
        text = re.sub(r"[\s,，:：;；]*(其中|where)?\s*[A-Za-z]\s*(=|≈|≤|≥)\s*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"[\s,，:：;；]*(其中|where)?\s*[A-Za-z]\s*为\s*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"[\s,，:：;；]*(其中|where)\s*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"[\s,，:：;；]*(=|≈|≤|≥|/|\\+|−|-)\s*$", "", text)
        return text

    def _join_brief(self, items: list[str], *, max_len: int) -> str:
        cleaned = []
        seen: set[str] = set()
        for item in items:
            clean = self._plain_text(item)
            if not clean or clean in seen:
                continue
            seen.add(clean)
            cleaned.append(clean)
        text = "；".join(cleaned)
        if len(text) <= max_len:
            return text
        brief_parts: list[str] = []
        target_count = min(3, len(cleaned))
        for item in cleaned[:target_count]:
            head, desc = self._split_item(item)
            part_budget = max(12, max_len // max(1, target_count))
            if not desc or desc == head:
                part = self._clean_phrase(
                    self._compact_label(head, max_len=part_budget)
                )
            else:
                desc_budget = max(4, part_budget - len(head) - 1)
                if len(desc) > desc_budget and not re.search(r"[，,、；;]", desc):
                    part = head
                else:
                    short_desc = self._clean_phrase(
                        self._compact_label(desc, max_len=desc_budget)
                    )
                    part = f"{head}：{short_desc}" if short_desc else head
            candidate = part if not brief_parts else "；".join([*brief_parts, part])
            if len(candidate) > max_len and brief_parts:
                break
            brief_parts.append(part)
        if brief_parts:
            return "；".join(brief_parts)
        return self._short_label(text, max_len=max_len)

    def _clean_phrase(self, value: str) -> str:
        return self._plain_text(value).strip(" ：:，,、；;。.!！?？")

    def _node_label(self, value: str, *, max_len: int = 8) -> str:
        head, _desc = self._split_item(value)
        return self._short_label(head, max_len=max_len)

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
        return self._compact_label(plain, max_len=max_len)

    def _compact_label(self, value: str, *, max_len: int) -> str:
        plain = re.sub(r"\s+", " ", str(value or "").strip())
        if len(plain) <= max_len:
            return plain
        without_parenthetical = re.sub(r"[（(][^）)]{1,24}[）)]", "", plain).strip()
        if 0 < len(without_parenthetical) <= max_len:
            return without_parenthetical

        if max_len <= 14:
            if "、" in plain:
                fitted = self._fit_delimited_parts(plain, max_len=max_len)
                if fitted:
                    return fitted
            for sep in ("：", ":", "，", ",", "；", ";", "。"):
                if sep in plain:
                    head = plain.split(sep, 1)[0].strip()
                    if head:
                        return self._safe_truncate(head, max_len=max_len)
            return self._safe_truncate(plain, max_len=max_len)

        clauses = [
            clause.strip()
            for clause in re.split(r"[。！？!?；;]", plain)
            if clause.strip()
        ]
        for clause in clauses:
            if len(clause) <= max_len:
                return clause
        if clauses:
            comma_parts = [
                part.strip()
                for part in re.split(r"[，,、]", clauses[0])
                if part.strip()
            ]
            if comma_parts:
                fitted = self._fit_parts(comma_parts, max_len=max_len)
                if fitted:
                    return fitted
                return self._safe_truncate(comma_parts[0], max_len=max_len)
        return self._safe_truncate(plain, max_len=max_len)

    def _safe_truncate(self, value: str, *, max_len: int) -> str:
        text = str(value or "").strip()
        if len(text) <= max_len:
            return text
        text = text[:max_len].strip()
        for open_mark, close_mark in (("（", "）"), ("(", ")"), ("《", "》")):
            if text.count(open_mark) > text.count(close_mark):
                text = text.rsplit(open_mark, 1)[0].strip()
        return text.strip(" ：:，,、；;。.!！?？")

    def _fit_delimited_parts(self, value: str, *, max_len: int) -> str:
        parts = [part.strip() for part in value.split("、") if part.strip()]
        return self._fit_parts(parts, max_len=max_len)

    def _fit_parts(self, parts: list[str], *, max_len: int) -> str:
        fitted = ""
        for part in parts:
            candidate = part if not fitted else f"{fitted}、{part}"
            if len(candidate) > max_len:
                break
            fitted = candidate
        return fitted

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
