from __future__ import annotations

from pathlib import Path
from typing import Any

_DEFAULT_PREVIEW_WIDTH = 960
_DEFAULT_PREVIEW_HEIGHT = 540

from .bundle import build_single_slide_compile_bundle


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


async def render_slide_via_pagevra_runtime(
    *,
    slide_js_path: Path,
    theme: dict[str, Any],
    slide_no: int,
    pagevra_base_url: str,
    httpx_module: Any,
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

    timeout_value = max(1.0, float(timeout_sec or 30.0))
    try:
        async with httpx_module.AsyncClient(timeout=timeout_value) as client:
            response = await client.post(f"{base_url}/compile/bundles", json=bundle)
    except httpx_module.TimeoutException as exc:
        raise RuntimeError(
            f"pagevra single-slide compile timed out after {timeout_value:.1f}s"
        ) from exc
    except httpx_module.HTTPError as exc:
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
