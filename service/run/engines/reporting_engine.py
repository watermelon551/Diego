from __future__ import annotations

from typing import Any

from ..services.reporting_service import ReportingService


class ReportingEngine:
    def __init__(self, runtime: Any) -> None:
        self._service = ReportingService(runtime)

    async def append_chart_truth_report(self, *, run_id: str, entry: dict[str, Any]) -> None:
        await self._service.append_chart_truth_report(run_id=run_id, entry=entry)

    async def append_quality_entry(self, *, run_id: str, entry: dict[str, Any]) -> None:
        await self._service.append_quality_entry(run_id=run_id, entry=entry)

    async def append_quality_gate_entry(self, *, run_id: str, entry: dict[str, Any]) -> None:
        await self._service.append_quality_gate_entry(run_id=run_id, entry=entry)

    async def append_candidate_selection_entry(self, *, run_id: str, entry: dict[str, Any]) -> None:
        await self._service.append_candidate_selection_entry(run_id=run_id, entry=entry)

    async def append_artifact_cleanup_entry(self, *, run_id: str, entry: dict[str, Any]) -> None:
        await self._service.append_artifact_cleanup_entry(run_id=run_id, entry=entry)

    async def append_repair_history(self, *, run_id: str, entry: dict[str, Any]) -> None:
        await self._service.append_repair_history(run_id=run_id, entry=entry)
