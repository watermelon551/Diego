from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from uuid import uuid4

from .payloads import _safe_theme


def _encode_file(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _collect_slide_bundle_files(
    slides_dir: Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    files: list[dict[str, str]] = []
    assets: list[dict[str, str]] = []
    for file_path in sorted(slides_dir.rglob("*")):
        if not file_path.is_file():
            continue
        rel_path = file_path.relative_to(slides_dir).as_posix()
        if rel_path.startswith("output/") or rel_path.startswith(".pagevra-preview/"):
            continue
        entry = {
            "path": f"slides/{rel_path}",
            "content_base64": _encode_file(file_path),
        }
        if file_path.suffix.lower() == ".js":
            files.append(entry)
        else:
            assets.append(entry)
    return files, assets


def build_single_slide_compile_bundle(
    *,
    slide_js_path: Path,
    theme: dict[str, Any],
    slide_no: int,
    provider_run_id: str | None = None,
    provider_trace_id: str | None = None,
) -> dict[str, Any]:
    if not slide_js_path.exists() or not slide_js_path.is_file():
        raise FileNotFoundError(f"slide js not found: {slide_js_path}")
    slides_dir = slide_js_path.parent
    files, assets = _collect_slide_bundle_files(slides_dir)
    entrypoint = f"slides/{slide_js_path.relative_to(slides_dir).as_posix()}"
    slide_index = max(0, int(slide_no or 1) - 1)
    slide_id = f"slide-{slide_no:02d}"
    return {
        "provider": "diego",
        "provider_run_id": provider_run_id or f"preview-{uuid4().hex}",
        "provider_trace_id": provider_trace_id,
        "mode": "single_slide",
        "entrypoint": entrypoint,
        "working_dir_manifest": {
            "dirs": ["slides", "slides/output"],
        },
        "files": files,
        "assets": assets,
        "compile_options": {
            "command": ["node", "__pagevra_single_slide_compile.js"],
            "cwd": "slides",
            "output_artifact_path": f"slides/output/{slide_id}.pptx",
        },
        "metadata": {
            "compile_context": {
                "theme": _safe_theme(theme),
            },
            "slide_id": slide_id,
            "slide_index": slide_index,
            "source_entrypoint": entrypoint,
        },
    }
