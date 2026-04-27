from __future__ import annotations

from ...models import RunRecord


class RunSlideSceneApiMixin:
    async def _recompile_run_after_scene_save(
        self, *, run: RunRecord
    ) -> dict[str, object]:
        return await self.slide_regeneration_service.recompile_run_after_scene_save(run=run)

    async def _regenerate_single_slide_task(
        self,
        *,
        run_id: str,
        slide_no: int,
        instruction: str,
        preserve_style: bool,
    ) -> None:
        return await self.slide_regeneration_service.regenerate_single_slide_task(
            run_id=run_id,
            slide_no=slide_no,
            instruction=instruction,
            preserve_style=preserve_style,
        )

    async def _publish_slide_generated_preview(
        self,
        *,
        run_id: str,
        slide_no: int,
        status: str,
        preview: dict[str, object],
    ) -> None:
        return await self.slide_regeneration_service.publish_slide_generated_preview(
            run_id=run_id,
            slide_no=slide_no,
            status=status,
            preview=preview,
        )
