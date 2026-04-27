from __future__ import annotations

from pathlib import Path

from ...models import (
    ConfirmOutlineRequest,
    CreateRunRequest,
    EditableSlideScene,
    RunDetailResponse,
    RunSummaryResponse,
    SaveSlideSceneRequest,
    SaveSlideSceneResponse,
    TemplateDetailResponse,
    TemplateUploadResponse,
)


class RunApplicationApiMixin:
    async def recover_interrupted_runs(self) -> dict[str, int]:
        return await self.application.recover_interrupted_runs()

    async def upload_template(
        self, *, filename: str, content: bytes
    ) -> TemplateUploadResponse:
        return await self.application.upload_template(filename=filename, content=content)

    async def get_template_detail(
        self, template_id: str
    ) -> TemplateDetailResponse | None:
        return await self.application.get_template_detail(template_id)

    async def create_run(self, req: CreateRunRequest) -> RunSummaryResponse:
        return await self.application.create_run(req)

    async def get_run_detail(self, run_id: str) -> RunDetailResponse | None:
        return await self.application.get_run_detail(run_id)

    async def build_compile_bundle(self, run_id: str) -> dict[str, object]:
        return await self.application.build_compile_bundle(run_id)

    async def get_slide_preview(
        self, run_id: str, slide_no: int
    ) -> dict[str, object] | None:
        return await self.application.get_slide_preview(run_id, slide_no)

    async def get_slide_scene(
        self, run_id: str, slide_no: int
    ) -> EditableSlideScene | None:
        return await self.application.get_slide_scene(run_id, slide_no)

    async def get_slide_asset_path(
        self, run_id: str, slide_no: int, asset_path: str
    ) -> Path | None:
        return await self.application.get_slide_asset_path(run_id, slide_no, asset_path)

    async def save_slide_scene(
        self,
        *,
        run_id: str,
        slide_no: int,
        req: SaveSlideSceneRequest,
    ) -> SaveSlideSceneResponse | None:
        return await self.application.save_slide_scene(
            run_id=run_id,
            slide_no=slide_no,
            req=req,
        )

    async def regenerate_single_slide(
        self,
        *,
        run_id: str,
        slide_no: int,
        instruction: str,
        preserve_style: bool,
        expected_render_version: int | None = None,
    ) -> RunSummaryResponse | None:
        return await self.application.regenerate_single_slide(
            run_id=run_id,
            slide_no=slide_no,
            instruction=instruction,
            preserve_style=preserve_style,
            expected_render_version=expected_render_version,
        )

    async def confirm_outline(
        self, run_id: str, req: ConfirmOutlineRequest
    ) -> RunSummaryResponse | None:
        return await self.application.confirm_outline(run_id, req)
