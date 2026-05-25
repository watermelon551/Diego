from __future__ import annotations

from typing import Any

from ...models import RunRecord
from ..scene_recompile import recompile_run_after_scene_save
from .slide_regeneration_pptd_mixin import SlideRegenerationPptdMixin
from .slide_regeneration_compile_mixin import SlideRegenerationCompileMixin
from .slide_regeneration_preview_mixin import SlideRegenerationPreviewMixin
from .slide_regeneration_scratch_mixin import SlideRegenerationScratchMixin
from .slide_regeneration_task_mixin import SlideRegenerationTaskMixin


class SlideRegenerationService(
    SlideRegenerationTaskMixin,
    SlideRegenerationPptdMixin,
    SlideRegenerationPreviewMixin,
    SlideRegenerationScratchMixin,
    SlideRegenerationCompileMixin,
):
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator

    async def recompile_run_after_scene_save(self, *, run: RunRecord) -> Any:
        return await recompile_run_after_scene_save(orchestrator=self.orch, run=run)

    async def regenerate_single_slide_task(
        self,
        *,
        run_id: str,
        slide_no: int,
        instruction: str,
        preserve_style: bool,
    ) -> None:
        return await SlideRegenerationTaskMixin.regenerate_single_slide_task(
            self,
            run_id=run_id,
            slide_no=slide_no,
            instruction=instruction,
            preserve_style=preserve_style,
        )

    async def publish_slide_generated_preview(
        self,
        *,
        run_id: str,
        slide_no: int,
        status: str,
        preview: dict[str, Any],
    ) -> None:
        return await SlideRegenerationPreviewMixin.publish_slide_generated_preview(
            self,
            run_id=run_id,
            slide_no=slide_no,
            status=status,
            preview=preview,
        )
