from __future__ import annotations

from pathlib import Path
from typing import Any

from .pptd_contracts import PptdSlideContent
from .pptd_page_yaml import PptdPageYamlRenderer
from .pptd_preview import PptdPreviewRenderer, PptdProjectPreviewRenderer
from .pptd_skill_template import PptdSkillTemplateDeck


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
    ) -> None:
        if skill_dir and PptdSkillTemplateDeck().write_project(
            pptd_path=pptd_path,
            title=title,
            nodes=nodes,
            slide_count=slide_count,
            theme=theme,
            skill_dir=skill_dir,
        ):
            return
        pages_dir = pptd_path.parent / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        total = max(1, slide_count, len(nodes))
        page_paths: list[str] = []
        renderer = PptdPageYamlRenderer()
        for index in range(total):
            slide = self._slide_content(index=index, total=total, nodes=nodes)
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
    ) -> dict[str, Any]:
        total = max(1, slide_count, len(nodes))
        renderer = PptdPreviewRenderer()
        pages = [
            {
                "index": index,
                "slide_id": f"slide-{index + 1:02d}",
                "format": "svg",
                "svg_data_url": renderer.svg_data_url(
                    slide=self._slide_content(index=index, total=total, nodes=nodes),
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

    def _slide_content(self, *, index: int, total: int, nodes: list[Any]) -> PptdSlideContent:
        node = nodes[index] if index < len(nodes) else None
        title = str(getattr(node, "title", "") or f"Slide {index + 1}")
        bullets = [str(item) for item in list(getattr(node, "bullets", []) or [])[:6]]
        return PptdSlideContent(index=index, total=total, title=title, bullets=bullets)

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
