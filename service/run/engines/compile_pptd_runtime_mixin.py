from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from service.pptd_runtime import PptdRuntimeAdapter

from .pptd_layout import PptdDeckWriter
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
        nodes = list(getattr(getattr(run, "outline", None), "nodes", []) or [])
        PptdDeckWriter().write_project(
            pptd_path=pptd_path,
            title=str(getattr(getattr(run, "input", None), "topic", "") or "Presentation"),
            nodes=nodes,
            slide_count=slide_count,
            theme=theme,
        )

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
        return PptdDeckWriter().preview_manifest(
            nodes=nodes,
            slide_count=len(getattr(run, "slides", []) or []),
            theme=theme,
        )
