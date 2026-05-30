from __future__ import annotations

from typing import Any
from uuid import uuid4

from ..models import (
    ItemGenerationRunRequest,
    LongFormRunDetailResponse,
    LongFormRunRequest,
    RunRecord,
    RunStatus,
    RunSummaryResponse,
    StructureExpansionRunRequest,
)


class ContentRunLifecycleMixin:
    orch: Any

    async def create_run(
        self,
        req: LongFormRunRequest | StructureExpansionRunRequest | ItemGenerationRunRequest,
    ) -> RunSummaryResponse:
        run_id = str(uuid4())
        trace_id = str(uuid4())
        artifact_dir = self.orch.artifacts_base / run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        run = RunRecord(
            run_id=run_id,
            trace_id=trace_id,
            status=RunStatus.PLANNING,
            input=req,
            artifact_dir=str(artifact_dir),
        )
        await self.orch.store.add_run(run)
        content_kind = str(getattr(req, "content_kind", "longform_draft") or "longform_draft")
        if content_kind == "structure_expansion":
            self.orch._spawn(self.generate_structure_expansion(run_id), run_id=run_id)
        elif content_kind == "item_generation":
            self.orch._spawn(self.generate_item_generation(run_id), run_id=run_id)
        else:
            self.orch._spawn(self.start_plan(run_id), run_id=run_id)
        return RunSummaryResponse(run_id=run_id, trace_id=trace_id, status=run.status)

    async def get_run_detail(self, run_id: str) -> LongFormRunDetailResponse | None:
        run = await self.orch.store.get_run(run_id)
        if run is None or getattr(run.input, "capability", "") != "content":
            return None
        return LongFormRunDetailResponse(
            run_id=run.run_id,
            trace_id=run.trace_id,
            status=run.status,
            content_kind=str(getattr(run.input, "content_kind", "longform_draft") or "longform_draft"),
            plan=run.longform_plan,
            plan_history=run.longform_plan_history,
            draft=run.longform_draft,
            structure_expansion=run.structure_expansion_result,
            item_generation=run.item_generation_result,
            stage_timings=run.longform_stage_timings,
            error_code=run.error_code,
            failed_stage=run.failed_stage,
            retryable=run.retryable,
            error_details=run.error_details,
            research_report=run.research_report,
            events=run.events,
        )
