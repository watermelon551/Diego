from __future__ import annotations

from pathlib import Path
from typing import Any

from ..design.skill_profile import enforce_layout_variety
from ..infra.store import now_iso
from ..models import (
    CompileBundleResult,
    CompileResult,
    ConfirmOutlineRequest,
    EventType,
    GenerationResult,
    OutlineHistoryEntry,
    RunDetailResponse,
    RunRecord,
    RunStatus,
    RunSummaryResponse,
)


class RunApplicationService:
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator

    async def create_run(self, req: Any) -> RunSummaryResponse:
        return await self.orch._kernel.create_run(req)

    async def get_run_detail(self, run_id: str) -> RunDetailResponse | None:
        run = await self.orch.store.get_run(run_id)
        if run is None or getattr(run.input, "capability", "ppt") != "ppt":
            return None
        generation_mode_raw = getattr(getattr(run, "input", None), "generation_mode", None)
        generation_mode = str(
            getattr(generation_mode_raw, "value", generation_mode_raw) or ""
        )
        pptx_path = str(run.pptx_path or "").strip()
        pptx_ready = bool(pptx_path and Path(pptx_path).exists() and Path(pptx_path).is_file())
        artifacts: dict[str, Any] = {}
        if pptx_path:
            artifacts["pptx"] = {"path": pptx_path, "downloadable": pptx_ready}
        compile_bundle_ready = bool(
            generation_mode == "scratch"
            and (
                getattr(run, "compile_bundle_ready", False)
                or str(run.compile_js_path or "").strip()
            )
        )
        if compile_bundle_ready:
            artifacts["compile_bundle"] = {
                "available": True,
                "entrypoint": "slides/compile.js",
                "provider": "diego",
                "mode": generation_mode,
                "build_endpoint": f"/v1/ppt/runs/{run.run_id}/artifacts/compile-bundle",
            }
        generation_result = GenerationResult(
            mode=run.input.generation_mode,
            artifact_dir=str(run.artifact_dir or ""),
            outline_ready=run.outline is not None,
            slide_count=len(run.slides),
            slide_artifacts_ready=bool(run.slides),
            citation_map_ready=bool(run.citation_map),
            compile_bundle_ready=compile_bundle_ready,
            compile_bundle_entrypoint="slides/compile.js" if compile_bundle_ready else None,
        )
        compile_bundle = CompileBundleResult(
            status="ready" if compile_bundle_ready else "not_available",
            provider="diego",
            available=compile_bundle_ready,
            entrypoint="slides/compile.js" if compile_bundle_ready else None,
            build_endpoint=(
                f"/v1/ppt/runs/{run.run_id}/artifacts/compile-bundle"
                if compile_bundle_ready
                else None
            ),
            mode=generation_mode if compile_bundle_ready else None,
        )
        compile_result_status = str(
            getattr(run, "compile_status", "not_requested") or "not_requested"
        )
        compile_requested_provider = getattr(run, "compile_requested_provider", None)
        compile_provider = run.compile_provider
        compile_artifact_path = run.pptx_path
        compile_artifact_ready = pptx_ready
        if generation_mode == "template":
            compile_result_status = "not_requested"
            compile_requested_provider = None
            compile_provider = None
            compile_artifact_path = None
            compile_artifact_ready = False
        compile_result = CompileResult(
            status=compile_result_status,
            requested_provider=compile_requested_provider,
            provider=compile_provider,
            bundle_ready=compile_bundle_ready,
            artifact_path=compile_artifact_path,
            artifact_ready=compile_artifact_ready,
            fallback_used=bool(run.compile_fallback_used),
            fallback_from=(
                run.compile_error_details.get("fallback_from")
                if isinstance(getattr(run, "compile_error_details", {}), dict)
                else None
            ),
            error_code=getattr(run, "compile_error_code", None),
            error_details=(
                dict(getattr(run, "compile_error_details", {}) or {})
                if isinstance(getattr(run, "compile_error_details", {}), dict)
                else {}
            ),
        )
        return RunDetailResponse(
            run_id=run.run_id,
            trace_id=run.trace_id,
            status=run.status,
            pptx_ready=pptx_ready,
            artifacts=artifacts,
            outline=run.outline,
            outline_history=run.outline_history,
            slides=run.slides,
            citation_map=run.citation_map,
            stage_timings=run.stage_timings,
            render_version=run.render_version,
            error_code=run.error_code,
            failed_stage=run.failed_stage,
            retryable=run.retryable,
            error_details=run.error_details,
            generation_result=generation_result,
            compile_bundle=compile_bundle,
            compile_result=compile_result,
            compile_js_path=run.compile_js_path,
            pptx_path=run.pptx_path,
            compile_requested_provider=getattr(run, "compile_requested_provider", None),
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
        if run is None or getattr(run.input, "capability", "ppt") != "ppt":
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

        def apply_confirm(record: RunRecord) -> None:
            current_version = record.outline.version if record.outline is not None else None
            if req.outline is not None:
                record.outline = req.outline
            record.status = RunStatus.SLIDES_GENERATING if req.approved else RunStatus.AWAITING_OUTLINE_CONFIRM
            new_version = record.outline.version if record.outline is not None else None
            action = "confirmed" if req.approved else ("updated" if req.outline is not None else "rejected")
            record.outline_history.append(
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
            await self.orch._publish(
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
            self.orch._spawn(self.orch._kernel.execute_generation_pipeline(run_id))
        updated = await self.orch.store.get_run(run_id)
        assert updated is not None
        return RunSummaryResponse(run_id=updated.run_id, trace_id=updated.trace_id, status=updated.status)

    async def build_compile_bundle(self, run_id: str) -> dict[str, Any]:
        return await self.orch.compile_engine.build_compile_bundle(run_id)

    async def get_run_record(self, run_id: str) -> RunRecord | None:
        return await self.orch.store.get_run(run_id)

    async def wait_for_event(self, run_id: str, cursor: int, timeout: float = 5.0) -> RunRecord:
        return await self.orch.store.wait_for_event(run_id, cursor, timeout=timeout)

    async def recover_interrupted_runs(self) -> dict[str, int]:
        interrupted_statuses = {
            RunStatus.PLANNING,
            RunStatus.DRAFTING,
            RunStatus.OUTLINE_DRAFTING,
            RunStatus.SLIDES_GENERATING,
            RunStatus.COMPILING,
        }
        runs = await self.orch.store.list_runs()
        recovered = 0
        for run in runs:
            if run.status not in interrupted_statuses:
                continue
            recovered += 1
            await self.orch._kernel.fail_run(
                run.run_id,
                run.status.value,
                "RUN_INTERRUPTED_BY_RESTART",
                retryable=True,
                error_details={
                    "reason": "service_restarted",
                    "previous_status": run.status.value,
                },
            )
        return {"scanned": len(runs), "recovered": recovered}
