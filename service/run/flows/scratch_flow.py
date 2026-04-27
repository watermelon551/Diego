from __future__ import annotations

from typing import Any

from ...models import VisualPolicy
from .scratch_compile_mixin import ScratchCompileMixin
from .scratch_slide_batch_mixin import ScratchSlideBatchMixin


class ScratchFlowService(ScratchSlideBatchMixin, ScratchCompileMixin):
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator

    async def execute(self, run_id: str) -> None:
        orch = self.orch
        run = await orch.store.get_run(run_id)
        assert run is not None and run.outline is not None
        orch._init_run_llm_budget(
            run_id=run_id, target_slide_count=run.input.target_slide_count
        )
        if (
            run.input.visual_policy == VisualPolicy.MEDIA_REQUIRED
            and orch.settings.asset_provider == "none"
        ):
            await orch._fail_run(
                run_id,
                "SLIDES_GENERATING",
                "VISUAL_POLICY_UNSATISFIED",
                retryable=False,
            )
            return
        effective_template_style = orch._resolved_template_style(run)
        design = orch._resolve_design_profile(
            topic=run.input.topic,
            template_style=effective_template_style,
            requirements_report=(
                run.research_report if isinstance(run.research_report, dict) else {}
            ),
        )
        failures = await self._generate_slide_batch(
            run_id=run_id,
            run=run,
            design=design,
        )
        if failures and failures[0]["details"].get("error_type") == "VisualPolicyUnsatisfiedError":
            await orch._fail_run(
                run_id,
                "SLIDES_GENERATING",
                "VISUAL_POLICY_UNSATISFIED",
                retryable=False,
            )
            return
        if failures:
            await orch._fail_run(
                run_id,
                "SLIDES_GENERATING",
                "SLIDE_LLM_ERROR",
                retryable=True,
                error_details={
                    "failure_count": len(failures),
                    "first_failure": failures[0],
                    "failures": failures[:8],
                },
            )
            return

        requested_provider = await self._mark_compile_started(run_id=run_id)
        run = await orch.store.get_run(run_id)
        assert run is not None
        await self._compile_scratch_run(
            run_id=run_id,
            run=run,
            design=design,
            requested_provider=requested_provider,
        )
