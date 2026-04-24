from __future__ import annotations

from typing import Any

from .runs import RunApplicationService
from .slides import SlideApplicationService
from .templates import TemplateApplicationService


class DiegoApplication:
    def __init__(self, orchestrator: Any) -> None:
        self.runs = RunApplicationService(orchestrator)
        self.slides = SlideApplicationService(orchestrator)
        self.templates = TemplateApplicationService(orchestrator)

    async def recover_interrupted_runs(self) -> dict[str, int]:
        return await self.runs.recover_interrupted_runs()

    async def create_run(self, req: Any):
        return await self.runs.create_run(req)

    async def get_run_detail(self, run_id: str):
        return await self.runs.get_run_detail(run_id)

    async def get_run_record(self, run_id: str):
        return await self.runs.get_run_record(run_id)

    async def wait_for_event(self, run_id: str, cursor: int, timeout: float = 5.0):
        return await self.runs.wait_for_event(run_id, cursor, timeout=timeout)

    async def confirm_outline(self, run_id: str, req: Any):
        return await self.runs.confirm_outline(run_id, req)

    async def build_compile_bundle(self, run_id: str):
        return await self.runs.build_compile_bundle(run_id)

    async def upload_template(self, *, filename: str, content: bytes):
        return await self.templates.upload_template(filename=filename, content=content)

    async def get_template_detail(self, template_id: str):
        return await self.templates.get_template_detail(template_id)

    async def get_slide_preview(self, run_id: str, slide_no: int):
        return await self.slides.get_slide_preview(run_id, slide_no)

    async def get_slide_scene(self, run_id: str, slide_no: int):
        return await self.slides.get_slide_scene(run_id, slide_no)

    async def get_slide_asset_path(self, run_id: str, slide_no: int, asset_path: str):
        return await self.slides.get_slide_asset_path(run_id, slide_no, asset_path)

    async def save_slide_scene(self, *, run_id: str, slide_no: int, req: Any):
        return await self.slides.save_slide_scene(run_id=run_id, slide_no=slide_no, req=req)

    async def regenerate_single_slide(
        self,
        *,
        run_id: str,
        slide_no: int,
        instruction: str,
        preserve_style: bool,
        expected_render_version: int | None = None,
    ):
        return await self.slides.regenerate_single_slide(
            run_id=run_id,
            slide_no=slide_no,
            instruction=instruction,
            preserve_style=preserve_style,
            expected_render_version=expected_render_version,
        )
