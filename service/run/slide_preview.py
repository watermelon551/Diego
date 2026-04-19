from __future__ import annotations

import asyncio
import base64
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import httpx

_SLIDE_WIDTH_IN = 10.0
_SLIDE_HEIGHT_IN = 5.625
_VIEWPORT_WIDTH_PX = 1280
_VIEWPORT_HEIGHT_PX = 720
_DEFAULT_PAGEVRA_TEMPLATE_ID = "document-teaching"


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


async def _capture_slide_payload(
    *,
    slide_js_path: Path,
    theme: dict[str, Any],
    timeout_sec: float,
    subprocess_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    if not slide_js_path.exists() or not slide_js_path.is_file():
        raise FileNotFoundError(f"slide js not found: {slide_js_path}")

    runner_path = slide_js_path.parent / (
        f".html-preview-runner-{slide_js_path.stem}-{uuid4().hex[:8]}.js"
    )
    runner_path.write_text(_capture_runner_script(), encoding="utf-8")
    run = subprocess_runner or subprocess.run
    cmd = [
        "node",
        runner_path.name,
        slide_js_path.name,
        json.dumps(theme or {}, ensure_ascii=False),
    ]
    try:
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
                timeout=max(1.0, float(timeout_sec or 30.0)),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"slide preview capture timed out after {max(1.0, float(timeout_sec or 30.0)):.1f}s"
            ) from exc
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
    return captured


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


