from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

_DEFAULT_PREVIEW_WIDTH = 960
_DEFAULT_PREVIEW_HEIGHT = 540


def _encode_file(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _safe_theme(theme: dict[str, Any] | None) -> dict[str, str]:
    source = theme if isinstance(theme, dict) else {}
    result: dict[str, str] = {}
    for key, fallback in {
        "primary": "111111",
        "secondary": "222222",
        "accent": "0A84FF",
        "light": "F2F3F5",
        "bg": "FFFFFF",
    }.items():
        value = str(source.get(key) or fallback).strip().lstrip("#")
        result[key] = value or fallback
    return result


def _collect_slide_bundle_files(slides_dir: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
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


def _first_svg_preview(body: dict[str, Any]) -> dict[str, Any]:
    artifacts = body.get("artifacts")
    preview_pages = artifacts.get("preview_pages") if isinstance(artifacts, dict) else None
    if not isinstance(preview_pages, list) or not preview_pages:
        raise RuntimeError("pagevra single-slide compile returned no preview_pages")
    first = preview_pages[0]
    if not isinstance(first, dict):
        raise RuntimeError("pagevra single-slide compile returned invalid preview manifest")
    if str(first.get("format") or "").strip().lower() != "svg":
        raise RuntimeError("pagevra single-slide compile returned non-svg preview")
    svg_data_url = str(first.get("svg_data_url") or "").strip()
    if not svg_data_url.startswith("data:image/svg+xml"):
        raise RuntimeError("pagevra single-slide compile returned missing svg_data_url")
    return first


async def render_slide_via_pagevra(
    *,
    slide_js_path: Path,
    theme: dict[str, Any],
    slide_no: int,
    pagevra_base_url: str,
    timeout_sec: float = 30.0,
    provider_run_id: str | None = None,
    provider_trace_id: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    base_url = str(pagevra_base_url or "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError("pagevra_base_url is required for single-slide preview compile")
    bundle = build_single_slide_compile_bundle(
        slide_js_path=slide_js_path,
        theme=theme,
        slide_no=slide_no,
        provider_run_id=provider_run_id,
        provider_trace_id=provider_trace_id,
    )

    try:
        async with httpx.AsyncClient(timeout=max(1.0, float(timeout_sec or 30.0))) as client:
            response = await client.post(f"{base_url}/compile/bundles", json=bundle)
    except httpx.TimeoutException as exc:
        raise RuntimeError(
            f"pagevra single-slide compile timed out after {max(1.0, float(timeout_sec or 30.0)):.1f}s"
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"pagevra single-slide compile request failed: {exc}") from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"pagevra single-slide compile returned invalid JSON: {response.text[:200]}"
        ) from exc

    if not isinstance(body, dict):
        raise RuntimeError("pagevra single-slide compile returned invalid payload")
    if response.status_code >= 400:
        reason = str(body.get("error") or body.get("state_reason") or response.text[:200]).strip()
        raise RuntimeError(f"pagevra single-slide compile failed: {reason}")
    if str(body.get("state") or "").strip().lower() != "success":
        reason = str(body.get("state_reason") or body.get("error") or "single_slide_compile_failed").strip()
        raise RuntimeError(f"pagevra single-slide compile failed: {reason}")

    preview = _first_svg_preview(body)
    width = preview.get("width")
    height = preview.get("height")
    return {
        "preview": preview,
        "preview_format": "svg",
        "svg_data_url": preview["svg_data_url"],
        "width": width if isinstance(width, (int, float)) and width > 0 else _DEFAULT_PREVIEW_WIDTH,
        "height": height if isinstance(height, (int, float)) and height > 0 else _DEFAULT_PREVIEW_HEIGHT,
        "pagevra_job_id": str(body.get("job_id") or ""),
        "warnings": body.get("warnings") if isinstance(body.get("warnings"), list) else [],
    }
