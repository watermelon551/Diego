from __future__ import annotations

from pathlib import Path
from typing import Any

from .pptd_contracts import PptdSlideContent
from .pptd_page_yaml import PptdPageYamlRenderer
from .pptd_preview import PptdPreviewRenderer, PptdProjectPreviewRenderer
from .pptd_skill_template import PptdSkillTemplateDeck
from .pptd_source_notes import pptd_source_notes_from_report


class PptdDeckWriter:
    def write_project(
        self,
        *,
        pptd_path: Path,
        title: str,
        nodes: list[Any],
        slide_count: int,
        theme: dict[str, Any],
        skill_dir: Path | None = None,
        template_style: str = "",
        template_id: str | None = None,
        source_notes: list[str] | None = None,
        requirements_report: dict[str, Any] | None = None,
    ) -> None:
        self._write_planning_docs(
            pptd_dir=pptd_path.parent,
            title=title,
            nodes=nodes,
            slide_count=slide_count,
            theme=theme,
            template_style=template_style,
            template_id=template_id,
            requirements_report=requirements_report,
        )
        if skill_dir and PptdSkillTemplateDeck().write_project(
            pptd_path=pptd_path,
            title=title,
            nodes=nodes,
            slide_count=slide_count,
            theme=theme,
            skill_dir=skill_dir,
            template_style=template_style,
            template_id=template_id,
            source_notes=source_notes,
        ):
            return
        pages_dir = pptd_path.parent / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        total = max(1, slide_count, len(nodes))
        page_paths: list[str] = []
        renderer = PptdPageYamlRenderer()
        for index in range(total):
            slide = self._slide_content(
                index=index,
                total=total,
                nodes=nodes,
                source_notes=source_notes,
            )
            page_name = f"slide-{index + 1:02d}.page"
            page_paths.append(f"pages/{page_name}")
            (pages_dir / page_name).write_text(
                renderer.page_yaml(slide=slide),
                encoding="utf-8",
            )
        pptd_path.write_text(
            self.deck_yaml(title=title, page_paths=page_paths, theme=theme),
            encoding="utf-8",
        )

    def preview_manifest(
        self,
        *,
        nodes: list[Any],
        slide_count: int,
        theme: dict[str, Any],
        source_notes: list[str] | None = None,
    ) -> dict[str, Any]:
        total = max(1, slide_count, len(nodes))
        renderer = PptdPreviewRenderer()
        pages = [
            {
                "index": index,
                "slide_id": f"slide-{index + 1:02d}",
                "format": "svg",
                "svg_data_url": renderer.svg_data_url(
                    slide=self._slide_content(
                        index=index,
                        total=total,
                        nodes=nodes,
                        source_notes=source_notes,
                    ),
                    theme=theme,
                ),
                "width": 1280,
                "height": 720,
            }
            for index in range(total)
        ]
        return {
            "schema_version": "pagevra.preview_manifest.v1",
            "page_count": len(pages),
            "pages": pages,
        }

    def preview_manifest_from_project(self, *, pptd_path: Path) -> dict[str, Any]:
        return PptdProjectPreviewRenderer().preview_manifest(pptd_path=pptd_path)

    def deck_yaml(
        self, *, title: str, page_paths: list[str], theme: dict[str, Any]
    ) -> str:
        primary = self._color(theme.get("primary") or theme.get("accent"), "#2563eb")
        background = self._color(theme.get("background"), "#ffffff")
        text = self._color(theme.get("text"), "#111827")
        accent = self._color(theme.get("accent"), "#16a34a")
        muted = self._color(theme.get("muted"), "#64748b")
        pages = "\n".join(f"  - {path}" for path in page_paths)
        return "\n".join(
            [
                f"title: {self._yaml_plain(title)}",
                "size: [1280, 720]",
                "theme:",
                "  colors:",
                f'    primary: "{primary}"',
                f'    accent: "{accent}"',
                f'    background: "{background}"',
                f'    surface: "{self._color(theme.get("surface"), "#f8fafc")}"',
                f'    card: "{self._color(theme.get("card"), "#ffffff")}"',
                f'    muted: "{muted}"',
                f'    text: "{text}"',
                '    textWhite: "#ffffff"',
                "  textStyles:",
                "    title:",
                "      fontSize: 42",
                '      color: "$text"',
                '      fontFamily: "Liter, MiSans"',
                "      lineHeight: 1.12",
                "    sectionLabel:",
                "      fontSize: 16",
                '      color: "$muted"',
                '      fontFamily: "Liter, MiSans"',
                "    body:",
                "      fontSize: 21",
                '      color: "$text"',
                '      fontFamily: "Liter, MiSans"',
                "      lineHeight: 1.35",
                "pages:",
                pages,
                "",
            ]
        )

    def source_notes_for_run(self, *, run: Any, slide_count: int) -> list[str]:
        report = (
            getattr(run, "research_report", {})
            if isinstance(getattr(run, "research_report", {}), dict)
            else {}
        )
        return pptd_source_notes_from_report(report, slide_count=slide_count)

    def _slide_content(
        self,
        *,
        index: int,
        total: int,
        nodes: list[Any],
        source_notes: list[str] | None = None,
    ) -> PptdSlideContent:
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
            source_note=(
                source_notes[index]
                if source_notes is not None and index < len(source_notes)
                else ""
            ),
        )

    def _write_planning_docs(
        self,
        *,
        pptd_dir: Path,
        title: str,
        nodes: list[Any],
        slide_count: int,
        theme: dict[str, Any],
        template_style: str = "",
        template_id: str | None = None,
        requirements_report: dict[str, Any] | None = None,
    ) -> None:
        pptd_dir.mkdir(parents=True, exist_ok=True)
        total = max(1, slide_count, len(nodes))
        (pptd_dir / "design.md").write_text(
            self._design_doc(
                title=title,
                theme=theme,
                template_style=template_style,
                template_id=template_id,
                requirements_report=requirements_report,
            ),
            encoding="utf-8",
        )
        (pptd_dir / "outline.md").write_text(
            self._outline_doc(title=title, nodes=nodes, slide_count=total),
            encoding="utf-8",
        )

    def _design_doc(
        self,
        *,
        title: str,
        theme: dict[str, Any],
        template_style: str = "",
        template_id: str | None = None,
        requirements_report: dict[str, Any] | None = None,
    ) -> str:
        primary = self._color(theme.get("primary") or theme.get("accent"), "#2563eb")
        background = self._color(theme.get("background"), "#ffffff")
        text = self._color(theme.get("text"), "#111827")
        accent = self._color(theme.get("accent"), "#16a34a")
        report = requirements_report if isinstance(requirements_report, dict) else {}
        profile = self._report_value(report, "scenario_profile") or self._profile_baseline(
            template_style=template_style
        )
        visual_mode = self._report_value(report, "visual_mode") or "creative"
        content_mode = self._report_value(report, "content_mode") or "outline"
        density_guidance = self._report_value(report, "density_guidance") or (
            "projection-readable medium density; use zoning before shrinking text."
        )
        font_guidance = self._report_value(report, "font_guidance") or (
            "body text should remain 18px or above unless the template explicitly requires otherwise."
        )
        risk_prohibitions = self._report_list(report, "risk_prohibitions")
        design_intent = (
            report.get("design_intent")
            if isinstance(report.get("design_intent"), dict)
            else {}
        )
        template_note = str(template_id or template_style or "auto").strip()
        lines = [
            f"# Design Plan: {title}",
            "",
            "## Profile Baseline Declaration",
            f"- Profile selection: `profiles/{profile}.md`.",
            "- Referenced dimensions: audience density, font-size floor, visual-as-comprehension-tool policy, layout rhythm, and risk prohibitions from the PPTD skill profile.",
            f"- Template/style request: `{template_note}`.",
            "- Deviation notes: NeoSpectra keeps Shell/Workbench UI stable; Diego only materializes PPTD project artifacts and does not expose source/vendor branding.",
            "",
            "## Visual Mode",
            f"- Visual mode: `{visual_mode}`.",
            f"- Content mode: `{content_mode}`.",
            "- Creative mode applies when no explicit reference/template is attached; preset-template mode applies when a neutral PPTD template is selected.",
            "",
            "## Skill Planning Contract",
            f"- Density guidance: {density_guidance}",
            f"- Font guidance: {font_guidance}",
            "- Visual strategy: "
            + (
                self._design_intent_value(design_intent, "visual_strategy")
                or "use diagrams, comparisons, tables, or process blocks as comprehension aids."
            ),
            "- Layout family: "
            + (
                self._design_intent_value(design_intent, "layout_family")
                or "template-led content pages with consistent common elements."
            ),
            "- Style recipe: "
            + (
                self._design_intent_value(design_intent, "style_recipe")
                or "neutral PPTD-first courseware style."
            ),
            "",
            "## Risk Prohibitions",
        ]
        if risk_prohibitions:
            lines.extend(f"- {item}" for item in risk_prohibitions)
        else:
            lines.extend(
                [
                    "- Keep body text readable and avoid overflow-prone dense paragraphs.",
                    "- Preserve consistent margins, slide numbers, and common page elements.",
                    "- Avoid default decorative gradients and empty placeholder graphics.",
                    "- Treat PPTD checker warnings as visual defects unless explicitly intended.",
                    "- Keep evidence/source notes visible when provided.",
                ]
            )
        lines.extend(
            [
                "",
                "## Style Direction",
                "- PPTD-first deck generated from a durable outline before page authoring.",
                "- Use the external PPTD skill's profile-first approach: choose the scenario profile, then select template/layout rhythm.",
                "- Titles should carry the knowledge point or conclusion, not only a chapter label.",
                "- Use diagrams, timelines, comparisons, metric tables, or summary blocks before decorative filler.",
                "- Body text should remain projection-readable; dense pages should use zoning instead of shrinking text below the profile floor.",
                "",
                "## Theme",
                "```yaml",
                "theme:",
                "  colors:",
                f'    primary: "{primary}"',
                f'    accent: "{accent}"',
                f'    background: "{background}"',
                f'    text: "{text}"',
                "  textStyles:",
                "    title:",
                "      fontSize: 42",
                '      fontFamily: "Liter, MiSans"',
                "    body:",
                "      fontSize: 21",
                '      fontFamily: "Liter, MiSans"',
                "      lineHeight: 1.35",
                "```",
                "",
                "## Quality Guardrails",
                "- Follow the Skill Planning Contract above before selecting page layouts.",
                "- Use the checker summary as the final source of truth for layout safety.",
                "- If a page fails because content is too dense, condense or split content before reducing font size.",
                "- Keep evidence/source notes visible when provided.",
                "",
            ]
        )
        return "\n".join(lines)

    def _profile_baseline(self, *, template_style: str) -> str:
        lowered = str(template_style or "").lower()
        if any(token in lowered for token in ("education", "course", "training", "teaching", "课程", "教学", "课件")):
            return "education"
        if any(token in lowered for token in ("academic", "research", "thesis", "paper", "论文", "答辩", "学术")):
            return "academic"
        if any(token in lowered for token in ("business", "finance", "market", "strategy", "商业", "金融", "战略")):
            return "business_insight"
        return "general"

    def _outline_doc(self, *, title: str, nodes: list[Any], slide_count: int) -> str:
        lines = ["# Presentation Outline", "", f"## Deck", f"- **Title**: {title}", ""]
        for index in range(slide_count):
            node = nodes[index] if index < len(nodes) else None
            slide_title = str(getattr(node, "title", "") or f"Slide {index + 1}")
            page_type = str(
                getattr(getattr(node, "page_type", ""), "value", "")
                or getattr(node, "page_type", "")
                or "content"
            )
            bullets = [
                str(item)
                for item in list(getattr(node, "bullets", []) or [])
                if str(item).strip()
            ]
            lines.extend(
                [
                    f"## Page {index + 1} [{page_type}]",
                    f"- **Title**: {slide_title}",
                    "- **Content**:",
                ]
            )
            if bullets:
                lines.extend(f"  - {item}" for item in bullets)
            else:
                lines.append("  - ")
            lines.append("")
        return "\n".join(lines)

    def _report_value(self, report: dict[str, Any], key: str) -> str:
        value = report.get(key)
        if isinstance(value, str):
            return " ".join(value.split())
        return ""

    def _report_list(self, report: dict[str, Any], key: str) -> list[str]:
        value = report.get(key)
        if not isinstance(value, list):
            return []
        return [" ".join(str(item).split()) for item in value if str(item).strip()]

    def _design_intent_value(self, design_intent: dict[Any, Any], key: str) -> str:
        value = design_intent.get(key)
        if isinstance(value, str):
            return " ".join(value.split())
        return ""

    def _yaml_plain(self, value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _color(self, value: Any, fallback: str) -> str:
        color = str(value or "").strip() or fallback
        if color.startswith("#"):
            return color
        lowered = color.lower()
        if len(lowered) in {3, 6} and all(char in "0123456789abcdef" for char in lowered):
            return f"#{color}"
        return fallback
