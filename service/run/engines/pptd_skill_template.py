from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from .pptd_contracts import PptdSlideContent


class PptdSkillTemplateDeck:
    template_name = "education-1"

    def __init__(self, template_name: str | None = None) -> None:
        if template_name:
            self.template_name = template_name

    def write_project(
        self,
        *,
        pptd_path: Path,
        title: str,
        nodes: list[Any],
        slide_count: int,
        theme: dict[str, Any],
        skill_dir: Path,
        template_style: str = "",
        template_id: str | None = None,
    ) -> bool:
        self.template_name = self._resolve_template_name(
            skill_dir=skill_dir,
            template_style=template_style,
            template_id=template_id,
        )
        template_dir = skill_dir / "guideline" / "design" / "template" / self.template_name
        deck_template = template_dir / f"{self.template_name}.pptd"
        pages_dir = template_dir / "pages"
        if not deck_template.is_file() or not pages_dir.is_dir():
            return False
        self._current_page_names = {
            item.name for item in pages_dir.iterdir() if item.is_file() and item.suffix == ".page"
        }

        target_pages_dir = pptd_path.parent / "pages"
        target_pages_dir.mkdir(parents=True, exist_ok=True)
        total = max(1, slide_count, len(nodes))
        page_paths: list[str] = []
        for index in range(total):
            slide = self._slide_content(index=index, total=total, nodes=nodes)
            template_page = pages_dir / self._template_page_name(slide=slide)
            if not template_page.is_file():
                return False
            page_name = f"slide-{index + 1:02d}.page"
            page_paths.append(f"pages/{page_name}")
            rendered_page = self._sanitize_rendered_page(
                self._render_page(template_page.read_text(encoding="utf-8"), slide=slide)
            )
            (target_pages_dir / page_name).write_text(
                rendered_page,
                encoding="utf-8",
            )

        pptd_path.write_text(
            self._render_deck(
                deck_template.read_text(encoding="utf-8"),
                title=title,
                page_paths=page_paths,
                theme=theme,
            ),
            encoding="utf-8",
        )
        return True

    def _render_deck(
        self,
        template: str,
        *,
        title: str,
        page_paths: list[str],
        theme: dict[str, Any],
    ) -> str:
        lines = template.splitlines()
        rendered: list[str] = [f"title: {self._yaml_plain(title)}"]
        in_pages = False
        for line in lines[1:]:
            if line.strip() == "pages:":
                in_pages = True
                break
            rendered.append(line)
        rendered = self._apply_theme_overrides(rendered, theme)
        rendered.append("pages:")
        rendered.extend(f"  - {path}" for path in page_paths)
        return "\n".join(rendered) + "\n"

    def _render_page(self, text: str, *, slide: PptdSlideContent) -> str:
        kind = self._template_page_name(slide=slide)
        if kind == "cover.page":
            return self._render_cover(text, slide)
        if kind == "toc.page":
            return self._render_toc(text, slide)
        if kind in {"section.page", "chapter.page", "chapter1.page", "chapter2.page"}:
            return self._render_section(text, slide)
        if kind in {"content1.page", "content_bullets.page", "content-bullets.page", "bullets.page"}:
            return self._render_bullet_list(text, slide)
        if kind in {"content2.page", "comparison.page", "two_column.page", "content_two_col.page"}:
            return self._render_two_panel(text, slide)
        if kind in {
            "content3.page",
            "process.page",
            "content-process.page",
            "process_flow.page",
            "process_timeline.page",
            "timeline.page",
        }:
            return self._render_process_case(text, slide)
        if kind in {"content4.page", "content-data.page", "content_data.page", "data_highlight.page"}:
            return self._render_data_cards(text, slide)
        if kind in {"content5.page", "framework.page", "content-concepts.page", "content_grid.page"}:
            return self._render_concept_map(text, slide)
        if kind == "process.page":
            return self._render_process(text, slide)
        if kind == "framework.page":
            return self._render_framework(text, slide)
        if kind == "final.page":
            return self._render_final(text, slide)
        return self._render_concept(text, slide)

    def _render_cover(self, text: str, slide: PptdSlideContent) -> str:
        subtitle = self._short_label(
            slide.bullets[0] if slide.bullets else "课程核心概念与实践路径",
            max_len=36,
        )
        highlight = self._short_label(
            slide.bullets[1] if len(slide.bullets) > 1 else "结构化路径 · 启发式引导",
            max_len=28,
        )
        title_size = self._cover_title_font_size(slide.title)
        replacements = {
            "main-title": self._p(slide.title),
            "subtitle": self._p(subtitle),
            "highlight-text": self._p(highlight),
            "footer-info": self._p("NeoSpectra · PPTD Courseware"),
            "cover-title": self._p(
                f'<span style="font-size:{title_size}px;"><strong>{self._plain(slide.title)}</strong></span>',
                escaped=False,
            ),
            "cover-subject": self._p(subtitle),
            "cover-info": self._p(highlight),
            "cover-main-title": self._p(
                f'<span style="font-size:{title_size}px;"><strong>{self._plain(slide.title)}</strong></span>',
                escaped=False,
            ),
            "cover-subtitle-en": self._p(subtitle),
            "cover-author": self._p("NeoSpectra"),
            "subject-label": self._p("课程"),
        }
        return self._generic_fill_text_blocks(
            self._replace_many(text, replacements),
            slide=slide,
            skip=set(replacements),
        )

    def _cover_title_font_size(self, title: str) -> int:
        length = len(str(title or "").strip())
        if length <= 14:
            return 56
        if length <= 24:
            return 44
        return 36

    def _render_toc(self, text: str, slide: PptdSlideContent) -> str:
        items = self._display_items(slide, count=4)
        replacements = {
            "page-title": self._p("学习路径导航"),
            "toc-title-cn": self._p("<strong>学习路径</strong>", escaped=False),
            "toc-title-en": self._p("Learning Roadmap"),
        }
        for idx in range(1, 5):
            item = items[idx - 1] if idx <= len(items) else f"模块 {idx}"
            replacements[f"module{idx}-title"] = self._p(f"<strong>{self._plain(item)}</strong>", escaped=False)
            replacements[f"module{idx}-desc"] = self._p("围绕本模块建立关键概念、触发条件与应用判断。")
            replacements[f"title{idx}"] = self._p(f"<strong>{self._plain(item)}</strong>", escaped=False)
            replacements[f"desc{idx}"] = self._p("建立概念、识别条件、迁移到真实问题。")
        return self._replace_many(text, replacements)

    def _render_section(self, text: str, slide: PptdSlideContent) -> str:
        items = self._display_items(slide, count=3)
        replacements = {
            "section-title": self._p(f"<strong>{self._plain(slide.title)}</strong>", escaped=False),
            "section-desc": self._p(self._join_brief(items, max_len=62)),
            "chapter-badge-text": self._p(f"SECTION {slide.page_no:02d}"),
            "ch-num": self._p(f"CHAPTER {slide.page_no:02d}"),
            "ch-title": self._p(f"<strong>{self._plain(slide.title)}</strong>", escaped=False),
            "ch-subtitle": self._p(self._join_brief(items, max_len=48)),
            "preview-label": self._p("本节要点"),
        }
        for idx in range(1, 4):
            replacements[f"preview-item{idx}"] = self._p(self._short_label(items[idx - 1], max_len=26))
        return self._generic_fill_text_blocks(
            self._replace_many(text, replacements),
            slide=slide,
            skip=set(replacements),
        )

    def _render_bullet_list(self, text: str, slide: PptdSlideContent) -> str:
        items = self._display_items(slide, count=5)
        replacements = {
            "page-title": self._p(slide.title),
            "subject-tag-text": self._p("<strong>机制拆解</strong>", escaped=False),
            "note-text": self._p(f"<strong>课堂提示：</strong>{self._plain(self._join_brief(items[:2], max_len=52))}", escaped=False),
            "formula-label": self._p("抓手"),
            "formula-text": self._p(self._short_label(items[0], max_len=30)),
        }
        for idx, item in enumerate(items[:5], start=1):
            replacements[f"bullet{idx}-text"] = self._p(self._bullet_line(item, idx=idx), escaped=False)
        return self._generic_fill_text_blocks(
            self._replace_many(text, replacements),
            slide=slide,
            skip=set(replacements),
        )

    def _render_two_panel(self, text: str, slide: PptdSlideContent) -> str:
        items = self._display_items(slide, count=6)
        left = items[:3]
        right = items[3:6] if len(items) > 3 else items[:3]
        left_head, left_desc = self._split_item(left[0])
        right_head, right_desc = self._split_item(right[0])
        replacements = {
            "page-title": self._p(slide.title),
            "subject-tag-text": self._p("<strong>对比分析</strong>", escaped=False),
            "left-title-label": self._p(f"<strong>{self._plain(left_head)}</strong>", escaped=False),
            "right-title-label": self._p(f"<strong>{self._plain(right_head)}</strong>", escaped=False),
            "left-definition": self._p(left_desc),
            "right-definition": self._p(right_desc),
            "left-feat-label": self._p("关键特征"),
            "right-feat-label": self._p("关键特征"),
            "left-apply-label": self._p("适用判断"),
            "right-apply-label": self._p("适用判断"),
            "left-apply-text": self._p(self._short_label(left[-1], max_len=34)),
            "right-apply-text": self._p(self._short_label(right[-1], max_len=34)),
            "left-example-text": self._p(f"例：{self._short_label(left[0], max_len=28)}"),
            "right-example-text": self._p(f"例：{self._short_label(right[0], max_len=28)}"),
        }
        for idx in range(1, 4):
            replacements[f"left-feat{idx}"] = self._p(self._short_label(left[min(idx - 1, len(left) - 1)], max_len=32))
            replacements[f"right-feat{idx}"] = self._p(self._short_label(right[min(idx - 1, len(right) - 1)], max_len=32))
        return self._generic_fill_text_blocks(
            self._replace_many(text, replacements),
            slide=slide,
            skip=set(replacements),
        )

    def _render_process_case(self, text: str, slide: PptdSlideContent) -> str:
        items = self._display_items(slide, count=4)
        replacements = {
            "page-title": self._p(slide.title),
            "example-tag-text": self._p("<strong>流程推演</strong>", escaped=False),
            "question-label": self._p("问题"),
            "question-text": self._p(f"这个机制如何一步步解决“{self._short_label(slide.title, max_len=18)}”？"),
            "answer-title": self._p("结论"),
            "answer-text": self._p(self._join_brief(items, max_len=58)),
            "answer-tip": self._p("用状态变化复述，而不是背定义。"),
        }
        for idx in range(1, 4):
            head, desc = self._split_item(items[min(idx - 1, len(items) - 1)])
            replacements[f"step{idx}-label"] = self._p(f"STEP {idx}")
            replacements[f"step{idx}-text"] = self._p(f"<strong>{self._plain(head)}</strong><br/>{self._plain(desc)}", escaped=False)
        return self._generic_fill_text_blocks(
            self._replace_many(text, replacements),
            slide=slide,
            skip=set(replacements),
        )

    def _render_data_cards(self, text: str, slide: PptdSlideContent) -> str:
        items = self._display_items(slide, count=3)
        replacements = {
            "page-title": self._p(slide.title),
            "data-tag-text": self._p("<strong>量化观察</strong>", escaped=False),
            "chart-title": self._p("机制效果示意"),
        }
        for idx, item in enumerate(items[:3], start=1):
            number, unit, desc = self._metric_parts(item, fallback=str(idx))
            replacements[f"card{idx}-number"] = self._p(number)
            replacements[f"card{idx}-unit"] = self._p(unit)
            replacements[f"card{idx}-desc"] = self._p(desc)
        return self._generic_fill_text_blocks(
            self._replace_many(text, replacements),
            slide=slide,
            skip=set(replacements),
        )

    def _render_concept_map(self, text: str, slide: PptdSlideContent) -> str:
        items = self._display_items(slide, count=4)
        positions = ("lu", "ru", "ld", "rd")
        replacements = {
            "page-title": self._p(slide.title),
            "concept-tag-text": self._p("<strong>概念网络</strong>", escaped=False),
            "center-node-text": self._p(f"<strong>{self._short_label(slide.title, max_len=10)}</strong>", escaped=False),
            "think-text": self._p(f"把四个节点连成一句话：{self._plain(self._join_brief(items, max_len=46))}"),
        }
        for pos, item in zip(positions, items):
            head, desc = self._split_item(item)
            replacements[f"sub-{pos}-text"] = self._p(f"<strong>{self._plain(head)}</strong>", escaped=False)
            replacements[f"sub-{pos}-desc"] = self._p(desc)
        return self._generic_fill_text_blocks(
            self._replace_many(text, replacements),
            slide=slide,
            skip=set(replacements),
        )

    def _render_concept(self, text: str, slide: PptdSlideContent) -> str:
        items = self._display_items(slide, count=4)
        replacements = {
            "page-title": self._p(slide.title),
            "content-text": self._rich_content(slide),
            "center-text": self._p("<strong>核心概念</strong>", escaped=False),
            "memory-text": self._p(f"<strong>关键洞察：</strong>{self._plain(items[0])}", escaped=False),
            "subject-tag-text": self._p("<strong>课程</strong>", escaped=False),
        }
        for idx, item in enumerate(items[:4], start=1):
            replacements[f"node{idx}-text"] = self._p(self._short_label(item, max_len=8))
            replacements[f"bullet{idx}-text"] = self._p(self._bullet_line(item, idx=idx), escaped=False)
            replacements[f"point{idx}-text"] = self._p(item)
        return self._generic_fill_text_blocks(
            self._replace_many(text, replacements),
            slide=slide,
            skip=set(replacements),
        )

    def _render_process(self, text: str, slide: PptdSlideContent) -> str:
        items = self._display_items(slide, count=4)
        replacements = {"page-title": self._p(slide.title), "diagram-title": self._p("<strong>机制流程</strong>", escaped=False)}
        for idx, item in enumerate(items[:4], start=1):
            head, desc = self._split_item(item)
            replacements[f"step{idx}-title"] = self._p(f"<strong>{self._plain(head)}</strong>", escaped=False)
            replacements[f"step{idx}-desc"] = self._p(desc)
            replacements[f"step{idx}-text"] = self._p(self._bullet_line(item, idx=idx), escaped=False)
        cycle = ["输入", "判断", "调整", "反馈"]
        for element_id, value in zip(("input-text", "process-text", "output-text", "reflect-text"), cycle):
            replacements[element_id] = self._p(f"<strong>{value}</strong>", escaped=False)
        return self._generic_fill_text_blocks(
            self._replace_many(text, replacements),
            slide=slide,
            skip=set(replacements),
        )

    def _render_framework(self, text: str, slide: PptdSlideContent) -> str:
        items = self._display_items(slide, count=5)
        replacements = {"page-title": self._p(slide.title), "center-text": self._p("<strong>框架</strong>", escaped=False)}
        for key, item in zip(("node-l-text", "node-e-text", "node-a-text", "node-r-text", "node-n-text"), items):
            replacements[key] = self._p(f"<strong>{self._short_label(item, max_len=10)}</strong>", escaped=False)
        return self._generic_fill_text_blocks(
            self._replace_many(text, replacements),
            slide=slide,
            skip=set(replacements),
        )

    def _render_final(self, text: str, slide: PptdSlideContent) -> str:
        items = self._display_items(slide, count=4)
        replacements = {
            "thank-you": self._p(slide.title),
            "subtitle": self._p("复盘、迁移、应用"),
            "action-text": "\n".join(self._p(f"• {item}") for item in items[:4]),
            "footer": self._p("NeoSpectra · Generated Courseware"),
            "summary-title": self._p(slide.title),
            "thanks-text": self._p(slide.title),
            "thanks-sub": self._p("继续把概念迁移到真实问题"),
            "final-title": self._p(slide.title),
            "right-sub": self._p("课堂迁移"),
        }
        for idx, item in enumerate(items[:4], start=1):
            replacements[f"point{idx}-text"] = self._p(item)
            replacements[f"think{idx}-text"] = self._p(item)
        return self._generic_fill_text_blocks(
            self._replace_many(text, replacements),
            slide=slide,
            skip=set(replacements),
        )

    def _replace_many(self, text: str, replacements: dict[str, str]) -> str:
        for element_id, value in replacements.items():
            text = self._replace_text_block(text, element_id=element_id, value=value)
        return text

    def _replace_text_block(self, text: str, *, element_id: str, value: str) -> str:
        lines = text.splitlines()
        marker = f"elementId: {element_id}"
        start = next((idx for idx, line in enumerate(lines) if line.strip().lstrip("- ") == marker), None)
        if start is None:
            return text
        text_idx = next((idx for idx in range(start + 1, len(lines)) if lines[idx].strip() == "text: |"), None)
        if text_idx is None:
            return text
        end = text_idx + 1
        while end < len(lines):
            if lines[end].strip() and len(lines[end]) - len(lines[end].lstrip(" ")) <= 6:
                break
            end += 1
        block = [f"        {line}" for line in value.splitlines() or [""]]
        return "\n".join([*lines[: text_idx + 1], *block, *lines[end:]]) + "\n"

    def _template_page_name(self, *, slide: PptdSlideContent) -> str:
        available = self._available_page_names()
        index = slide.index
        total = slide.total
        page_type = slide.page_type.lower()
        if index == 0 or page_type == "cover":
            return self._first_existing(["cover.page", "page1.page"], available) or "cover.page"
        if index == total - 1 or page_type in {"summary", "final"}:
            return (
                self._first_existing(["final.page", "ending.page", "conclusion.page", "page11.page"], available)
                or "final.page"
            )
        if page_type in {"section", "chapter"}:
            section = self._first_existing(["section.page", "chapter.page", "chapter1.page", "chapter2.page"], available)
            if section:
                return section
        if index == 1 and total >= 5:
            toc = self._first_existing(["toc.page", "page2.page"], available)
            if toc:
                return toc
        content_pages = [
            item
            for item in [
                "concept.page",
                "process.page",
                "framework.page",
                "comparison.page",
                "case_study.page",
                "practice.page",
                "content1.page",
                "content2.page",
                "content3.page",
                "content4.page",
                "content5.page",
                "content-cards.page",
                "content-concepts.page",
                "content-process.page",
                "content-timeline.page",
                "methodology.page",
                "discussion.page",
                "data_analysis.page",
                "results_chart.page",
                "three_column_analysis.page",
                "process_timeline.page",
                "market_comparison.page",
                "strategic_framework.page",
                "milestone_roadmap.page",
                "timeline.page",
                "matrix_analysis.page",
                "action_plan.page",
            ]
            if item in available
        ]
        if content_pages:
            preferred = self._preferred_content_pages(slide=slide)
            selected = self._first_existing(preferred, set(content_pages))
            if selected:
                return selected
            return content_pages[(index - 1) % len(content_pages)]
        numbered = sorted(item for item in available if item.startswith("page") and item.endswith(".page"))
        if numbered:
            return numbered[min(index, len(numbered) - 1)]
        return ["concept.page", "process.page", "framework.page"][(index - 1) % 3]

    def _slide_content(self, *, index: int, total: int, nodes: list[Any]) -> PptdSlideContent:
        node = nodes[index] if index < len(nodes) else None
        title = str(getattr(node, "title", "") or f"Slide {index + 1}")
        bullets = [str(item) for item in list(getattr(node, "bullets", []) or [])[:6]]
        page_type = str(
            getattr(getattr(node, "page_type", ""), "value", "")
            or getattr(node, "page_type", "")
            or "content"
        )
        layout_hint = str(getattr(node, "layout_hint", "") or "")
        return PptdSlideContent(
            index=index,
            total=total,
            title=title,
            bullets=bullets,
            page_type=page_type,
            layout_hint=layout_hint,
        )

    def _preferred_content_pages(self, *, slide: PptdSlideContent) -> list[str]:
        hint = slide.layout_hint.lower()
        if any(token in hint for token in ("two-column", "two_col", "showcase", "comparison", "compare")):
            return ["content2.page", "comparison.page", "two_column.page", "market_comparison.page"]
        if any(token in hint for token in ("timeline", "process", "flow", "step")):
            return ["content3.page", "process.page", "content-process.page", "process_timeline.page", "timeline.page"]
        if any(token in hint for token in ("data", "chart", "metric", "kpi")):
            return ["content4.page", "content-data.page", "data_highlight.page", "content_chart.page"]
        if any(token in hint for token in ("framework", "concept", "map", "grid")):
            return ["content5.page", "framework.page", "content-concepts.page", "content_grid.page"]

        signal = " ".join([slide.title, *slide.bullets]).lower()
        if any(token in signal for token in (" vs ", "gbn", "sr", "对比", "比较", "差异", "优劣", "versus")):
            return ["content2.page", "comparison.page", "two_column.page", "market_comparison.page"]
        if any(token in signal for token in ("框架", "结构", "关系", "协同", "概念", "framework", "concept", "map")):
            return ["content5.page", "framework.page", "content-concepts.page", "content_grid.page"]
        if any(token in signal for token in ("流程", "步骤", "机制", "过程", "滑动窗口", "确认", "重传", "timeline", "process", "flow")):
            return ["content3.page", "process.page", "content-process.page", "process_timeline.page", "timeline.page"]
        if any(token in signal for token in ("数据", "指标", "效率", "利用率", "%", "chart", "data", "metric", "ratio")):
            return ["content4.page", "content-data.page", "data_highlight.page", "content_chart.page"]
        return ["content1.page", "content_bullets.page", "content-bullets.page", "bullets.page"]

    def _display_items(self, slide: PptdSlideContent, *, count: int) -> list[str]:
        items = [self._plain(item) for item in slide.bullets if str(item).strip()]
        if not items:
            items = [f"围绕“{slide.title}”建立关键概念。"]
        return [*items[:count], *([items[-1]] * max(0, count - len(items)))]

    def _rich_content(self, slide: PptdSlideContent) -> str:
        items = self._display_items(slide, count=4)
        lines = [self._p(f"<strong>{self._plain(slide.title)}</strong>", escaped=False)]
        for item in items[:4]:
            lines.append(self._p(f'<span style="color:$accent">•</span> {self._plain(item)}', escaped=False))
        return "\n".join(lines)

    def _split_item(self, item: str) -> tuple[str, str]:
        for sep in ("：", ":", "，", ","):
            if sep in item:
                head, desc = item.split(sep, 1)
                return self._short_label(head, max_len=12), self._plain(desc)[:42]
        return self._short_label(item, max_len=12), self._plain(item)[:42]

    def _join_brief(self, items: list[str], *, max_len: int) -> str:
        text = "；".join(self._plain(item) for item in items if item)
        return text if len(text) <= max_len else f"{text[:max_len - 1]}…"

    def _metric_parts(self, item: str, *, fallback: str) -> tuple[str, str, str]:
        plain = self._plain(item)
        match = re.search(r"([0-9]+(?:\\.[0-9]+)?)(\\s*%|倍|帧|bit|ms|s)?", plain)
        if match:
            number = match.group(1)
            unit = (match.group(2) or "").strip() or "指标"
            desc = plain.replace(match.group(0), "", 1).strip(" ：:-，,") or plain
            return number, unit, self._short_label(desc, max_len=34)
        head, desc = self._split_item(plain)
        return fallback.zfill(2), head, self._short_label(desc, max_len=34)

    def _short_label(self, value: str, *, max_len: int) -> str:
        plain = self._plain(value)
        return plain if len(plain) <= max_len else f"{plain[:max_len - 1]}…"

    def _plain(self, value: str) -> str:
        return html.escape(str(value).strip(), quote=False)

    def _p(self, value: str, *, escaped: bool = True) -> str:
        body = self._plain(value) if escaped else value
        return f"<p>{body}</p>"

    def _bullet_line(self, item: str, *, idx: int) -> str:
        labels = ("定义", "机制", "条件", "应用", "迁移")
        label = labels[min(idx - 1, len(labels) - 1)]
        return f'<strong style="color:$primary;">{label}：</strong>{self._plain(item)}'

    def _generic_fill_text_blocks(
        self,
        text: str,
        *,
        slide: PptdSlideContent,
        skip: set[str] | None = None,
    ) -> str:
        skip = skip or set()
        for element_id in self._element_ids(text):
            if (
                element_id in skip
                or self._is_decorative_text_id(element_id)
                or self._element_type(text, element_id=element_id) != "text"
            ):
                continue
            value = self._generic_value(element_id=element_id, slide=slide)
            if value:
                text = self._replace_text_block(text, element_id=element_id, value=value)
        return text

    def _generic_value(self, *, element_id: str, slide: PptdSlideContent) -> str:
        lowered = element_id.lower()
        items = self._display_items(slide, count=5)
        if lowered in {"subject-label", "subject-tag-text"}:
            return self._p("课程")
        if "page-num" in lowered or lowered.endswith("-num") or lowered in {"num", "chapter-number"}:
            return self._p(str(slide.page_no))
        if lowered == "formula-label":
            return self._p("要点")
        if lowered == "formula-text":
            return self._p(self._short_label(self._item_for_id(element_id, items), max_len=30))
        if "title" in lowered and not any(token in lowered for token in ("subtitle", "sub-title")):
            if any(token in lowered for token in ("card", "node", "step", "point", "title1", "title2", "title3", "title4")):
                return self._p(f"<strong>{self._plain(self._item_for_id(element_id, items))}</strong>", escaped=False)
            return self._p(f"<strong>{self._plain(slide.title)}</strong>", escaped=False)
        if any(token in lowered for token in ("subtitle", "sub", "desc", "content", "definition", "apply", "example")):
            return self._p(self._item_for_id(element_id, items))
        if any(token in lowered for token in ("bullet", "point", "feat", "step", "item", "text")):
            return self._p(self._item_for_id(element_id, items))
        if "label" in lowered or "tag" in lowered:
            return self._p("课程")
        return ""

    def _sanitize_rendered_page(self, text: str) -> str:
        text = self._remove_text_element_wrap_keys(text)
        return self._replace_bounds(text, element_id="formula-text", bounds=[230, 582, 850, 52])

    def _remove_text_element_wrap_keys(self, text: str) -> str:
        lines = text.splitlines()
        rendered: list[str] = []
        for line in lines:
            indent = len(line) - len(line.lstrip(" "))
            if indent == 4 and line.strip() == "wrap: false":
                continue
            rendered.append(line)
        return "\n".join(rendered) + "\n"

    def _replace_bounds(self, text: str, *, element_id: str, bounds: list[int]) -> str:
        lines = text.splitlines()
        marker = f"elementId: {element_id}"
        start = next((idx for idx, line in enumerate(lines) if line.strip().lstrip("- ") == marker), None)
        if start is None:
            return text
        bounds_idx = next((idx for idx in range(start + 1, len(lines)) if lines[idx].strip() == "bounds:"), None)
        if bounds_idx is None:
            return text
        end = bounds_idx + 1
        while end < len(lines):
            stripped = lines[end].strip()
            if stripped and not stripped.startswith("- "):
                break
            end += 1
        block = ["    bounds:", *(f"      - {item}" for item in bounds)]
        return "\n".join([*lines[:bounds_idx], *block, *lines[end:]]) + "\n"

    def _item_for_id(self, element_id: str, items: list[str]) -> str:
        digits = "".join(ch for ch in element_id if ch.isdigit())
        if digits:
            index = max(0, min(len(items) - 1, int(digits[-1]) - 1))
            return items[index]
        return items[0]

    def _is_decorative_text_id(self, element_id: str) -> bool:
        lowered = element_id.lower()
        return any(
            token in lowered
            for token in (
                "symbol",
                "watermark",
                "logo",
                "diamond",
                "progress",
                "dash",
                "divider",
                "deco",
            )
        )

    def _element_ids(self, text: str) -> list[str]:
        ids: list[str] = []
        for line in text.splitlines():
            stripped = line.strip().lstrip("- ").strip()
            if stripped.startswith("elementId:"):
                ids.append(stripped.split(":", 1)[1].strip())
        return ids

    def _element_type(self, text: str, *, element_id: str) -> str:
        lines = text.splitlines()
        marker = f"elementId: {element_id}"
        start = next((idx for idx, line in enumerate(lines) if line.strip().lstrip("- ") == marker), None)
        if start is None:
            return ""
        end = start + 1
        while end < len(lines):
            stripped = lines[end].strip().lstrip("- ").strip()
            if stripped.startswith("elementId:"):
                break
            if stripped.startswith("elementType:"):
                return stripped.split(":", 1)[1].strip()
            end += 1
        return ""

    def _resolve_template_name(
        self,
        *,
        skill_dir: Path,
        template_style: str,
        template_id: str | None,
    ) -> str:
        available = self._available_templates(skill_dir)
        requested = str(template_id or "").strip()
        if requested in available:
            return requested
        lowered = f"{template_style} {requested}".lower()
        candidates: list[str]
        if any(token in lowered for token in ("academic", "research", "thesis", "paper", "论文", "答辩", "学术")):
            candidates = ["academic-1", "academic-2", "education-3"]
        elif any(token in lowered for token in ("business", "insight", "finance", "market", "data", "商业", "市场", "金融")):
            candidates = ["business_insight-1", "business_insight-2", "strategic-1"]
        elif any(token in lowered for token in ("strategic", "strategy", "proposal", "roadmap", "战略", "方案")):
            candidates = ["strategic-1", "strategic-2"]
        elif any(token in lowered for token in ("work", "report", "summary", "汇报", "总结", "述职")):
            candidates = ["work_report-1", "work_report-2"]
        elif any(token in lowered for token in ("promotion", "brand", "marketing", "发布", "营销", "品牌")):
            candidates = ["promotion-1", "promotion-2", "general-3"]
        elif any(token in lowered for token in ("education", "course", "training", "teaching", "课程", "教学", "课件")):
            candidates = ["education-3", "education-1", "education-2"]
        else:
            candidates = ["education-3", "general-1", "education-1"]
        return next((item for item in candidates if item in available), self.template_name)

    def _available_templates(self, skill_dir: Path) -> set[str]:
        template_root = skill_dir / "guideline" / "design" / "template"
        if not template_root.is_dir():
            return set()
        return {
            item.name
            for item in template_root.iterdir()
            if item.is_dir() and (item / f"{item.name}.pptd").is_file()
        }

    def _available_page_names(self) -> set[str]:
        return set(getattr(self, "_current_page_names", set()))

    def _first_existing(self, candidates: list[str], available: set[str]) -> str | None:
        return next((item for item in candidates if item in available), None)

    def _yaml_plain(self, value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _apply_theme_overrides(self, lines: list[str], theme: dict[str, Any]) -> list[str]:
        replacements = {
            "primary": theme.get("primary"),
            "accent": theme.get("accent"),
            "background": theme.get("background"),
        }
        rendered = lines[:]
        in_theme_colors = False
        for idx, line in enumerate(rendered):
            stripped = line.strip()
            if stripped == "colors:":
                in_theme_colors = True
                continue
            if stripped.endswith(":") and not stripped.startswith("- ") and stripped != "colors:":
                indent = len(line) - len(line.lstrip(" "))
                if indent <= 2:
                    in_theme_colors = False
            if not in_theme_colors:
                continue
            key = stripped.split(":", 1)[0] if ":" in stripped else ""
            if key in replacements and replacements[key]:
                indent = line[: len(line) - len(line.lstrip(" "))]
                rendered[idx] = f'{indent}{key}: "{self._color(replacements[key])}"'
        return rendered

    def _color(self, value: Any) -> str:
        color = str(value or "").strip()
        if color.startswith("#"):
            return color
        lowered = color.lower()
        if len(lowered) in {3, 6} and all(char in "0123456789abcdef" for char in lowered):
            return f"#{color}"
        return color
