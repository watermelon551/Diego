from __future__ import annotations

from pathlib import Path
from typing import Any

from ....models import EventType, GenerationMode
from ..failure_artifacts import (
    persist_failed_candidate_js,
    persist_qa_failure_artifacts,
    split_qa_issues_by_slide,
)
from ..failure_diagnostics import build_slide_failure_context, truncate_diag_text
from ..parsing_runtime import (
    dedupe_preserve_order,
    extract_js_focus_windows,
    extract_line_numbers,
    render_js_with_line_numbers,
)


class SlideJsDiagnosticsRuntimeMixin:
    def _truncate_diag_text(self, text: str, *, limit: int | None = None) -> str:
        return truncate_diag_text(
            text,
            limit=limit,
            default_limit=self.slide_diag_max_stderr_chars,
        )

    def _render_js_with_line_numbers(self, js_code: str) -> str:
        return render_js_with_line_numbers(
            js_code,
            max_js_lines=self.slide_diag_max_js_lines,
        )

    def _extract_line_numbers(self, text: str) -> list[int]:
        return extract_line_numbers(text)

    def _extract_js_focus_windows(
        self, js_code: str, *, line_numbers: list[int], radius: int = 4
    ) -> list[dict[str, Any]]:
        return extract_js_focus_windows(
            js_code,
            line_numbers=line_numbers,
            radius=radius,
        )

    def _build_slide_failure_context(
        self,
        *,
        phase: str,
        slide_js_path: Path | None,
        candidate_js: str,
        issues: list[str],
        diagnostics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return build_slide_failure_context(
            phase=phase,
            slide_js_path=slide_js_path,
            candidate_js=candidate_js,
            issues=issues,
            diagnostics=diagnostics,
            truncate=lambda payload, payload_limit: self._truncate_diag_text(
                payload, limit=payload_limit
            ),
            dedupe_preserve_order=self._dedupe_preserve_order,
            max_js_lines=self.slide_diag_max_js_lines,
        )

    async def _publish_retry_context_event(
        self,
        *,
        run_id: str,
        slide_no: int,
        repair_round: int,
        candidate_no: int,
        phase: str,
        issues: list[str],
        context: dict[str, Any],
    ) -> None:
        error_location = (
            context.get("error_location", {})
            if isinstance(context.get("error_location", {}), dict)
            else {}
        )
        gate_summary = (
            context.get("gate_summary", {})
            if isinstance(context.get("gate_summary", {}), dict)
            else {}
        )
        await self._publish(
            run_id,
            EventType.SLIDE_RETRY_CONTEXT_BUILT,
            {
                "slide_no": slide_no,
                "round": repair_round,
                "candidate": candidate_no,
                "phase": phase,
                "issue_count": len(issues or []),
                "failing_js_path": context.get("slide_js_path", ""),
                "stderr_excerpt": context.get("stderr_excerpt", ""),
                "error_location": error_location,
                "gate_summary": gate_summary,
                "attempt": context.get("attempt"),
            },
        )

    def _persist_failed_candidate_js(
        self,
        *,
        slides_dir: Path,
        slide_no: int,
        js_code: str,
        round_no: int,
        issues: list[str],
    ) -> None:
        persist_failed_candidate_js(
            slides_dir=slides_dir,
            slide_no=slide_no,
            js_code=js_code,
            round_no=round_no,
            issues=issues,
        )

    def _split_qa_issues_by_slide(
        self, issues: list[str]
    ) -> tuple[dict[int, list[str]], list[str]]:
        return split_qa_issues_by_slide(
            issues,
            dedupe_preserve_order=self._dedupe_preserve_order,
        )

    async def _persist_qa_failure_artifacts(
        self, *, run_id: str, mode: GenerationMode
    ) -> dict[str, Any]:
        return await persist_qa_failure_artifacts(
            store=self.store,
            run_id=run_id,
            mode=mode,
            dedupe_preserve_order=self._dedupe_preserve_order,
        )

    def _dedupe_preserve_order(self, issues: list[str]) -> list[str]:
        return dedupe_preserve_order(issues)
