from __future__ import annotations

import asyncio
import base64
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

_SLIDE_WIDTH_IN = 10.0
_SLIDE_HEIGHT_IN = 5.625
_VIEWPORT_WIDTH_PX = 1600
_VIEWPORT_HEIGHT_PX = 900


def _capture_runner_script() -> str:
    return "\n".join(
        [
            "const path = require('path');",
            "",
            "function toSerializable(value) {",
            "  try {",
            "    return JSON.parse(JSON.stringify(value));",
            "  } catch (_) {",
            "    return null;",
            "  }",
            "}",
            "",
            "function operation(kind, payload) {",
            "  return { kind, payload: toSerializable(payload) };",
            "}",
            "",
            "(async () => {",
            "  const slidePath = process.argv[2];",
            "  const themeRaw = process.argv[3] || '{}';",
            "  if (!slidePath) {",
            "    throw new Error('missing slide path');",
            "  }",
            "  const mod = require(path.resolve(slidePath));",
            "  if (!mod || typeof mod.createSlide !== 'function') {",
            "    throw new Error('missing createSlide export');",
            "  }",
            "  let theme = {};",
            "  try {",
            "    theme = JSON.parse(themeRaw);",
            "  } catch (_) {",
            "    theme = {};",
            "  }",
            "  const operations = [];",
            "  let background = null;",
            "  const slide = {",
            "    addText: (content, options = {}) => operations.push(operation('text', { content, options })),",
            "    addShape: (shape, options = {}) => operations.push(operation('shape', { shape: String(shape || ''), options })),",
            "    addImage: (options = {}) => operations.push(operation('image', { options })),",
            "    addChart: (chartType, data, options = {}) => operations.push(operation('chart', { chartType: String(chartType || ''), data, options })),",
            "  };",
            "  Object.defineProperty(slide, 'background', {",
            "    configurable: true,",
            "    enumerable: true,",
            "    get() { return background; },",
            "    set(value) {",
            "      background = toSerializable(value);",
            "      operations.push(operation('background', value));",
            "    },",
            "  });",
            "",
            "  const pres = {",
            "    shapes: new Proxy({}, { get: (_target, prop) => String(prop || '') }),",
            "    charts: new Proxy({}, { get: (_target, prop) => String(prop || '') }),",
            "    addSlide: () => slide,",
            "  };",
            "",
            "  mod.createSlide(pres, theme);",
            "  process.stdout.write(JSON.stringify({ operations, background, slide_config: toSerializable(mod.slideConfig), theme: toSerializable(theme) }));",
            "})().catch((error) => {",
            "  const message = error && error.stack ? String(error.stack) : String(error || 'capture failed');",
            "  process.stderr.write(message);",
            "  process.exit(1);",
            "});",
        ]
    )


def _coerce_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _safe_color(value: Any, fallback: str) -> str:
    text = str(value or "").strip().lstrip("#")
    if re.fullmatch(r"[0-9A-Fa-f]{6}", text):
        return f"#{text.upper()}"
    if re.fullmatch(r"[0-9A-Fa-f]{3}", text):
        expanded = "".join([char * 2 for char in text.upper()])
        return f"#{expanded}"
    return fallback


def _opacity_from_transparency(value: Any) -> float:
    transparency = _coerce_float(value, default=0.0)
    opacity = 1.0 - max(0.0, min(100.0, transparency)) / 100.0
    return round(opacity, 3)


def _px_x(value: Any) -> int:
    return int(round(max(0.0, _coerce_float(value)) / _SLIDE_WIDTH_IN * _VIEWPORT_WIDTH_PX))


def _px_y(value: Any) -> int:
    return int(round(max(0.0, _coerce_float(value)) / _SLIDE_HEIGHT_IN * _VIEWPORT_HEIGHT_PX))


def _px_w(value: Any, default: int) -> int:
    width = _coerce_float(value, default=0.0)
    if width <= 0:
        return default
    return int(round(width / _SLIDE_WIDTH_IN * _VIEWPORT_WIDTH_PX))


def _px_h(value: Any, default: int) -> int:
    height = _coerce_float(value, default=0.0)
    if height <= 0:
        return default
    return int(round(height / _SLIDE_HEIGHT_IN * _VIEWPORT_HEIGHT_PX))


