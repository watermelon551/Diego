from __future__ import annotations

import time

from ...design.skill_profile import enforce_layout_variety
from ...infra.store import now_iso
from ...models import (
    EventType,
    OutlineDocument,
    OutlineHistoryEntry,
    RunRecord,
    RunStatus,
)
from ..outline_reporting import (
    build_plan_completed_payload,
    build_research_completed_payload,
)


class OutlineFinalizeMixin:
    async def _finalize_outline(
        self,
        *,
        run_id: str,
        run: RunRecord,
        outline: OutlineDocument,
        requirements_report: dict,
        rag_retrieval: dict,
        effective_template_style: str,
        started: float,
    ) -> None:
        orch = self.orch
        style_dna_id = ""
        if isinstance(requirements_report.get("design_intent", {}), dict):
            style_dna_id = str(
                requirements_report.get("design_intent", {}).get("style_dna_id", "")
            ).strip()
        enforce_layout_variety(
            nodes=outline.nodes,
            seed=f"{run.input.topic}|{effective_template_style}|{run_id}",
            style_dna_id=style_dna_id or None,
        )
        design = orch._resolve_design_profile(
            topic=run.input.topic,
            template_style=effective_template_style,
            requirements_report=requirements_report,
        )

        def apply_outline(r: RunRecord) -> None:
            r.outline = outline
            r.research_report = requirements_report
            r.status = RunStatus.AWAITING_OUTLINE_CONFIRM
            r.stage_timings.outline_ms = int((time.perf_counter() - started) * 1000)
            r.outline_history.append(
                OutlineHistoryEntry(
                    action="generated",
                    approved=False,
                    base_version=None,
                    new_version=outline.version,
                    change_reason=None,
                    at=now_iso(),
                )
            )

        await orch.store.update_run(run_id, apply_outline)
        await orch._publish(
            run_id,
            EventType.OUTLINE_COMPLETED,
            {"version": outline.version, "sections": len(outline.nodes)},
        )
        await orch._publish(
            run_id,
            EventType.RESEARCH_COMPLETED,
            build_research_completed_payload(
                requirements_report=requirements_report,
                rag_retrieval=rag_retrieval,
            ),
        )
        await orch._publish(
            run_id,
            EventType.PLAN_COMPLETED,
            build_plan_completed_payload(
                section_count=len(outline.nodes),
                palette_name=design.palette_name,
                style_name=design.style.name,
                style_dna_id=style_dna_id,
                title_font=design.title_font,
                body_font=design.body_font,
                theme=design.theme,
            ),
        )
