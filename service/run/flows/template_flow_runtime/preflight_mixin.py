from __future__ import annotations

from typing import Any

from ...types import (
    TemplateAssetError,
    TemplateLayoutConflictError,
    TemplateSlotMappingError,
)


class TemplateFlowPreflightMixin:
    orch: Any

    async def _load_template_run_context(self, run_id: str) -> tuple[Any, Any, str, Any] | None:
        orch = self.orch
        run = await orch.store.get_run(run_id)
        assert run is not None and run.outline is not None
        orch._init_run_llm_budget(
            run_id=run_id, target_slide_count=run.input.target_slide_count
        )
        effective_template_style = orch._resolved_template_style(run)
        design = orch._resolve_design_profile(
            topic=run.input.topic,
            template_style=effective_template_style,
            requirements_report=(
                run.research_report if isinstance(run.research_report, dict) else {}
            ),
        )
        if not run.input.template_id:
            await orch._fail_run(
                run_id, "SLIDES_GENERATING", "TEMPLATE_ID_MISSING", retryable=False
            )
            return None

        template_record = await orch.store.get_template(run.input.template_id)
        if template_record is None:
            await orch._fail_run(
                run_id, "SLIDES_GENERATING", "TEMPLATE_NOT_FOUND", retryable=False
            )
            return None
        return run, template_record, effective_template_style, design

    async def _fail_template_apply_exception(self, run_id: str, exc: Exception) -> bool:
        orch = self.orch
        if isinstance(exc, TemplateAssetError):
            await orch._fail_run(
                run_id,
                "SLIDES_GENERATING",
                "TEMPLATE_ASSET_FETCH_FAILED",
                retryable=False,
            )
            return True
        if isinstance(exc, TemplateSlotMappingError):
            await orch._fail_run(
                run_id, "SLIDES_GENERATING", "TEMPLATE_SLOT_UNMAPPED", retryable=False
            )
            return True
        if isinstance(exc, TemplateLayoutConflictError):
            await orch._fail_run(
                run_id, "SLIDES_GENERATING", "TEMPLATE_LAYOUT_CONFLICT", retryable=False
            )
            return True
        return False
