from __future__ import annotations

from typing import Any
from uuid import uuid4

from ..design.skill_profile import enforce_layout_variety
from ..models import (
    ConfirmOutlineRequest,
    EventType,
    GenerationMode,
    OutlineHistoryEntry,
    RunDetailResponse,
    RunEvent,
    RunRecord,
    RunStatus,
    RunSummaryResponse,
)
from ..infra.store import now_iso
from .runtime_models import RunContext


class RunKernel:
    def __init__(
        self,
        *,
        orchestrator: Any,
        outline_stage: Any,
        scratch_stage: Any,
        template_stage: Any,
    ) -> None:
        self.orch = orchestrator
        self._outline_stage = outline_stage
        self._scratch_stage = scratch_stage
        self._template_stage = template_stage

    async def create_run(self, req: Any) -> RunSummaryResponse:
        run_id = str(uuid4())
        trace_id = str(uuid4())
        artifact_dir = self.orch.artifacts_base / run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        run = RunRecord(
            run_id=run_id,
            trace_id=trace_id,
            status=RunStatus.OUTLINE_DRAFTING,
            input=req,
            artifact_dir=str(artifact_dir),
        )
        await self.orch.store.add_run(run)
        self.orch._spawn(self.start_outline(run_id))
        return RunSummaryResponse(run_id=run_id, trace_id=trace_id, status=run.status)

    async def get_run_detail(self, run_id: str) -> RunDetailResponse | None:
        run = await self.orch.store.get_run(run_id)
        if run is None:
            return None
        return RunDetailResponse(
            run_id=run.run_id,
            trace_id=run.trace_id,
            status=run.status,
            outline=run.outline,
            outline_history=run.outline_history,
            slides=run.slides,
            citation_map=run.citation_map,
            stage_timings=run.stage_timings,
            error_code=run.error_code,
            failed_stage=run.failed_stage,
            retryable=run.retryable,
            error_details=run.error_details,
            compile_js_path=run.compile_js_path,
            pptx_path=run.pptx_path,
            compile_provider=run.compile_provider,
            compile_fallback_used=run.compile_fallback_used,
            qa_report=run.qa_report,
            template_mapping_report=run.template_mapping_report,
            chart_truth_report=run.chart_truth_report,
            repair_history=run.repair_history,
            quality_report=run.quality_report,
            quality_gate_report=run.quality_gate_report,
            research_report=run.research_report,
            candidate_selection_report=run.candidate_selection_report,
            template_layout_report=run.template_layout_report,
            artifact_cleanup_report=run.artifact_cleanup_report,
            events=run.events,
        )

    async def confirm_outline(self, run_id: str, req: ConfirmOutlineRequest) -> RunSummaryResponse | None:
        run = await self.orch.store.get_run(run_id)
        if run is None:
            return None
        if run.status != RunStatus.AWAITING_OUTLINE_CONFIRM:
            raise ValueError("run is not awaiting outline confirmation")
        if run.outline is None:
            raise ValueError("run outline is missing")
        if req.outline is not None:
            if req.base_version != run.outline.version:
                raise ValueError(
                    f"base_version mismatch: expected {run.outline.version}, got {req.base_version}"
                )
            enforce_layout_variety(
                nodes=req.outline.nodes,
                seed=f"{run.input.topic}|{self.orch._resolved_template_style(run)}|{run_id}|confirm",
                style_dna_id=self.orch._resolved_style_dna_id(run),
            )
            if req.outline.version <= run.outline.version:
                req.outline.version = run.outline.version + 1

        def apply_confirm(r: RunRecord) -> None:
            current_version = r.outline.version if r.outline is not None else None
            if req.outline is not None:
                r.outline = req.outline
            r.status = RunStatus.SLIDES_GENERATING if req.approved else RunStatus.AWAITING_OUTLINE_CONFIRM
            new_version = r.outline.version if r.outline is not None else None
            action = "confirmed" if req.approved else ("updated" if req.outline is not None else "rejected")
            r.outline_history.append(
                OutlineHistoryEntry(
                    action=action,
                    approved=req.approved,
                    base_version=current_version,
                    new_version=new_version,
                    change_reason=req.change_reason,
                    at=now_iso(),
                )
            )

        await self.orch.store.update_run(run_id, apply_confirm)
        if req.outline is not None:
            await self.publish(
                run_id,
                EventType.OUTLINE_UPDATED,
                {
                    "approved": req.approved,
                    "base_version": req.base_version,
                    "new_version": req.outline.version,
                    "change_reason": req.change_reason,
                },
            )
        if req.approved:
            self.orch._spawn(self.execute_generation_pipeline(run_id))
        updated = await self.orch.store.get_run(run_id)
        assert updated is not None
        return RunSummaryResponse(run_id=updated.run_id, trace_id=updated.trace_id, status=updated.status)

    async def publish(self, run_id: str, event_type: EventType, payload: dict[str, Any]) -> None:
        run = await self.orch.store.get_run(run_id)
        if run is None:
            return
        event = RunEvent(seq=len(run.events) + 1, event=event_type, ts=now_iso(), payload=payload)
        await self.orch.store.append_event(run_id, event)

    async def fail_run(
        self,
        run_id: str,
        stage: str,
        error_code: str,
        retryable: bool,
        error_details: dict[str, Any] | None = None,
    ) -> None:
        def apply_fail(r: RunRecord) -> None:
            r.status = RunStatus.FAILED
            r.error_code = error_code
            r.failed_stage = stage
            r.retryable = retryable
            r.error_details = dict(error_details or {})

        await self.orch.store.update_run(run_id, apply_fail)
        payload: dict[str, Any] = {"error_code": error_code, "failed_stage": stage, "retryable": retryable}
        if error_details:
            payload["error_details"] = error_details
        self.orch._clear_run_llm_budget(run_id)
        await self.publish(run_id, EventType.RUN_FAILED, payload)
        await self.publish(
            run_id,
            EventType.RUN_FINALIZED,
            {"final_status": RunStatus.FAILED.value, "from_stage": stage, "reason": error_code},
        )

    async def finalize_run_success(self, run_id: str, *, from_stage: str, reason: str) -> None:
        def apply_success(r: RunRecord) -> None:
            r.status = RunStatus.SUCCEEDED
            r.error_code = None
            r.failed_stage = None
            r.retryable = False
            r.error_details = {}

        await self.orch.store.update_run(run_id, apply_success)
        self.orch._clear_run_llm_budget(run_id)
        await self.publish(
            run_id,
            EventType.RUN_FINALIZED,
            {"final_status": RunStatus.SUCCEEDED.value, "from_stage": from_stage, "reason": reason},
        )

    async def start_outline(self, run_id: str) -> None:
        ctx = await RunContext.load(store=self.orch.store, run_id=run_id)
        if ctx is None:
            return
        await self._outline_stage.execute(ctx)

    async def execute_generation_pipeline(self, run_id: str) -> None:
        ctx = await RunContext.load(store=self.orch.store, run_id=run_id)
        if ctx is None or ctx.run.outline is None:
            await self.fail_run(run_id, "SLIDES_GENERATING", "OUTLINE_MISSING", retryable=False)
            return
        try:
            if ctx.run.input.generation_mode == GenerationMode.TEMPLATE:
                await self._template_stage.execute(ctx)
            else:
                await self._scratch_stage.execute(ctx)
        except Exception:
            await self.fail_run(run_id, "SLIDES_GENERATING", "GENERATION_PIPELINE_ERROR", retryable=True)
