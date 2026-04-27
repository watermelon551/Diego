from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any, Awaitable, Callable

from ....models import EventType
from ...slide_preview import build_preview_runner_js
from .process_failure import summarize_process_failure


async def run_slide_preview_qa_with_text(
    *,
    run_id: str,
    slide_js: Path,
    slide_no: int,
    preview_qa_gate: BoundedSemaphore,
    llm_timeout_sec: float,
    debug_keep_previews: bool,
    run_subprocess: Callable[..., subprocess.CompletedProcess[str]],
    known_compile_stderr_reason: Callable[..., str | None],
    truncate_diag_text: Callable[[str], str],
    exception_reason: Callable[[Exception], str],
    publish: Callable[[str, EventType, dict[str, Any]], Awaitable[None]],
    append_artifact_cleanup_entry: Callable[..., Awaitable[None]],
    extract_preview_text: Callable[[Path], Awaitable[tuple[str, str | None]]],
) -> tuple[list[str], str, dict[str, Any]]:
    issues: list[str] = []
    preview_text = ""
    diagnostics: dict[str, Any] = {}
    cleanup_note = "skipped"
    preview_file = slide_js.parent / f"slide-{slide_no:02d}-preview.pptx"
    preview_runner = slide_js.parent / f".preview-runner-{slide_no:02d}.js"
    preview_runner.write_text(
        build_preview_runner_js(
            slide_js_name=slide_js.name,
            preview_name=preview_file.name,
        ),
        encoding="utf-8",
    )
    preview_cmd = ["node", preview_runner.name]
    acquired = False
    try:
        acquired = await asyncio.to_thread(
            preview_qa_gate.acquire,
            True,
            max(2.0, llm_timeout_sec),
        )
        if not acquired:
            raise TimeoutError("preview compile gate timeout")
        result = await asyncio.to_thread(
            run_subprocess,
            preview_cmd,
            cwd=slide_js.parent,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception as exc:
        error_message = exception_reason(exc)
        diagnostics = {
            "command": " ".join(preview_cmd),
            "exit_code": None,
            "stderr": "",
            "stdout": "",
            "error_class": type(exc).__name__,
            "error_message": error_message,
        }
        issues.append(f"{slide_js.name}: preview compile failed: {error_message}")
        await _publish_preview_result(
            publish=publish,
            run_id=run_id,
            slide_no=slide_no,
            slide_js=slide_js.name,
            issues=issues,
        )
        return issues, preview_text, diagnostics
    finally:
        if acquired:
            preview_qa_gate.release()
        preview_runner.unlink(missing_ok=True)

    if result.returncode != 0:
        reason, details = summarize_process_failure(
            stderr=result.stderr or "",
            stdout=result.stdout or "",
        )
        issues.append(f"{slide_js.name}: preview compile failed: {reason}")
        if details:
            issues.append(f"{slide_js.name}: preview compile details: {details}")
        diagnostics = {
            "command": " ".join(preview_cmd),
            "exit_code": result.returncode,
            "stderr": truncate_diag_text(result.stderr or ""),
            "stdout": truncate_diag_text(result.stdout or ""),
            "error_message": reason,
        }
        await _publish_preview_result(
            publish=publish,
            run_id=run_id,
            slide_no=slide_no,
            slide_js=slide_js.name,
            issues=issues,
        )
        return issues, preview_text, diagnostics

    known_reason = known_compile_stderr_reason(
        stderr=result.stderr or "",
        stdout=result.stdout or "",
    )
    if known_reason:
        issues.append(f"{slide_js.name}: preview compile failed: {known_reason}")
        diagnostics = {
            "command": " ".join(preview_cmd),
            "exit_code": result.returncode,
            "stderr": truncate_diag_text(result.stderr or ""),
            "stdout": truncate_diag_text(result.stdout or ""),
            "error_message": known_reason,
        }
        await _publish_preview_result(
            publish=publish,
            run_id=run_id,
            slide_no=slide_no,
            slide_js=slide_js.name,
            issues=issues,
        )
        return issues, preview_text, diagnostics

    if not preview_file.exists():
        issues.append(f"{slide_js.name}: preview pptx missing")
        diagnostics = {
            "command": " ".join(preview_cmd),
            "exit_code": 0,
            "stderr": "",
            "stdout": "",
            "error_message": "preview pptx missing",
        }
        await _publish_preview_result(
            publish=publish,
            run_id=run_id,
            slide_no=slide_no,
            slide_js=slide_js.name,
            issues=issues,
        )
        return issues, preview_text, diagnostics

    preview_text, preview_issue = await extract_preview_text(preview_file)
    if preview_issue:
        issues.append(f"{slide_js.name}: {preview_issue}")
        diagnostics = {
            "command": f"{sys.executable} -m markitdown {preview_file.name}",
            "exit_code": 0,
            "stderr": "",
            "stdout": truncate_diag_text(preview_text),
            "error_message": preview_issue,
        }
    cleanup_note = await _cleanup_preview_file(
        preview_file=preview_file,
        debug_keep_previews=debug_keep_previews,
    )
    await append_artifact_cleanup_entry(
        run_id=run_id,
        entry={
            "slide_no": slide_no,
            "file": str(preview_file),
            "action": cleanup_note,
        },
    )
    await publish(
        run_id,
        EventType.ARTIFACT_CLEANUP_COMPLETED,
        {"slide_no": slide_no, "file": str(preview_file), "action": cleanup_note},
    )
    await _publish_preview_result(
        publish=publish,
        run_id=run_id,
        slide_no=slide_no,
        slide_js=slide_js.name,
        issues=issues,
    )
    return issues, preview_text, diagnostics


async def _cleanup_preview_file(
    *, preview_file: Path, debug_keep_previews: bool
) -> str:
    if not debug_keep_previews and preview_file.exists():
        preview_file.unlink(missing_ok=True)
        return "deleted"
    if preview_file.exists():
        return "kept_by_debug"
    return "skipped"


async def _publish_preview_result(
    *,
    publish: Callable[[str, EventType, dict[str, Any]], Awaitable[None]],
    run_id: str,
    slide_no: int,
    slide_js: str,
    issues: list[str],
) -> None:
    await publish(
        run_id,
        EventType.SLIDE_PREVIEW_QA,
        {
            "slide_no": slide_no,
            "slide_js": slide_js,
            "passed": not issues,
            "issues": issues,
        },
    )
