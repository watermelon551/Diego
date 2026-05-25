from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from .pptd_contracts import PptdSlideContent


class PptdSkillTemplateDeck:
    template_name = "education-1"

    def write_project(
        self,
        *,
        pptd_path: Path,
        title: str,
        nodes: list[Any],
        slide_count: int,
        theme: dict[str, Any],
        skill_dir: Path,
    ) -> bool:
        template_dir = skill_dir / "guideline" / "design" / "template" / self.template_name
        deck_template = template_dir / f"{self.template_name}.pptd"
        pages_dir = template_dir / "pages"
        if not deck_template.is_file() or not pages_dir.is_dir():
            return False

        target_pages_dir = pptd_path.parent / "pages"
        target_pages_dir.mkdir(parents=True, exist_ok=True)
        total = max(1, slide_count, len(nodes))
        page_paths: list[str] = []
        for index in range(total):
            slide = self._slide_content(index=index, total=total, nodes=nodes)
            template_page = pages_dir / self._template_page_name(index=index, total=total)
            if not template_page.is_file():
                return False
            page_name = f"slide-{index + 1:02d}.page"
            page_paths.append(f"pages/{page_name}")
            (target_pages_dir / page_name).write_text(
                self._render_page(template_page.read_text(encoding="utf-8"), slide=slide),
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
        kind = self._template_page_name(index=slide.index, total=slide.total)
        if kind == "cover.page":
            return self._render_cover(text, slide)
        if kind == "toc.page":
            return self._render_toc(text, slide)
        if kind == "process.page":
            return self._render_process(text, slide)
        if kind == "framework.page":
            return self._render_framework(text, slide)
        if kind == "final.page":
            return self._render_final(text, slide)
        return self._render_concept(text, slide)

    def _render_cover(self, text: str, slide: PptdSlideContent) -> str:
        subtitle = self._plain(slide.bullets[0] if slide.bullets else "课程核心概念与实践路径")
        highlight = self._plain(slide.bullets[1] if len(slide.bullets) > 1 else "结构化路径 · 启发式引导")
        replacements = {
            "main-title": self._p(slide.title),
            "subtitle": self._p(subtitle),
            "highlight-text": self._p(highlight),
            "footer-info": self._p("NeoSpectra · PPTD Courseware"),
        }
        return self._replace_many(text, replacements)

    def _render_toc(self, text: str, slide: PptdSlideContent) -> str:
        items = self._display_items(slide, count=4)
        replacements = {"page-title": self._p("学习路径导航")}
        for idx in range(1, 5):
            item = items[idx - 1] if idx <= len(items) else f"模块 {idx}"
            replacements[f"module{idx}-title"] = self._p(f"<strong>{self._plain(item)}</strong>", escaped=False)
            replacements[f"module{idx}-desc"] = self._p("围绕本模块建立关键概念、触发条件与应用判断。")
        return self._replace_many(text, replacements)

    def _render_concept(self, text: str, slide: PptdSlideContent) -> str:
        items = self._display_items(slide, count=4)
        replacements = {
            "page-title": self._p(slide.title),
            "content-text": self._rich_content(slide),
            "center-text": self._p("<strong>核心概念</strong>", escaped=False),
            "memory-text": self._p(f"<strong>关键洞察：</strong>{self._plain(items[0])}", escaped=False),
        }
        for idx, item in enumerate(items[:4], start=1):
            replacements[f"node{idx}-text"] = self._p(self._short_label(item, max_len=8))
        return self._replace_many(text, replacements)

    def _render_process(self, text: str, slide: PptdSlideContent) -> str:
        items = self._display_items(slide, count=4)
        replacements = {"page-title": self._p(slide.title), "diagram-title": self._p("<strong>机制流程</strong>", escaped=False)}
        for idx, item in enumerate(items[:4], start=1):
            head, desc = self._split_item(item)
            replacements[f"step{idx}-title"] = self._p(f"<strong>{self._plain(head)}</strong>", escaped=False)
            replacements[f"step{idx}-desc"] = self._p(desc)
        cycle = ["输入", "判断", "调整", "反馈"]
        for element_id, value in zip(("input-text", "process-text", "output-text", "reflect-text"), cycle):
            replacements[element_id] = self._p(f"<strong>{value}</strong>", escaped=False)
        return self._replace_many(text, replacements)

    def _render_framework(self, text: str, slide: PptdSlideContent) -> str:
        items = self._display_items(slide, count=5)
        replacements = {"page-title": self._p(slide.title), "center-text": self._p("<strong>框架</strong>", escaped=False)}
        for key, item in zip(("node-l-text", "node-e-text", "node-a-text", "node-r-text", "node-n-text"), items):
            replacements[key] = self._p(f"<strong>{self._short_label(item, max_len=10)}</strong>", escaped=False)
        return self._replace_many(text, replacements)

    def _render_final(self, text: str, slide: PptdSlideContent) -> str:
        items = self._display_items(slide, count=4)
        replacements = {
            "thank-you": self._p(slide.title),
            "subtitle": self._p("复盘、迁移、应用"),
            "action-text": "\n".join(self._p(f"• {item}") for item in items[:4]),
            "footer": self._p("NeoSpectra · Generated Courseware"),
        }
        return self._replace_many(text, replacements)

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

    def _template_page_name(self, *, index: int, total: int) -> str:
        if index == 0:
            return "cover.page"
        if index == total - 1:
            return "final.page"
        if index == 1 and total >= 5:
            return "toc.page"
        return ["concept.page", "process.page", "framework.page"][(index - 1) % 3]

    def _slide_content(self, *, index: int, total: int, nodes: list[Any]) -> PptdSlideContent:
        node = nodes[index] if index < len(nodes) else None
        title = str(getattr(node, "title", "") or f"Slide {index + 1}")
        bullets = [str(item) for item in list(getattr(node, "bullets", []) or [])[:6]]
        return PptdSlideContent(index=index, total=total, title=title, bullets=bullets)

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

    def _short_label(self, value: str, *, max_len: int) -> str:
        plain = self._plain(value)
        return plain if len(plain) <= max_len else f"{plain[:max_len - 1]}…"

    def _plain(self, value: str) -> str:
        return html.escape(str(value).strip(), quote=False)

    def _p(self, value: str, *, escaped: bool = True) -> str:
        body = self._plain(value) if escaped else value
        return f"<p>{body}</p>"

    def _yaml_plain(self, value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _apply_theme_overrides(self, lines: list[str], theme: dict[str, Any]) -> list[str]:
        replacements = {
            "primary": theme.get("primary"),
            "accent": theme.get("accent"),
            "background": theme.get("background"),
        }
        rendered = lines[:]
        for idx, line in enumerate(rendered):
            stripped = line.strip()
            key = stripped.split(":", 1)[0] if ":" in stripped else ""
            if key in replacements and replacements[key]:
                rendered[idx] = f'    {key}: "{self._color(replacements[key])}"'
        return rendered

    def _color(self, value: Any) -> str:
        color = str(value or "").strip()
        if color.startswith("#"):
            return color
        lowered = color.lower()
        if len(lowered) in {3, 6} and all(char in "0123456789abcdef" for char in lowered):
            return f"#{color}"
        return color
