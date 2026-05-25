from __future__ import annotations

from ...models import EventType, GenerationMode, RunStatus
from ..slide_regeneration_reporting import build_regeneration_rule_violations
from ..template_slide_regeneration import regenerate_single_template_slide


class SlideRegenerationTaskMixin:
    async def regenerate_single_slide_task(
        self,
        *,
        run_id: str,
        slide_no: int,
        instruction: str,
        preserve_style: bool,
    ) -> None:
        orch = self.orch
        try:
            run = await orch.store.get_run(run_id)
            if run is None or run.outline is None:
                return
            if self._run_has_pptd_project(run):
                await self.regenerate_single_pptd_slide(
                    run_id=run_id,
                    slide_no=slide_no,
                    instruction=instruction,
                    preserve_style=preserve_style,
                    run=run,
                )
            elif run.input.generation_mode == GenerationMode.TEMPLATE:
                await regenerate_single_template_slide(
                    orchestrator=orch,
                    run_id=run_id,
                    slide_no=slide_no,
                    instruction=instruction,
                    preserve_style=preserve_style,
                    run=run,
                    rule_violations=build_regeneration_rule_violations(
                        instruction=instruction,
                        preserve_style=preserve_style,
                    ),
                )
            else:
                await self.regenerate_single_scratch_slide(
                    run_id=run_id,
                    slide_no=slide_no,
                    instruction=instruction,
                    preserve_style=preserve_style,
                    run=run,
                )
        except Exception as exc:
            await orch.store.update_run(
                run_id, lambda r: setattr(r, "status", RunStatus.SUCCEEDED)
            )
            await orch._publish(
                run_id,
                EventType.SLIDE_FAILED,
                {
                    "slide_no": slide_no,
                    "phase": "slide.regenerate",
                    "reason": orch._exception_reason(exc),
                    "details": {"error_type": type(exc).__name__},
                },
            )
