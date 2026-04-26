from __future__ import annotations

from typing import Any
from uuid import uuid4

from ..models import (
    EventType,
    GenerationMode,
    RunEvent,
    RunRecord,
    RunStatus,
    RunSummaryResponse,
)
from ..infra.store import now_iso
from .runtime_models import RunContext
from .types import RunStageError


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

    async def get_run_detail(self, run_id: str) -> Any:
        return await self.orch.application.get_run_detail(run_id)

    async def confirm_outline(self, run_id: str, req: Any) -> RunSummaryResponse | None:
        return await self.orch.application.confirm_outline(run_id, req)

    async def publish(
        self, run_id: str, event_type: EventType, payload: dict[str, Any]
    ) -> None:
        run = await self.orch.store.get_run(run_id)
        if run is None:
            return
        event = RunEvent(
            seq=len(run.events) + 1, event=event_type, ts=now_iso(), payload=payload
        )
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
            if stage == "COMPILING":
                r.compile_status = "failed"
                r.compile_error_code = error_code
                r.compile_error_details = dict(error_details or {})

        await self.orch.store.update_run(run_id, apply_fail)
        payload: dict[str, Any] = {
            "error_code": error_code,
            "failed_stage": stage,
            "retryable": retryable,
        }
        if error_details:
            payload["error_details"] = error_details
        self.orch._clear_run_llm_budget(run_id)
        await self.publish(run_id, EventType.RUN_FAILED, payload)
        await self.publish(
            run_id,
            EventType.RUN_FINALIZED,
            {
                "final_status": RunStatus.FAILED.value,
                "from_stage": stage,
                "reason": error_code,
            },
        )

    async def finalize_run_success(
        self, run_id: str, *, from_stage: str, reason: str
    ) -> None:
        def apply_success(r: RunRecord) -> None:
            r.status = RunStatus.SUCCEEDED
            r.error_code = None
            r.failed_stage = None
            r.retryable = False
            r.error_details = {}
            if r.compile_status != "failed":
                r.compile_error_code = None
                r.compile_error_details = {}

        await self.orch.store.update_run(run_id, apply_success)
        self.orch._clear_run_llm_budget(run_id)
        await self.publish(
            run_id,
            EventType.RUN_FINALIZED,
            {
                "final_status": RunStatus.SUCCEEDED.value,
                "from_stage": from_stage,
                "reason": reason,
            },
        )

    async def start_outline(self, run_id: str) -> None:
        ctx = await RunContext.load(store=self.orch.store, run_id=run_id)
        if ctx is None:
            return
        await self._outline_stage.execute(ctx)

    async def execute_generation_pipeline(self, run_id: str) -> None:
        ctx = await RunContext.load(store=self.orch.store, run_id=run_id)
        if ctx is None or ctx.run.outline is None:
            await self.fail_run(
                run_id, "SLIDES_GENERATING", "OUTLINE_MISSING", retryable=False
            )
            return
        try:
            if ctx.run.input.generation_mode == GenerationMode.TEMPLATE:
                await self._template_stage.execute(ctx)
            else:
                await self._scratch_stage.execute(ctx)
        except RunStageError as exc:
            await self.fail_run(
                run_id,
                exc.stage,
                exc.error_code,
                retryable=exc.retryable,
                error_details=exc.details,
            )
        except Exception:
            await self.fail_run(
                run_id, "SLIDES_GENERATING", "GENERATION_PIPELINE_ERROR", retryable=True
            )