def _iter_operations(captured: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    operations = captured.get("operations") if isinstance(captured.get("operations"), list) else []
    return [
        item
        for item in operations
        if isinstance(item, dict)
        and str(item.get("kind") or "").strip().lower() == kind
        and isinstance(item.get("payload"), dict)
    ]


def _slide_config(captured: dict[str, Any]) -> dict[str, Any]:
    config = captured.get("slide_config")
    return dict(config) if isinstance(config, dict) else {}


def _normalize_lines(text: str) -> list[str]:
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def _dedupe_text(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _extract_text_entries(captured: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in _iter_operations(captured, "text"):
        payload = dict(item.get("payload") or {})
        options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
        text = _normalize_text_content(payload.get("content")).strip()
        if not text:
            continue
        entries.append(
            {
                "text": text,
                "font_size": _coerce_float(options.get("fontSize"), default=16.0),
                "x": _coerce_float(options.get("x"), default=0.0),
                "y": _coerce_float(options.get("y"), default=0.0),
                "bold": bool(options.get("bold")),
            }
        )
    return entries


def _resolve_page_kind(captured: dict[str, Any]) -> str:
    config = _slide_config(captured)
    raw = (
        config.get("page_type")
        or config.get("pageType")
        or config.get("type")
        or config.get("kind")
    )
    normalized = str(raw or "").strip().lower()
    mapping = {
        "cover": "cover",
        "toc": "toc",
        "section": "section",
        "summary": "summary_page",
        "summary_page": "summary_page",
    }
    return mapping.get(normalized, "content")


def _pick_page_title(captured: dict[str, Any]) -> str:
    config = _slide_config(captured)
    configured = str(config.get("title") or config.get("heading") or "").strip()
    if configured:
        return configured
    entries = _extract_text_entries(captured)
    if not entries:
        return ""
    ranked = sorted(
        entries,
        key=lambda item: (
            -float(item.get("font_size") or 0.0),
            float(item.get("y") or 0.0),
            float(item.get("x") or 0.0),
        ),
    )
    return str(ranked[0].get("text") or "").splitlines()[0].strip()


def _extract_page_copy(captured: dict[str, Any], title: str) -> tuple[list[str], list[str]]:
    config = _slide_config(captured)
    configured_bullets = config.get("bullets")
    bullets = []
    if isinstance(configured_bullets, list):
        bullets = _dedupe_text([str(item).strip() for item in configured_bullets])

    paragraphs: list[str] = []
    title_consumed = False
    for entry in sorted(
        _extract_text_entries(captured),
        key=lambda item: (float(item.get("y") or 0.0), float(item.get("x") or 0.0)),
    ):
        for line in _normalize_lines(str(entry.get("text") or "")):
            normalized = line[2:].strip() if line.startswith("- ") else line
            if title and normalized == title and not title_consumed:
                title_consumed = True
                continue
            if line.startswith("- "):
                bullets.append(normalized)
            else:
                paragraphs.append(normalized)
    return _dedupe_text(bullets), _dedupe_text(paragraphs)


def _collect_numeric_pairs(data: Any) -> list[tuple[str, float]]:
    pairs: list[tuple[str, float]] = []
    if not isinstance(data, list):
        return pairs
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            continue
        direct_value = item.get("value")
        if direct_value is None:
            direct_value = item.get("y")
        if direct_value is None and isinstance(item.get("values"), list):
            values = item.get("values") or []
            numeric = [
                _coerce_float(value, default=float("nan"))
                for value in values
                if isinstance(value, (int, float, str))
            ]
            numeric = [value for value in numeric if value == value]
            if numeric:
                direct_value = sum(numeric)
        if direct_value is None and isinstance(item.get("data"), list):
            numeric = []
            for point in item.get("data") or []:
                if isinstance(point, dict):
                    value = point.get("value")
                    if value is None:
                        value = point.get("y")
                else:
                    value = point
                parsed = _coerce_float(value, default=float("nan"))
                if parsed == parsed:
                    numeric.append(parsed)
            if numeric:
                direct_value = sum(numeric)
        parsed_value = _coerce_float(direct_value, default=float("nan"))
        if parsed_value != parsed_value:
            continue
        label = str(
            item.get("name")
            or item.get("label")
            or item.get("category")
            or item.get("series")
            or f"Series {index}"
        ).strip()
        if not label:
            label = f"Series {index}"
        pairs.append((label, parsed_value))
    return pairs


def _escape_mermaid_label(text: str) -> str:
    return str(text or "").replace('"', "'")


def _build_mermaid_chart_code(payload: dict[str, Any]) -> str | None:
    chart_type = str(payload.get("chartType") or "").strip().lower()
    pairs = _collect_numeric_pairs(payload.get("data"))
    if chart_type not in {"pie", "doughnut", "donut"} or not pairs:
        return None
    lines = ["pie showData"]
    for label, value in pairs[:8]:
        lines.append(f'    "{_escape_mermaid_label(label)}" : {value:g}')
    return "\n".join(lines)


def _summarize_chart_payload(payload: dict[str, Any]) -> str:
    chart_type = str(payload.get("chartType") or "chart").strip().upper() or "CHART"
    pairs = _collect_numeric_pairs(payload.get("data"))
    if not pairs:
        return f"{chart_type} chart"
    summary = ", ".join(f"{label} {value:g}" for label, value in pairs[:4])
    return f"{chart_type} chart: {summary}"


def _collect_pagevra_image_blocks(*, captured: dict[str, Any], slide_dir: Path) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for item in _iter_operations(captured, "image"):
        payload = dict(item.get("payload") or {})
        options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
        src = _resolve_image_source(options=options, slide_dir=slide_dir)
        if not src:
            continue
        alt = str(options.get("altText") or options.get("alt") or "Slide image").strip() or "Slide image"
        blocks.append({"type": "image", "src": src, "alt": alt})
    return blocks[:2]


def _collect_pagevra_chart_blocks(captured: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for item in _iter_operations(captured, "chart"):
        payload = dict(item.get("payload") or {})
        mermaid = _build_mermaid_chart_code(payload)
        if mermaid:
            blocks.append({"type": "mermaid", "code": mermaid, "title": str(payload.get("chartType") or "chart")})
            continue
        blocks.append({"type": "paragraph", "text": _summarize_chart_payload(payload)})
    return blocks[:2]


def _build_pagevra_structure(*, page_kind: str, bullets: list[str], paragraphs: list[str]) -> dict[str, Any] | None:
    if page_kind == "cover":
        cover: dict[str, Any] = {}
        if bullets:
            cover["eyebrow"] = bullets[0]
        if paragraphs:
            cover["subtitle"] = paragraphs[0]
        return {"cover": cover} if cover else None
    if page_kind == "summary_page":
        summary: dict[str, Any] = {}
        if bullets:
            summary["key_points"] = bullets[:6]
        if paragraphs:
            summary["closing_note"] = paragraphs[0]
        return {"summary_page": summary} if summary else None
    return None


def _build_layout_hints(blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    has_visual = any(block.get("type") in {"image", "mermaid"} for block in blocks)
    if not has_visual:
        return None
    return {
        "visual_priority": "balanced",
        "allow_columns": True,
        "emphasis_level": "medium",
    }


def _operations_to_pagevra_page(
    *,
    captured: dict[str, Any],
    slide_js_path: Path,
    slide_no: int,
    theme: dict[str, str],
) -> dict[str, Any]:
    page_index = max(0, slide_no - 1)
    page_kind = _resolve_page_kind(captured)
    title = _pick_page_title(captured) or f"Slide {slide_no}"
    bullets, paragraphs = _extract_page_copy(captured, title)
    blocks: list[dict[str, Any]] = [{"type": "heading", "text": title, "level": 1}]
    if bullets:
        blocks.append({"type": "bullet_list", "items": bullets[:8], "ordered": False})
    for paragraph in paragraphs[:3]:
        if paragraph != title:
            blocks.append({"type": "paragraph", "text": paragraph})
    blocks.extend(_collect_pagevra_image_blocks(captured=captured, slide_dir=slide_js_path.parent))
    blocks.extend(_collect_pagevra_chart_blocks(captured))
    if not blocks:
        blocks.append({"type": "paragraph", "text": f"Slide {slide_no}"})

    structure = _build_pagevra_structure(page_kind=page_kind, bullets=bullets, paragraphs=paragraphs)
    page: dict[str, Any] = {
        "page_id": f"slide-{slide_no}",
        "page_index": page_index,
        "title": title,
        "kind": page_kind,
        "layout": page_kind,
        "blocks": blocks[:8],
        "metadata": {
            "source": "diego",
            "background": _resolve_background_color(captured=captured, theme=theme),
        },
    }
    layout_hints = _build_layout_hints(blocks)
    if layout_hints:
        page["layout_hints"] = layout_hints
    if structure:
        page["structure"] = structure
    return page


def _build_pagevra_render_input(
    *,
    captured: dict[str, Any],
    slide_js_path: Path,
    slide_no: int,
    theme: dict[str, str],
) -> dict[str, Any]:
    output_dir = (slide_js_path.parent / ".pagevra-preview").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    page = _operations_to_pagevra_page(
        captured=captured,
        slide_js_path=slide_js_path,
        slide_no=slide_no,
        theme=theme,
    )
    return {
        "render_job_id": f"diego-preview-{slide_js_path.stem}-{uuid4().hex[:8]}",
        "page_id": page["page_id"],
        "page_index": page["page_index"],
        "document_title": page.get("title") or f"Slide {slide_no}",
        "output_dir": str(output_dir),
        "render": {
            "outputs": ["preview"],
            "theme": {
                "theme_id": "default",
                "template_id": _DEFAULT_PAGEVRA_TEMPLATE_ID,
                "overrides": {
                    "accent_color": theme["accent"],
                    "background": theme["bg"],
                    "foreground": theme["secondary"],
                },
            },
        },
        "page": page,
    }


async def render_slide_html_preview(
    *,
    slide_js_path: Path,
    theme: dict[str, Any],
    subprocess_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    captured = await _capture_slide_payload(
        slide_js_path=slide_js_path,
        theme=theme,
        timeout_sec=30.0,
        subprocess_runner=subprocess_runner,
    )
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


async def render_slide_via_pagevra(
    *,
    slide_js_path: Path,
    theme: dict[str, Any],
    slide_no: int,
    pagevra_base_url: str,
    timeout_sec: float = 30.0,
    subprocess_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    base_url = str(pagevra_base_url or "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError("pagevra_base_url is required for page preview rendering")

    captured = await _capture_slide_payload(
        slide_js_path=slide_js_path,
        theme=theme,
        timeout_sec=timeout_sec,
        subprocess_runner=subprocess_runner,
    )
    normalized_theme = _normalize_theme(theme if isinstance(theme, dict) else captured.get("theme"))
    payload = _build_pagevra_render_input(
        captured=captured,
        slide_js_path=slide_js_path,
        slide_no=slide_no,
        theme=normalized_theme,
    )

    try:
        async with httpx.AsyncClient(timeout=max(1.0, float(timeout_sec or 30.0))) as client:
            response = await client.post(f"{base_url}/render/pages", json=payload)
    except httpx.TimeoutException as exc:
        raise RuntimeError(
            f"pagevra preview render timed out after {max(1.0, float(timeout_sec or 30.0)):.1f}s"
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"pagevra preview render request failed: {exc}") from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"pagevra preview render returned invalid JSON: {response.text[:200]}"
        ) from exc

    if not isinstance(body, dict):
        raise RuntimeError("pagevra preview render returned invalid payload")
    if response.status_code >= 400:
        reason = str(body.get("error") or body.get("state_reason") or response.text[:200]).strip()
        raise RuntimeError(f"pagevra preview render failed: {reason}")
    if str(body.get("state") or "").strip().lower() != "success":
        reason = str(body.get("state_reason") or body.get("error") or "page_render_failed").strip()
        raise RuntimeError(f"pagevra preview render failed: {reason}")

    image_url = str(body.get("preview_image_data_url") or "")
    if not image_url.strip():
        preview_image_data_urls = body.get("preview_image_data_urls")
        if isinstance(preview_image_data_urls, list):
            first_image = next(
                (str(item).strip() for item in preview_image_data_urls if str(item or "").strip()),
                "",
            )
            image_url = first_image

    html_preview = str(body.get("html_preview") or "")
    if not html_preview.strip():
        html_previews = body.get("html_previews")
        if isinstance(html_previews, list):
            first_preview = next(
                (str(item).strip() for item in html_previews if str(item or "").strip()),
                "",
            )
            html_preview = first_preview
    if not html_preview.strip() and not image_url.strip():
        raise RuntimeError("pagevra preview render returned neither html_preview nor preview_image_data_url")

    warnings = body.get("warnings") if isinstance(body.get("warnings"), list) else []
    return {
        "html_preview": html_preview or None,
        "image_url": image_url or None,
        "width": _VIEWPORT_WIDTH_PX,
        "height": _VIEWPORT_HEIGHT_PX,
        "warnings": warnings,
    }
