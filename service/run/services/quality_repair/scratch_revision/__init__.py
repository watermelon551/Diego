from __future__ import annotations

from typing import Any

from .....design.skill_profile import DesignProfile
from .....models import OutlineNode
from .agentic_mixin import AgenticScratchRevisionMixin


class QualityScratchRevisionMixin(
    AgenticScratchRevisionMixin,
):
    orch: Any

    async def revise_scratch_slides(
        self,
        *,
        run_id: str,
        design: DesignProfile,
        forced_issues: list[str] | None,
    ) -> bool:
        orch = self.orch
        run = await orch.store.get_run(run_id)
        if run is None or run.outline is None:
            return False
        effective_template_style = orch._resolved_template_style(run)
        return await self._revise_agentic_scratch_slides(
            run_id=run_id,
            run=run,
            design=design,
            effective_template_style=effective_template_style,
            forced_issues=forced_issues,
        )

    def _chart_plan_for_reviewed(
        self,
        *,
        node: OutlineNode,
        reviewed: Any,
        source_refs: list[str] | None,
    ) -> Any:
        orch = self.orch
        return orch._build_chart_plan_from_bullets(
            node=OutlineNode(
                title=reviewed.title,
                bullets=list(reviewed.bullets),
                page_type=node.page_type,
                layout_hint=reviewed.layout_hint or node.layout_hint,
            ),
            source_refs=list(source_refs or []),
        )

    async def _append_chart_truth_entry(
        self,
        *,
        run_id: str,
        slide_no: int,
        chart_plan: Any,
    ) -> None:
        await self.orch._append_chart_truth_report(
            run_id=run_id,
            entry={
                "slide_no": slide_no,
                "has_verified_data": chart_plan.has_verified_data,
                "mode": chart_plan.mode,
                "source": chart_plan.source,
                "note": chart_plan.note,
                "labels": chart_plan.labels,
            },
        )


__all__ = ["QualityScratchRevisionMixin"]
