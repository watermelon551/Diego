from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..design.skill_profile import DesignProfile
from ..models import EventType, GenerationMode
from .runtime_models import RunContext


class OutlineStage:
    def __init__(self, flow: Any) -> None:
        self._flow = flow

    async def execute(self, ctx: RunContext) -> None:
        await self._flow.execute(ctx.run_id)


class ScratchGenerationStage:
    def __init__(self, flow: Any) -> None:
        self._flow = flow

    async def execute(self, ctx: RunContext) -> None:
        await self._flow.execute(ctx.run_id)


class TemplateGenerationStage:
    def __init__(self, flow: Any) -> None:
        self._flow = flow

    async def execute(self, ctx: RunContext) -> None:
        await self._flow.execute(ctx.run_id)


class FinalizeQualityStage:
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator

    async def execute(
        self,
        *,
        run_id: str,
        mode: GenerationMode,
        design: DesignProfile,
        from_stage: str,
        success_reason: str,
    ) -> bool:
        qa_timeout_sec = max(1.0, float(self.orch.settings.qa_finalize_timeout_sec))
        try:
            post_compile_ok = await asyncio.wait_for(
                self.orch.quality_engine.complete_post_compile_quality(
                    run_id=run_id,
                    mode=mode,
                    design=design,
                ),
                timeout=qa_timeout_sec,
            )
        except asyncio.TimeoutError:
            run = await self.orch.store.get_run(run_id)
            pptx_path = Path(str(getattr(run, "pptx_path", "") or "").strip())
            if str(pptx_path) and pptx_path.exists() and pptx_path.is_file():
                def apply_degraded_qa(record) -> None:
                    previous = (
                        record.qa_report
                        if isinstance(getattr(record, "qa_report", None), dict)
                        else {}
                    )
                    record.qa_report = {
                        **previous,
                        "passed": True,
                        "degraded": True,
                        "degraded_reason": "FINALIZE_TIMEOUT",
                        "finalize_timeout_sec": int(qa_timeout_sec),
                        "mode": mode.value,
                    }

                await self.orch.store.update_run(run_id, apply_degraded_qa)
                await self.orch._publish(
                    run_id,
                    EventType.QA_COMPLETED,
                    {
                        "passed": True,
                        "degraded": True,
                        "degraded_reason": "FINALIZE_TIMEOUT",
                        "finalize_timeout_sec": int(qa_timeout_sec),
                        "mode": mode.value,
                    },
                )
                await self.orch._finalize_run_success(
                    run_id,
                    from_stage=from_stage,
                    reason=f"{success_reason}; finalize_qa_timeout_degraded",
                )
                return True
            await self.orch._fail_run(
                run_id,
                from_stage,
                "FINALIZE_TIMEOUT",
                retryable=True,
                error_details={"reason": f"post-compile QA exceeded {qa_timeout_sec:.0f}s", "mode": mode.value},
            )
            return False
        if not post_compile_ok:
            return False
        await self.orch._finalize_run_success(run_id, from_stage=from_stage, reason=success_reason)
        return True
