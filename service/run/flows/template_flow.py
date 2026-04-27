from __future__ import annotations

from typing import Any

from .template_flow_runtime import (
    TemplateFlowApplyCompileMixin,
    TemplateFlowPreflightMixin,
    TemplateFlowPrepareMixin,
    TemplateFlowPreviewFinalizeMixin,
)


class TemplateFlowService(
    TemplateFlowPreflightMixin,
    TemplateFlowPrepareMixin,
    TemplateFlowApplyCompileMixin,
    TemplateFlowPreviewFinalizeMixin,
):
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator

    async def execute(self, run_id: str) -> None:
        context = await self._load_template_run_context(run_id)
        if context is None:
            return
        run, template_record, _effective_template_style, design = context
        work_paths = await self._prepare_template_workspace(
            run_id=run_id,
            artifact_dir=run.artifact_dir,
            template_path=template_record.path,
        )
        if work_paths is None:
            return
        (
            _template_dir,
            _work_template,
            _template_md,
            unpacked,
            edited,
            template_slides_dir,
            template_compile_js,
            _,
        ) = work_paths
        apply_result = await self._apply_template_generation(
            run_id=run_id,
            unpacked=unpacked,
            design=design,
        )
        if apply_result is None:
            return
        artifacts, compile_start = apply_result
        compiled = await self._compile_template_outputs(
            run_id=run_id,
            artifacts=artifacts,
            compile_start=compile_start,
            unpacked=unpacked,
            edited=edited,
            template_slides_dir=template_slides_dir,
            template_compile_js=template_compile_js,
        )
        if not compiled:
            return
        previews_published = await self._publish_template_previews(
            run_id=run_id,
            artifacts=artifacts,
            theme=design.theme,
        )
        if not previews_published:
            return
        await self._finalize_template_run(
            run_id=run_id,
            edited=edited,
            template_compile_js=template_compile_js,
            design=design,
        )


__all__ = ["TemplateFlowService"]
