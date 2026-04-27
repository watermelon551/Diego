from __future__ import annotations

from typing import Any

from ..models import RunStatus, RunSummaryResponse


class SlideRegenerationApplicationMixin:
    async def regenerate_single_slide(
        self,
        *,
        run_id: str,
        slide_no: int,
        instruction: str,
        preserve_style: bool,
        expected_render_version: int | None = None,
    ) -> RunSummaryResponse | None:
        if slide_no < 1:
            raise ValueError("slide_no must be >= 1")
        run = await self.orch.store.get_run(run_id)
        if run is None:
            return None
        if run.status != RunStatus.SUCCEEDED:
            raise ValueError("run must be in SUCCEEDED state")
        if expected_render_version is not None and run.render_version != expected_render_version:
            raise ValueError(
                "render version conflict: "
                f"expected {expected_render_version}, current {run.render_version}"
            )
        if run.outline is None:
            raise ValueError("run outline missing")
        if slide_no > len(run.outline.nodes):
            raise ValueError("slide_no out of range")
        if not any(
            int(getattr(item, "slide_no", 0) or 0) == slide_no for item in run.slides
        ):
            raise ValueError("slide artifact missing")

        await self.orch.store.update_run(
            run_id,
            lambda r: setattr(r, "status", RunStatus.SLIDES_GENERATING),
        )
        self.orch._spawn(
            self._regenerate_single_slide_task(
                run_id=run_id,
                slide_no=slide_no,
                instruction=instruction.strip(),
                preserve_style=preserve_style,
            )
        )
        return RunSummaryResponse(
            run_id=run.run_id,
            trace_id=run.trace_id,
            status=RunStatus.SLIDES_GENERATING,
        )

    async def _regenerate_single_slide_task(
        self,
        *,
        run_id: str,
        slide_no: int,
        instruction: str,
        preserve_style: bool,
    ) -> None:
        return await self.orch._regenerate_single_slide_task(
            run_id=run_id,
            slide_no=slide_no,
            instruction=instruction,
            preserve_style=preserve_style,
        )

