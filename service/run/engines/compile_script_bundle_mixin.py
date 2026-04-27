from __future__ import annotations

import base64
from pathlib import Path
from typing import Any


class CompileScriptBundleMixin:
    runtime: Any

    def _ensure_compile_script(
        self,
        *,
        slides_dir: Path,
        slide_count: int,
        theme: dict[str, Any],
    ) -> Path:
        compile_js = slides_dir / "compile.js"
        compile_js.write_text(
            self.runtime._build_compile_script(total=slide_count, theme=theme),
            encoding="utf-8",
        )
        return compile_js

    async def _build_scratch_compile_bundle(
        self, *, run: Any, slides_dir: Path, theme: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        files: list[dict[str, str]] = []
        assets: list[dict[str, str]] = []
        for file_path in sorted(slides_dir.rglob("*")):
            if not file_path.is_file():
                continue
            rel_path = file_path.relative_to(slides_dir).as_posix()
            if rel_path.startswith("output/"):
                continue
            entry = {
                "path": f"slides/{rel_path}",
                "content_base64": base64.b64encode(file_path.read_bytes()).decode(
                    "ascii"
                ),
            }
            if file_path.suffix.lower() == ".js":
                files.append(entry)
            else:
                assets.append(entry)
        return {
            "provider": "diego",
            "provider_run_id": str(run.run_id),
            "provider_trace_id": str(run.trace_id),
            "mode": "scratch",
            "entrypoint": "slides/compile.js",
            "working_dir_manifest": {
                "dirs": ["slides", "slides/output"],
            },
            "files": files,
            "assets": assets,
            "compile_options": {
                "command": ["node", "compile.js"],
                "cwd": "slides",
                "output_artifact_path": "slides/output/presentation.pptx",
            },
            "metadata": {
                "artifact_dir": str(run.artifact_dir),
                "theme_source": "diego",
                "compile_context": {
                    "theme": theme or {},
                },
            },
        }
