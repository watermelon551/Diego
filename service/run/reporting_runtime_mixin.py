from __future__ import annotations

from typing import Any

from .run_reporting_runtime import (
    append_artifact_cleanup_entry,
    append_candidate_selection_entry,
    append_chart_truth_report,
    append_quality_entry,
    append_quality_gate_entry,
    append_repair_history,
    fail_run,
    normalize_citations,
)


class RunReportingRuntimeMixin:
    async def _append_chart_truth_report(
        self, *, run_id: str, entry: dict[str, Any]
    ) -> None:
        await append_chart_truth_report(self, run_id=run_id, entry=entry)

    async def _append_quality_entry(
        self, *, run_id: str, entry: dict[str, Any]
    ) -> None:
        await append_quality_entry(self, run_id=run_id, entry=entry)

    async def _append_quality_gate_entry(
        self, *, run_id: str, entry: dict[str, Any]
    ) -> None:
        await append_quality_gate_entry(self, run_id=run_id, entry=entry)

    async def _append_candidate_selection_entry(
        self, *, run_id: str, entry: dict[str, Any]
    ) -> None:
        await append_candidate_selection_entry(self, run_id=run_id, entry=entry)

    async def _append_artifact_cleanup_entry(
        self, *, run_id: str, entry: dict[str, Any]
    ) -> None:
        await append_artifact_cleanup_entry(self, run_id=run_id, entry=entry)

    async def _append_repair_history(
        self, *, run_id: str, entry: dict[str, Any]
    ) -> None:
        await append_repair_history(self, run_id=run_id, entry=entry)

    async def _fail_run(
        self,
        run_id: str,
        stage: str,
        error_code: str,
        retryable: bool,
        error_details: dict[str, Any] | None = None,
    ) -> None:
        await fail_run(
            self,
            run_id,
            stage,
            error_code,
            retryable,
            error_details=error_details,
        )

    def _normalize_citations(
        self, citations: list[str], rag_source_ids: list[str], slide_no: int
    ) -> list[str]:
        return normalize_citations(citations, rag_source_ids, slide_no)
