from __future__ import annotations

from typing import Any


async def append_chart_truth_report(orch: Any, *, run_id: str, entry: dict[str, Any]) -> None:
    await orch.reporting_engine.append_chart_truth_report(run_id=run_id, entry=entry)


async def append_quality_entry(orch: Any, *, run_id: str, entry: dict[str, Any]) -> None:
    await orch.reporting_engine.append_quality_entry(run_id=run_id, entry=entry)


async def append_quality_gate_entry(orch: Any, *, run_id: str, entry: dict[str, Any]) -> None:
    await orch.reporting_engine.append_quality_gate_entry(run_id=run_id, entry=entry)


async def append_candidate_selection_entry(orch: Any, *, run_id: str, entry: dict[str, Any]) -> None:
    await orch.reporting_engine.append_candidate_selection_entry(run_id=run_id, entry=entry)


async def append_artifact_cleanup_entry(orch: Any, *, run_id: str, entry: dict[str, Any]) -> None:
    await orch.reporting_engine.append_artifact_cleanup_entry(run_id=run_id, entry=entry)


async def append_repair_history(orch: Any, *, run_id: str, entry: dict[str, Any]) -> None:
    await orch.reporting_engine.append_repair_history(run_id=run_id, entry=entry)


async def fail_run(
    orch: Any,
    run_id: str,
    stage: str,
    error_code: str,
    retryable: bool,
    error_details: dict[str, Any] | None = None,
) -> None:
    await orch._kernel.fail_run(
        run_id,
        stage,
        error_code,
        retryable,
        error_details=error_details,
    )


def normalize_citations(citations: list[str], rag_source_ids: list[str], slide_no: int) -> list[str]:
    normalized = [item for item in citations if item]
    if normalized:
        return list(dict.fromkeys(normalized))
    if not rag_source_ids:
        return []
    first = rag_source_ids[(slide_no - 1) % len(rag_source_ids)]
    second = rag_source_ids[slide_no % len(rag_source_ids)] if len(rag_source_ids) > 1 else first
    return list(dict.fromkeys([first, second]))
