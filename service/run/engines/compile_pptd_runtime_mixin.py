from __future__ import annotations

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