def _normalize_text_content(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        lines: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                options = item.get("options")
                if isinstance(options, dict) and options.get("bullet"):
                    text = f"- {text}"
                lines.append(text)
                continue
            text = str(item or "").strip()
            if text:
                lines.append(text)
        return "\n".join(lines)
    return str(raw or "")


def _mime_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    if suffix == ".svg":
        return "image/svg+xml"
    return "application/octet-stream"


def _resolve_image_source(*, options: dict[str, Any], slide_dir: Path) -> str | None:
    for key in ("data", "path", "url"):
        value = options.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        text = value.strip()
        if text.startswith("data:image"):
            return text
        if text.startswith("http://") or text.startswith("https://"):
            return text
        candidate = Path(text)
        if not candidate.is_absolute():
            candidate = (slide_dir / candidate).resolve()
        if not candidate.exists() or not candidate.is_file():
            continue
        encoded = base64.b64encode(candidate.read_bytes()).decode("ascii")
        return f"data:{_mime_type_for(candidate)};base64,{encoded}"
    return None


def _render_shape(payload: dict[str, Any], theme: dict[str, str]) -> str:
    shape = str(payload.get("shape") or "").upper()
    options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
    x = _px_x(options.get("x"))
    y = _px_y(options.get("y"))
    w = _px_w(options.get("w"), default=120)
    h = _px_h(options.get("h"), default=40)
    fill = options.get("fill") if isinstance(options.get("fill"), dict) else {}
    line = options.get("line") if isinstance(options.get("line"), dict) else {}
    fill_color = _safe_color(fill.get("color"), theme["light"])
    line_color = _safe_color(line.get("color"), theme["secondary"])
    opacity = _opacity_from_transparency(fill.get("transparency"))
    border_width = max(1, int(round(_coerce_float(line.get("pt"), default=1.0) * 1.4)))
    radius = "12px"
    if "OVAL" in shape:
        radius = "9999px"
    elif "ROUNDED" in shape:
        radius = "16px"
    elif "LINE" in shape:
        radius = "2px"

    if "LINE" in shape:
        return (
            f"<div class=\"shape line\" style=\"left:{x}px;top:{y}px;width:{max(w,2)}px;height:{max(h,2)}px;"
            f"border-top:{border_width}px solid {line_color};opacity:{opacity};\"></div>"
        )

    return (
        f"<div class=\"shape\" style=\"left:{x}px;top:{y}px;width:{w}px;height:{h}px;"
        f"background:{fill_color};opacity:{opacity};border:{border_width}px solid {line_color};"
        f"border-radius:{radius};\"></div>"
    )


def _render_text(payload: dict[str, Any], theme: dict[str, str]) -> str:
    options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
    content = _normalize_text_content(payload.get("content"))
    if not content.strip():
        return ""

    x = _px_x(options.get("x"))
    y = _px_y(options.get("y"))
    w = _px_w(options.get("w"), default=260)
    h = _px_h(options.get("h"), default=80)
    color = _safe_color(options.get("color"), theme["secondary"])
    font_size = max(10, int(round(_coerce_float(options.get("fontSize"), default=16.0))))
    weight = "700" if options.get("bold") else "400"
    align = str(options.get("align") or "left")
    if align not in {"left", "center", "right", "justify"}:
        align = "left"

    escaped = (
        content.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )
    return (
        f"<div class=\"text\" style=\"left:{x}px;top:{y}px;width:{w}px;height:{h}px;"
        f"color:{color};font-size:{font_size}px;font-weight:{weight};text-align:{align};\">{escaped}</div>"
    )


def _render_image(payload: dict[str, Any], theme: dict[str, str], slide_dir: Path) -> str:
    options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
    x = _px_x(options.get("x"))
    y = _px_y(options.get("y"))
    w = _px_w(options.get("w"), default=280)
    h = _px_h(options.get("h"), default=180)
    source = _resolve_image_source(options=options, slide_dir=slide_dir)
    if source:
        return (
            f"<img class=\"image\" src=\"{source}\" style=\"left:{x}px;top:{y}px;width:{w}px;height:{h}px;\" alt=\"slide image\"/>"
        )
    return (
        f"<div class=\"image placeholder\" style=\"left:{x}px;top:{y}px;width:{w}px;height:{h}px;"
        f"border:1px dashed {theme['secondary']};color:{theme['secondary']};\">Image</div>"
    )


def _render_chart(payload: dict[str, Any], theme: dict[str, str]) -> str:
    options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
    chart_type = str(payload.get("chartType") or "chart").upper()
    x = _px_x(options.get("x"))
    y = _px_y(options.get("y"))
    w = _px_w(options.get("w"), default=300)
    h = _px_h(options.get("h"), default=200)
    return (
        f"<div class=\"chart\" style=\"left:{x}px;top:{y}px;width:{w}px;height:{h}px;"
        f"border:1px solid {theme['accent']};color:{theme['accent']};\">{chart_type}</div>"
    )


def _resolve_background_color(*, captured: dict[str, Any], theme: dict[str, str]) -> str:
    background = captured.get("background")
    if isinstance(background, dict):
        return _safe_color(background.get("color"), theme["bg"])

    operations = captured.get("operations") if isinstance(captured.get("operations"), list) else []
    for item in operations:
        if not isinstance(item, dict) or item.get("kind") != "background":
            continue
        payload = item.get("payload")
        if isinstance(payload, dict):
            value = payload.get("value")
            if isinstance(value, dict):
                return _safe_color(value.get("color"), theme["bg"])
    return theme["bg"]


def _normalize_theme(theme: dict[str, Any] | None) -> dict[str, str]:
    source = theme if isinstance(theme, dict) else {}
    return {
        "primary": _safe_color(source.get("primary"), "#111111"),
        "secondary": _safe_color(source.get("secondary"), "#333333"),
        "accent": _safe_color(source.get("accent"), "#0A84FF"),
        "light": _safe_color(source.get("light"), "#EEF2F7"),
        "bg": _safe_color(source.get("bg"), "#FFFFFF"),
    }


def _build_preview_html(*, captured: dict[str, Any], slide_dir: Path, theme: dict[str, str]) -> str:
    background_color = _resolve_background_color(captured=captured, theme=theme)
    operations = captured.get("operations") if isinstance(captured.get("operations"), list) else []
    layers: list[str] = []

    for operation in operations:
        if not isinstance(operation, dict):
            continue
        kind = str(operation.get("kind") or "").strip().lower()
        payload = operation.get("payload") if isinstance(operation.get("payload"), dict) else {}
        if kind == "text":
            html_chunk = _render_text(payload, theme)
        elif kind == "shape":
            html_chunk = _render_shape(payload, theme)
        elif kind == "image":
            html_chunk = _render_image(payload, theme, slide_dir)
        elif kind == "chart":
            html_chunk = _render_chart(payload, theme)
        else:
            html_chunk = ""
        if html_chunk:
            layers.append(html_chunk)

    body = "\n".join(layers)
    return "".join(
        [
            "<!doctype html><html><head><meta charset=\"utf-8\"/>",
            "<style>",
            "html,body{margin:0;padding:0;background:#0b1220;} ",
            f".slide-preview-stage{{position:relative;width:{_VIEWPORT_WIDTH_PX}px;height:{_VIEWPORT_HEIGHT_PX}px;background:{background_color};overflow:hidden;font-family:'Segoe UI',Arial,sans-serif;}}",
            ".slide-preview-stage .shape,.slide-preview-stage .text,.slide-preview-stage .image,.slide-preview-stage .chart{position:absolute;box-sizing:border-box;}",
            ".slide-preview-stage .text{white-space:pre-wrap;overflow:hidden;line-height:1.28;}",
            ".slide-preview-stage .image{object-fit:cover;background:#f6f8fb;}",
            ".slide-preview-stage .image.placeholder,.slide-preview-stage .chart{display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:600;background:rgba(255,255,255,0.6);}",
            "</style></head><body>",
            f"<div class=\"slide-preview-stage\">{body}</div>",
            "</body></html>",
        ]
    )


async def render_slide_html_preview(
    *,
    slide_js_path: Path,
    theme: dict[str, Any],
    subprocess_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    if not slide_js_path.exists() or not slide_js_path.is_file():
        raise FileNotFoundError(f"slide js not found: {slide_js_path}")

    runner_path = slide_js_path.parent / f".html-preview-runner-{slide_js_path.stem}.js"
    runner_path.write_text(_capture_runner_script(), encoding="utf-8")
    run = subprocess_runner or subprocess.run
    cmd = [
        "node",
        runner_path.name,
        slide_js_path.name,
        json.dumps(theme or {}, ensure_ascii=False),
    ]
    try:
        result = await asyncio.to_thread(
            run,
            cmd,
            cwd=slide_js_path.parent,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    finally:
        runner_path.unlink(missing_ok=True)

    if result.returncode != 0:
        reason = (result.stderr or result.stdout or "slide html preview failed").strip()
        raise RuntimeError(reason[:1200])

    stdout = str(result.stdout or "").strip()
    if not stdout:
        raise RuntimeError("slide html preview capture returned empty output")

    try:
        captured = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"slide html preview returned invalid JSON: {stdout[:200]}") from exc

    if not isinstance(captured, dict):
        raise RuntimeError("slide html preview capture payload is invalid")

    normalized_theme = _normalize_theme(theme if isinstance(theme, dict) else captured.get("theme"))
    html_preview = _build_preview_html(
        captured=captured,
        slide_dir=slide_js_path.parent,
        theme=normalized_theme,
    )
    return {
        "html_preview": html_preview,
        "width": _VIEWPORT_WIDTH_PX,
        "height": _VIEWPORT_HEIGHT_PX,
    }
