from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from .slide_preview_runtime import (
    build_placeholder_preview as _build_placeholder_preview,
    build_preview_runner_js as _build_preview_runner_js,
    build_single_slide_compile_bundle as _build_single_slide_compile_bundle,
    build_slide_preview_payload as _build_slide_preview_payload,
    render_slide_via_pagevra_runtime,
)


def build_slide_preview_payload(
    *, run_id: str, slide_no: int, preview: dict[str, Any]
) -> dict[str, Any]:
    return _build_slide_preview_payload(run_id=run_id, slide_no=slide_no, preview=preview)


def build_placeholder_preview(
    *,
    slide_no: int,
    theme: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    return _build_placeholder_preview(slide_no=slide_no, theme=theme, reason=reason)


def build_preview_runner_js(*, slide_js_name: str, preview_name: str) -> str:
    return _build_preview_runner_js(slide_js_name=slide_js_name, preview_name=preview_name)


def build_single_slide_compile_bundle(
    *,
    slide_js_path: Path,
    theme: dict[str, Any],
    slide_no: int,
    provider_run_id: str | None = None,
    provider_trace_id: str | None = None,
) -> dict[str, Any]:
    return _build_single_slide_compile_bundle(
        slide_js_path=slide_js_path,
        theme=theme,
        slide_no=slide_no,
        provider_run_id=provider_run_id,
        provider_trace_id=provider_trace_id,
    )


async def render_slide_via_pagevra(
    *,
    slide_js_path: Path,
    theme: dict[str, Any],
    slide_no: int,
    pagevra_base_url: str,
    timeout_sec: float = 30.0,
    provider_run_id: str | None = None,
    provider_trace_id: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return await render_slide_via_pagevra_runtime(
        slide_js_path=slide_js_path,
        theme=theme,
        slide_no=slide_no,
        pagevra_base_url=pagevra_base_url,
        httpx_module=httpx,
        timeout_sec=timeout_sec,
        provider_run_id=provider_run_id,
        provider_trace_id=provider_trace_id,
        **kwargs,
    )


__all__ = [
    "build_placeholder_preview",
    "build_preview_runner_js",
    "build_single_slide_compile_bundle",
    "build_slide_preview_payload",
    "render_slide_via_pagevra",
]
