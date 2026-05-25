from __future__ import annotations

from typing import Any

from ...models import EventType, SlideArtifact, VisualPolicy
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
        if str(getattr(orch.settings, "compile_provider", "") or "").lower() == "pptd":
            await self._materialize_pptd_outline_slides(run_id=run_id, run=run)
            requested_provider = await self._mark_compile_started(run_id=run_id)
            run = await orch.store.get_run(run_id)
            assert run is not None
            await self._compile_scratch_run(
                run_id=run_id,
                run=run,
                design=design,
                requested_provider=requested_provider,
            )
            return
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
            error_type = str(failures[0].get("details", {}).get("error_type") or "")
            await orch._fail_run(
                run_id,
                "SLIDES_GENERATING",
                "SLIDE_GENERATION_TIMEOUT" if error_type == "SlideGenerationTimeout" else "SLIDE_LLM_ERROR",
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

    async def _materialize_pptd_outline_slides(self, *, run_id: str, run: Any) -> None:
        orch = self.orch
        outline_nodes = list(getattr(getattr(run, "outline", None), "nodes", []) or [])

        def apply_outline_slides(record: Any) -> None:
            existing_by_no = {
                int(getattr(slide, "slide_no", 0) or 0): slide
                for slide in list(getattr(record, "slides", []) or [])
            }
            record.slides = [
                existing_by_no.get(index)
                or SlideArtifact(
                    slide_no=index,
                    js_path=None,
                    js_code="",
                    status="pptd_outline_ready",
                    citations=[],
                )
                for index, _node in enumerate(outline_nodes, start=1)
            ]

        await orch.store.update_run(run_id, apply_outline_slides)
        for index, node in enumerate(outline_nodes, start=1):
            await orch._publish(
                run_id,
                EventType.SLIDE_GENERATED,
                {
                    "slide_no": index,
                    "status": "pptd_outline_ready",
                    "page_type": getattr(getattr(node, "page_type", None), "value", None),
                    "preview_format": "pptd",
                    "is_final": False,
                },
            )
