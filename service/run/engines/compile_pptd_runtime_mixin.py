from __future__ import annotations

import base64
import html
import json
from pathlib import Path
from typing import Any

from service.pptd_runtime import PptdRuntimeAdapter

from ..results import ScratchCompileResult


class CompilePptdRuntimeMixin:
    runtime: Any

    async def _compile_scratch_via_pptd(
        self,
        *,
        run_id: str,
        slides_dir: Path,
        slide_count: int,
        theme: dict[str, Any] | None = None,
    ) -> ScratchCompileResult:
        run = await self.runtime.store.get_run(run_id)
        if run is None:
            return self._pptd_compile_failure(
                slides_dir=slides_dir,
                reason="pptd_run_not_found",
                return_code=None,
            )
        pptd_dir = slides_dir / "pptd"
        pptd_path = pptd_dir / "presentation.pptd"
        pptx_path = slides_dir / "output" / "presentation.pptx"
        self._write_pptd_project(
            pptd_path=pptd_path,
            run=run,
            slide_count=slide_count,
            theme=theme or {},
        )
        adapter = PptdRuntimeAdapter(
            skill_dir=Path(str(getattr(self.runtime.settings, "pptd_skill_dir", "") or "")),
            runner_mode=str(
                getattr(self.runtime.settings, "pptd_runner_mode", "") or "docker"
            ),
            runner_image=str(
                getattr(self.runtime.settings, "pptd_runner_image", "")
                or "debian:bookworm-slim"
            ),
            platform=str(
                getattr(self.runtime.settings, "pptd_runner_platform", "")
                or "linux/amd64"
            ),
            timeout_sec=float(
                getattr(self.runtime.settings, "pptd_runner_timeout_sec", 120.0)
                or 120.0
            ),
            run_subprocess=self.runtime.subprocess.run,
        )
        check = adapter.check(pptd_path)
        if not check.ok:
            return self._pptd_compile_failure(
                slides_dir=slides_dir,
                reason=check.reason or "pptd_check_failed",
                return_code=check.return_code,
                details={"stdout": check.stdout, "stderr": check.stderr},
            )
        convert = adapter.convert(pptd_path, output_path=pptx_path)
        if not convert.ok:
            return self._pptd_compile_failure(
                slides_dir=slides_dir,
                reason=convert.reason or "pptd_convert_failed",
                return_code=convert.return_code,
                details={"stdout": convert.stdout, "stderr": convert.stderr},
            )
        return ScratchCompileResult(
            ok=True,
            compile_js_path=pptd_path,
            pptx_path=pptx_path,
            return_code=0,
            reason="",
            provider="pptd",
            bundle_ready=True,
            fallback_used=False,
            fallback_from=None,
            requested_provider="pptd",
        )

    def _pptd_compile_failure(
        self,
        *,
        slides_dir: Path,
        reason: str,
        return_code: int | None,
        details: dict[str, Any] | None = None,
    ) -> ScratchCompileResult:
        return ScratchCompileResult(
            ok=False,
            compile_js_path=slides_dir / "pptd" / "presentation.pptd",
            pptx_path=slides_dir / "output" / "presentation.pptx",
            return_code=return_code,
            reason=reason,
            provider="pptd",
            bundle_ready=False,
            fallback_used=False,
            fallback_from=None,
            requested_provider="pptd",
            error_details=details or {},
        )

    def _write_pptd_project(
        self,
        *,
        pptd_path: Path,
        run: Any,
        slide_count: int,
        theme: dict[str, Any],
    ) -> None:
        pages_dir = pptd_path.parent / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        nodes = list(getattr(getattr(run, "outline", None), "nodes", []) or [])
        total = max(1, slide_count, len(nodes))
        page_paths: list[str] = []
        for index in range(total):
            node = nodes[index] if index < len(nodes) else None
            page_name = f"slide-{index + 1:02d}.page"
            page_paths.append(f"pages/{page_name}")
            (pages_dir / page_name).write_text(
                self._pptd_page_yaml(index=index, total=total, node=node),
                encoding="utf-8",
            )
        pptd_path.write_text(
            self._pptd_deck_yaml(
                title=str(getattr(getattr(run, "input", None), "topic", "") or "Presentation"),
                page_paths=page_paths,
                theme=theme,
            ),
            encoding="utf-8",
        )

    def _pptd_deck_yaml(
        self, *, title: str, page_paths: list[str], theme: dict[str, Any]
    ) -> str:
        primary = str(theme.get("primary") or theme.get("accent") or "#2563eb")
        background = str(theme.get("background") or "#ffffff")
        text = str(theme.get("text") or "#111827")
        pages = "\n".join(f"  - {path}" for path in page_paths)
        return "\n".join(
            [
                f"title: {self._yaml_plain(title)}",
                "size: [1280, 720]",
                "theme:",
                "  colors:",
                f'    primary: "{primary}"',
                f'    background: "{background}"',
                f'    text: "{text}"',
                "  textStyles:",
                "    title:",
                "      fontSize: 46",
                '      color: "$primary"',
                '      fontFamily: "MiSans"',
                "    body:",
                "      fontSize: 24",
                '      color: "$text"',
                '      fontFamily: "MiSans"',
                "      lineHeight: 1.35",
                "pages:",
                pages,
                "",
            ]
        )

    def _pptd_page_yaml(self, *, index: int, total: int, node: Any) -> str:
        title = str(getattr(node, "title", "") or f"Slide {index + 1}")
        bullets = [str(item) for item in list(getattr(node, "bullets", []) or [])[:5]]
        body = "\n".join(f"• {item}" for item in bullets) or f"Page {index + 1} of {total}"
        body_lines = max(1, len(body.splitlines()))
        body_height = max(72, min(260, 42 * body_lines + 24))
        page_type = "cover" if index == 0 else "content"
        return "\n".join(
            [
                f"pageType: {page_type}",
                "background:",
                "  type: solid",
                '  color: "$background"',
                "elements:",
                "  - elementId: title",
                "    elementType: text",
                "    bounds: [96, 120, 1088, 92]",
                "    content:",
                '      style: "$title"',
                "      text: |",
                self._block_text(title, indent=8),
                "  - elementId: body",
                "    elementType: text",
                f"    bounds: [104, 260, 1064, {body_height}]",
                "    content:",
                '      style: "$body"',
                "      text: |",
                self._block_text(body, indent=8),
                "",
            ]
        )

    def _yaml_plain(self, value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _block_text(self, value: str, *, indent: int) -> str:
        prefix = " " * indent
        return "\n".join(f"{prefix}{line}" for line in value.splitlines() or [""])

    async def _build_pptd_compile_bundle(
        self,
        *,
        run: Any,
        slides_dir: Path,
        theme: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        pptd_path = slides_dir / "pptd" / "presentation.pptd"
        pptx_path = slides_dir / "output" / "presentation.pptx"
        slide_count = len(getattr(run, "slides", []) or [])
        if not pptd_path.is_file():
            self._write_pptd_project(
                pptd_path=pptd_path,
                run=run,
                slide_count=slide_count,
                theme=theme or {},
            )
        if not pptx_path.is_file():
            raise ValueError(f"pptd output artifact is missing: {pptx_path}")

        script_path = slides_dir / "compile_pptd_bundle.js"
        preview_seed_path = slides_dir / "preview_seed.json"
        input_pptx_path = slides_dir / "input" / "presentation.pptx"
        input_pptx_path.parent.mkdir(parents=True, exist_ok=True)
        input_pptx_path.write_bytes(pptx_path.read_bytes())
        script_path.write_text(self._pptd_bundle_script(), encoding="utf-8")
        preview_seed_path.write_text(
            json.dumps(
                self._pptd_preview_manifest_from_run(run=run, theme=theme or {}),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        files: list[dict[str, str]] = [
            self._bundle_file_entry(script_path, slides_dir=slides_dir),
            self._bundle_file_entry(preview_seed_path, slides_dir=slides_dir),
            self._bundle_file_entry(pptd_path, slides_dir=slides_dir),
        ]
        for page_path in sorted((slides_dir / "pptd" / "pages").glob("*.page")):
            files.append(self._bundle_file_entry(page_path, slides_dir=slides_dir))
        assets = [self._bundle_file_entry(input_pptx_path, slides_dir=slides_dir)]
        return {
            "provider": "diego",
            "provider_run_id": str(run.run_id),
            "provider_trace_id": str(run.trace_id),
            "mode": "scratch",
            "entrypoint": "slides/compile_pptd_bundle.js",
            "working_dir_manifest": {
                "dirs": ["slides", "slides/input", "slides/output", "slides/pptd"],
            },
            "files": files,
            "assets": assets,
            "compile_options": {
                "command": ["node", "compile_pptd_bundle.js"],
                "cwd": "slides",
                "output_artifacts": [
                    {
                        "kind": "pptx",
                        "path": "slides/output/presentation.pptx",
                        "media_type": (
                            "application/vnd.openxmlformats-officedocument."
                            "presentationml.presentation"
                        ),
                    }
                ],
                "preview_manifest_path": "slides/output/preview.json",
                "result_manifest_path": "slides/output/result.json",
            },
            "metadata": {
                "artifact_dir": str(run.artifact_dir),
                "theme_source": "diego",
                "compile_context": {
                    "model": "pptd",
                },
            },
        }

    def _bundle_file_entry(self, path: Path, *, slides_dir: Path) -> dict[str, str]:
        return {
            "path": f"slides/{path.relative_to(slides_dir).as_posix()}",
            "content_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
        }

    def _pptd_bundle_script(self) -> str:
        return "\n".join(
            [
                "const fs = require('fs');",
                "const path = require('path');",
                "fs.mkdirSync('output', { recursive: true });",
                "fs.copyFileSync(path.join('input', 'presentation.pptx'), path.join('output', 'presentation.pptx'));",
                "const preview = JSON.parse(fs.readFileSync('preview_seed.json', 'utf-8'));",
                "fs.writeFileSync(path.join('output', 'preview.json'), JSON.stringify(preview));",
                "fs.writeFileSync(path.join('output', 'result.json'), JSON.stringify({",
                "  schema_version: 'pagevra.result_manifest.v1',",
                "  primary_artifact_kind: 'pptx',",
                "  artifact_kinds: ['pptx'],",
                "  artifacts: [{",
                "    kind: 'pptx',",
                "    path: 'slides/output/presentation.pptx',",
                "    media_type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation'",
                "  }],",
                "  preview: { page_count: preview.pages.length },",
                "  metadata: { model: 'pptd' }",
                "}));",
                "",
            ]
        )

    def _pptd_preview_manifest_from_run(
        self, *, run: Any, theme: dict[str, Any]
    ) -> dict[str, Any]:
        nodes = list(getattr(getattr(run, "outline", None), "nodes", []) or [])
        total = max(1, len(nodes), len(getattr(run, "slides", []) or []))
        pages = []
        for index in range(total):
            node = nodes[index] if index < len(nodes) else None
            title = str(getattr(node, "title", "") or f"Slide {index + 1}")
            bullets = [str(item) for item in list(getattr(node, "bullets", []) or [])[:5]]
            pages.append(
                {
                    "index": index,
                    "slide_id": f"slide-{index + 1:02d}",
                    "format": "svg",
                    "svg_data_url": self._pptd_preview_svg_data_url(
                        title=title,
                        bullets=bullets,
                        page_no=index + 1,
                        total=total,
                        theme=theme,
                    ),
                    "width": 1280,
                    "height": 720,
                }
            )
        return {
            "schema_version": "pagevra.preview_manifest.v1",
            "page_count": len(pages),
            "pages": pages,
        }

    def _pptd_preview_svg_data_url(
        self,
        *,
        title: str,
        bullets: list[str],
        page_no: int,
        total: int,
        theme: dict[str, Any],
    ) -> str:
        primary = html.escape(str(theme.get("primary") or theme.get("accent") or "#2563eb"))
        background = html.escape(str(theme.get("background") or theme.get("bg") or "#ffffff"))
        text_color = html.escape(str(theme.get("text") or "#111827"))
        title_xml = html.escape(title)
        bullet_lines = "\n".join(
            f'<text x="112" y="{304 + idx * 46}" font-size="26" fill="{text_color}">• {html.escape(item)}</text>'
            for idx, item in enumerate(bullets or [f"Page {page_no} of {total}"])
        )
        svg = "\n".join(
            [
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">',
                f'<rect width="1280" height="720" fill="{background}"/>',
                f'<rect x="0" y="0" width="1280" height="14" fill="{primary}"/>',
                f'<text x="96" y="188" font-size="54" font-family="Arial, sans-serif" font-weight="700" fill="{primary}">{title_xml}</text>',
                bullet_lines,
                f'<text x="112" y="650" font-size="20" fill="{text_color}" opacity="0.55">{page_no:02d} / {total:02d}</text>',
                "</svg>",
            ]
        )
        encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        return f"data:image/svg+xml;base64,{encoded}"
