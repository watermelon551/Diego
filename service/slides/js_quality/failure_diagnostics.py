from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .asset_contract import collect_detected_api_violations


def truncate_diag_text(text: str, *, limit: int | None, default_limit: int) -> str:
    payload = str(text or "")
    max_chars = max(256, int(limit if limit is not None else default_limit))
    if len(payload) <= max_chars:
        return payload
    return payload[:max_chars] + f"\n...[truncated {len(payload) - max_chars} chars]"


def render_js_with_line_numbers(js_code: str, *, max_lines: int) -> str:
    lines = str(js_code or "").splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... [truncated {len(str(js_code or '').splitlines()) - max_lines} lines]"]
    return "\n".join(f"{idx + 1:04d}| {line}" for idx, line in enumerate(lines))


def extract_line_numbers(text: str) -> list[int]:
    import re

    line_numbers: list[int] = []
    for match in re.finditer(r":(\d+)(?::\d+)?\b", str(text or "")):
        try:
            value = int(match.group(1))
        except ValueError:
            continue
        if value > 0:
            line_numbers.append(value)
    seen: set[int] = set()
    deduped: list[int] = []
    for item in line_numbers:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped[:8]


def extract_js_focus_windows(js_code: str, *, line_numbers: list[int], radius: int = 4) -> list[dict[str, Any]]:
    lines = str(js_code or "").splitlines()
    if not lines:
        return []
    windows: list[dict[str, Any]] = []
    for line_no in line_numbers[:6]:
        idx = max(1, line_no)
        start = max(1, idx - radius)
        end = min(len(lines), idx + radius)
        snippet = "\n".join(f"{n:04d}| {lines[n - 1]}" for n in range(start, end + 1))
        windows.append({"line": idx, "start": start, "end": end, "snippet": snippet})
    return windows[:4]


def build_slide_failure_context(
    *,
    phase: str,
    slide_js_path: Path | None,
    candidate_js: str,
    issues: list[str],
    diagnostics: dict[str, Any] | None,
    truncate: Callable[[str, int | None], str],
    dedupe_preserve_order: Callable[[list[str]], list[str]],
    max_js_lines: int,
) -> dict[str, Any]:
    diag = dict(diagnostics or {})
    stdout = truncate(str(diag.get("stdout", "")), None)
    stderr = truncate(str(diag.get("stderr", "")), None)
    command = str(diag.get("command", ""))
    exit_code = diag.get("exit_code")
    error_class = str(diag.get("error_class", ""))
    error_message = truncate(str(diag.get("error_message", "")), None)
    numbered = render_js_with_line_numbers(candidate_js, max_lines=max(40, max_js_lines))
    line_numbers = extract_line_numbers("\n".join([stderr, stdout, error_message, "\n".join(issues or [])]))
    focus = extract_js_focus_windows(candidate_js, line_numbers=line_numbers)
    first_line = line_numbers[0] if line_numbers else None
    error_location = {"line": first_line} if first_line else {}
    gate_summary = diag.get("gate_summary") if isinstance(diag.get("gate_summary"), dict) else {}
    context = {
        "phase": phase,
        "slide_js": slide_js_path.name if slide_js_path else "",
        "slide_js_path": str(slide_js_path) if slide_js_path else "",
        "issues": dedupe_preserve_order([str(item) for item in (issues or []) if str(item).strip()])[:24],
        "command": command,
        "exit_code": exit_code,
        "stderr": stderr,
        "stdout": stdout,
        "stderr_excerpt": truncate(stderr, 1200),
        "stdout_excerpt": truncate(stdout, 1200),
        "error_class": error_class,
        "error_message": error_message,
        "error_location": error_location,
        "failed_js_full": truncate(candidate_js, 50000),
        "failed_js_with_line_no": numbered,
        "focus_windows": focus,
        "detected_api_violations": collect_detected_api_violations(candidate_js),
        "gate_summary": gate_summary,
    }
    if "preview_mode" in diag:
        context["preview_mode"] = diag.get("preview_mode")
    if "attempt" in diag:
        context["attempt"] = diag.get("attempt")
    return context
