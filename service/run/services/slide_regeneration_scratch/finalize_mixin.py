from __future__ import annotations

from ....models import EventType, RunRecord, RunStatus


class SlideRegenerationScratchFinalizeMixin:
    async def _finalize_scratch_regenerated_slide(
        self,
        *,
        run_id: str,
        run: RunRecord,
        slide_no: int,
        updated_node,
        artifact,
        citations: list[str],
        chart_plan,
        preview: dict[str, object],
        design,
    ) -> None:
        orch = self.orch

        def apply_slide_update(r: RunRecord) -> None:
            r.status = RunStatus.COMPILING
            r.outline.nodes[slide_no - 1] = updated_node
            r.citation_map[slide_no] = list(citations)
            for index, existing in enumerate(r.slides):
                if int(getattr(existing, "slide_no", 0) or 0) == slide_no:
                    r.slides[index] = artifact
                    break

        await orch.store.update_run(run_id, apply_slide_update)
        await orch._append_chart_truth_report(
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
        await orch._publish(
            run_id,
            EventType.CHART_TRUTH_CHECKED,
            {
                "slide_no": slide_no,
                "has_verified_data": chart_plan.has_verified_data,
                "mode": chart_plan.mode,
                "source": chart_plan.source,
            },
        )
        await self.publish_slide_generated_preview(
            run_id=run_id,
            slide_no=slide_no,
            status=artifact.status,
            preview=preview,
        )
        await self._finalize_scratch_regeneration_compile(
            run_id=run_id,
            run=run,
            design=design,
        )
