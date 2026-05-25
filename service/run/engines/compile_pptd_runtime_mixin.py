from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from service.pptd_runtime import PptdRuntimeAdapter

from .pptd_layout import PptdDeckWriter
from .pptd_warning_repair import (
    repair_pptd_warning_layout,
    restore_pptd_warning_repair_backup,
)
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
        repair_details: dict[str, Any] | None = None
        if check.reason == "pptd_check_warnings":
            repaired = repair_pptd_warning_layout(
                pptd_path=pptd_path,
                checker_output=f"{check.stdout}\n{check.stderr}",
            )
            if repaired:
                first_check = check
                check = adapter.check(pptd_path)
                restored = False
                if (
                    first_check.warning_count is not None
                    and check.warning_count is not None
                    and check.warning_count > first_check.warning_count
                ):
                    restored = restore_pptd_warning_repair_backup(pptd_path=pptd_path)
                    if restored:
                        check = first_check
                repair_details = {
                    "attempted": True,
                    "changed": True,
                    "restored": restored,
                    "initial_stdout": first_check.stdout,
                    "initial_stderr": first_check.stderr,
                    "initial_error_count": first_check.error_count,
                    "initial_warning_count": first_check.warning_count,
                    "final_error_count": check.error_count,
                    "final_warning_count": check.warning_count,
                }
            else:
                repair_details = {
                    "attempted": True,
                    "changed": False,
                }
        if not check.ok:
            return self._pptd_compile_failure(
                slides_dir=slides_dir,
                reason=check.reason or "pptd_check_failed",
                return_code=check.return_code,
                details={
                    "stdout": check.stdout,
                    "stderr": check.stderr,
                    "error_count": check.error_count,
                    "warning_count": check.warning_count,
                    "repair": repair_details,
                },
            )
        convert = adapter.convert(pptd_path, output_path=pptx_path)
        if not convert.ok:
            return self._pptd_compile_failure(
                slides_dir=slides_dir,
                reason=convert.reason or "pptd_convert_failed",
                return_code=convert.return_code,
                details={"stdout": convert.stdout, "stderr": convert.stderr},
            )
        screenshot_details = self._render_pptd_screenshots(
            slides_dir=slides_dir,
            pptx_path=pptx_path,
            adapter=adapter,
        )
        self._write_pptd_compile_provenance(
            slides_dir=slides_dir,
            pptd_path=pptd_path,
            pptx_path=pptx_path,
            check=check,
            repair_details=repair_details,
            screenshot_details=screenshot_details,
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
            error_details={"repair": repair_details} if repair_details else None,
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
        run_input = getattr(run, "input", None)
        nodes = list(getattr(getattr(run, "outline", None), "nodes", []) or [])
        writer = PptdDeckWriter()
        source_notes = writer.source_notes_for_run(run=run, slide_count=slide_count)
        writer.write_project(
            pptd_path=pptd_path,
            title=str(getattr(run_input, "topic", "") or "Presentation"),
            nodes=nodes,
            slide_count=slide_count,
            theme=theme,
            skill_dir=Path(str(getattr(self.runtime.settings, "pptd_skill_dir", "") or "")),
            template_style=str(getattr(run_input, "template_style", "") or ""),
            template_id=str(getattr(run_input, "template_id", "") or "") or None,
            source_notes=source_notes,
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
        provenance = self._pptd_compile_provenance(slides_dir=slides_dir)
        preview_seed_path.write_text(
            json.dumps(
                self._pptd_preview_manifest_from_run(
                    run=run,
                    theme=theme or {},
                    provenance=provenance,
                ),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        files: list[dict[str, str]] = [
            self._bundle_file_entry(script_path, slides_dir=slides_dir),
            self._bundle_file_entry(preview_seed_path, slides_dir=slides_dir),
            self._bundle_file_entry(pptd_path, slides_dir=slides_dir),
        ]
        for planning_doc in ("design.md", "outline.md"):
            doc_path = slides_dir / "pptd" / planning_doc
            if doc_path.is_file():
                files.append(self._bundle_file_entry(doc_path, slides_dir=slides_dir))
        provenance_path = slides_dir / "pptd" / "compile_provenance.json"
        if provenance_path.is_file():
            files.append(self._bundle_file_entry(provenance_path, slides_dir=slides_dir))
        for page_path in sorted((slides_dir / "pptd" / "pages").glob("*.page")):
            files.append(self._bundle_file_entry(page_path, slides_dir=slides_dir))
        assets = [self._bundle_file_entry(input_pptx_path, slides_dir=slides_dir)]
        for screenshot_path in sorted((slides_dir / "output" / "screenshots").glob("*.png")):
            assets.append(self._bundle_file_entry(screenshot_path, slides_dir=slides_dir))
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
                "  metadata: { model: 'pptd', preview_truth: preview.metadata && preview.metadata.preview_truth || null }",
                "}));",
                "",
            ]
        )

    def _pptd_preview_manifest_from_run(
        self,
        *,
        run: Any,
        theme: dict[str, Any],
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        screenshot_manifest = self._pptd_screenshot_preview_manifest(
            run=run,
            provenance=provenance,
        )
        if screenshot_manifest:
            self._attach_preview_truth_metadata(
                manifest=screenshot_manifest,
                provenance=provenance,
            )
            return screenshot_manifest
        pptd_path = Path(str(getattr(run, "artifact_dir", "") or "")) / "slides" / "pptd" / "presentation.pptd"
        if pptd_path.is_file():
            manifest = PptdDeckWriter().preview_manifest_from_project(pptd_path=pptd_path)
            if manifest.get("pages"):
                self._attach_preview_truth_metadata(
                    manifest=manifest,
                    provenance=provenance,
                )
                return manifest
        nodes = list(getattr(getattr(run, "outline", None), "nodes", []) or [])
        manifest = PptdDeckWriter().preview_manifest(
            nodes=nodes,
            slide_count=len(getattr(run, "slides", []) or []),
            theme=theme,
            source_notes=PptdDeckWriter().source_notes_for_run(
                run=run,
                slide_count=len(getattr(run, "slides", []) or []),
            ),
        )
        self._attach_preview_truth_metadata(manifest=manifest, provenance=provenance)
        return manifest

    def _pptd_screenshot_preview_manifest(
        self,
        *,
        run: Any,
        provenance: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        screenshot = provenance.get("screenshot") if isinstance(provenance, dict) else None
        if not isinstance(screenshot, dict) or screenshot.get("status") != "completed":
            return None
        files = screenshot.get("files")
        if not isinstance(files, list):
            return None
        artifact_dir = Path(str(getattr(run, "artifact_dir", "") or ""))
        pages: list[dict[str, Any]] = []
        for index, item in enumerate(files):
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                continue
            rel_path = str(item["path"])
            if not rel_path.startswith("slides/output/screenshots/") or ".." in Path(rel_path).parts:
                continue
            image_path = artifact_dir / rel_path
            if not image_path.is_file():
                continue
            width, height = self._png_dimensions(image_path)
            pages.append(
                {
                    "index": index,
                    "slide_id": f"slide-{index + 1:02d}",
                    "format": "png",
                    "data_url": (
                        "data:image/png;base64,"
                        + base64.b64encode(image_path.read_bytes()).decode("ascii")
                    ),
                    "artifact_path": rel_path,
                    "width": width,
                    "height": height,
                    "status": "rendered_from_pptx",
                }
            )
        if not pages:
            return None
        return {
            "schema_version": "pagevra.preview_manifest.v1",
            "page_count": len(pages),
            "pages": pages,
            "source": "converted_pptx_screenshot",
        }

    def _write_pptd_compile_provenance(
        self,
        *,
        slides_dir: Path,
        pptd_path: Path,
        pptx_path: Path,
        check: Any,
        repair_details: dict[str, Any] | None,
        screenshot_details: dict[str, Any],
    ) -> None:
        provenance = {
            "schema_version": "diego.pptd_compile_provenance.v1",
            "truth_owner": "Diego",
            "preview_source": "checked_pptd_project",
            "export_source": "converted_pptx",
            "pptd_path": "slides/pptd/presentation.pptd",
            "pptx_path": "slides/output/presentation.pptx",
            "pptd_sha256": self._sha256(pptd_path),
            "pptx_sha256": self._sha256(pptx_path),
            "check": {
                "error_count": check.error_count,
                "warning_count": check.warning_count,
                "return_code": check.return_code,
            },
            "warning_repair": repair_details,
            "screenshot": screenshot_details,
        }
        path = slides_dir / "pptd" / "compile_provenance.json"
        path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")

    def _render_pptd_screenshots(
        self,
        *,
        slides_dir: Path,
        pptx_path: Path,
        adapter: PptdRuntimeAdapter,
    ) -> dict[str, Any]:
        if not bool(getattr(self.runtime.settings, "pptd_screenshot_enabled", False)):
            return {"enabled": False}
        output_dir = slides_dir / "output" / "screenshots"
        result = adapter.screenshot(
            pptx_path,
            output_dir=output_dir,
            pages="all",
            dpi=int(getattr(self.runtime.settings, "pptd_screenshot_dpi", 150) or 150),
        )
        if not result.ok:
            return {
                "enabled": True,
                "status": "failed",
                "reason": result.reason or "pptd_screenshot_failed",
                "return_code": result.return_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "output_dir": "slides/output/screenshots",
            }
        files = []
        for path in sorted(output_dir.glob("*.png")):
            files.append(
                {
                    "path": f"slides/{path.relative_to(slides_dir).as_posix()}",
                    "sha256": self._sha256(path),
                    "bytes": path.stat().st_size,
                }
            )
        return {
            "enabled": True,
            "status": "completed",
            "source": "converted_pptx",
            "return_code": result.return_code,
            "output_dir": "slides/output/screenshots",
            "files": files,
        }

    def _pptd_compile_provenance(self, *, slides_dir: Path) -> dict[str, Any] | None:
        path = slides_dir / "pptd" / "compile_provenance.json"
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    def _attach_preview_truth_metadata(
        self,
        *,
        manifest: dict[str, Any],
        provenance: dict[str, Any] | None,
    ) -> None:
        if not provenance:
            return
        metadata = manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {}
        metadata["preview_truth"] = {
            "truth_owner": provenance.get("truth_owner"),
            "preview_source": provenance.get("preview_source"),
            "export_source": provenance.get("export_source"),
            "pptd_sha256": provenance.get("pptd_sha256"),
            "pptx_sha256": provenance.get("pptx_sha256"),
            "check": provenance.get("check"),
            "warning_repair": provenance.get("warning_repair"),
            "screenshot": provenance.get("screenshot"),
        }
        manifest["metadata"] = metadata

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _png_dimensions(self, path: Path) -> tuple[int | None, int | None]:
        with path.open("rb") as handle:
            header = handle.read(24)
        if len(header) >= 24 and header.startswith(b"\x89PNG\r\n\x1a\n"):
            return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")
        return None, None
