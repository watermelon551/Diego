from __future__ import annotations

import time
from typing import Any

from ...infra.store import now_iso
from ...llm import LongFormFormatError
from ...models import (
    EventType,
    LongFormPlan,
    LongFormPlanHistoryEntry,
    RunRecord,
    RunStatus,
)


class ContentPlanGenerationMixin:
    orch: Any

    async def start_plan(self, run_id: str) -> None:
        run = await self.orch.store.get_run(run_id)
        if (
            run is None
            or getattr(run.input, "capability", "") != "content"
            or str(getattr(run.input, "content_kind", "longform_draft"))
            != "longform_draft"
        ):
            return
        started = time.perf_counter()
        try:
            rag_context_snippets, _rag_retrieval, _research_report = (
                await self._prepare_plan_requirements(run_id=run_id, run=run)
            )
        except Exception:
            return

        async def on_token(token: str) -> None:
            await self.orch._publish(run_id, EventType.PLAN_TOKEN, {"token": token})

        plan = await self._draft_plan_with_repair(
            run_id=run_id,
            run=run,
            rag_context_snippets=rag_context_snippets,
            on_token=on_token,
        )
        if plan is None:
            return
        try:
            plan = await self.orch._call_outline_with_timeout_retry(
                run_id=run_id,
                phase="content.plan.critique",
                action=lambda: self.orch.llm_client.critique_longform_plan(
                    topic=run.input.topic,
                    audience=run.input.audience,
                    purpose=run.input.purpose,
                    tone=run.input.tone,
                    target_section_count=run.input.target_section_count,
                    plan=plan,
                ),
            )
        except Exception:
            pass

        def apply_plan(record: RunRecord) -> None:
            record.longform_plan = plan
            record.longform_plan_history.append(
                LongFormPlanHistoryEntry(
                    action="drafted",
                    approved=False,
                    base_version=None,
                    new_version=plan.version,
                    change_reason=None,
                    at=now_iso(),
                )
            )
            record.status = RunStatus.AWAITING_PLAN_CONFIRM
            record.longform_stage_timings.plan_ms = int(
                (time.perf_counter() - started) * 1000
            )

        await self.orch.store.update_run(run_id, apply_plan)
        await self.orch._publish(
            run_id,
            EventType.PLAN_COMPLETED,
            {
                "version": plan.version,
                "title": plan.title,
                "section_count": len(plan.sections),
            },
        )

    async def _draft_plan_with_repair(
        self,
        *,
        run_id: str,
        run: RunRecord,
        rag_context_snippets: list[dict[str, Any]],
        on_token,
    ) -> LongFormPlan | None:
        plan: LongFormPlan | None = None
        previous_response = ""
        error_category = ""
        error_details: list[str] = []
        repair_attempts = max(1, self.orch.llm_max_retries)
        for attempt in range(1, repair_attempts + 2):
            try:
                if attempt == 1:
                    plan = await self.orch._call_outline_with_timeout_retry(
                        run_id=run_id,
                        phase="content.plan.generate",
                        action=lambda: self.orch.llm_client.generate_longform_plan(
                            topic=run.input.topic,
                            project_id=run.input.project_id,
                            rag_source_ids=run.input.rag_source_ids,
                            rag_context_snippets=rag_context_snippets,
                            audience=run.input.audience,
                            purpose=run.input.purpose,
                            tone=run.input.tone,
                            target_section_count=run.input.target_section_count,
                            on_token=on_token,
                        ),
                    )
                else:
                    plan = await self.orch._call_outline_with_timeout_retry(
                        run_id=run_id,
                        phase="content.plan.repair",
                        action=lambda: self.orch.llm_client.repair_longform_plan(
                            topic=run.input.topic,
                            project_id=run.input.project_id,
                            rag_source_ids=run.input.rag_source_ids,
                            rag_context_snippets=rag_context_snippets,
                            audience=run.input.audience,
                            purpose=run.input.purpose,
                            tone=run.input.tone,
                            target_section_count=run.input.target_section_count,
                            previous_response=previous_response,
                            error_category=error_category,
                            error_details=error_details,
                        ),
                    )
                break
            except LongFormFormatError as exc:
                previous_response = exc.raw_response
                error_category = exc.category
                error_details = list(exc.details)
                if attempt >= repair_attempts + 1:
                    await self.orch._fail_run(
                        run_id,
                        "PLANNING",
                        "LONGFORM_PLAN_REPAIR_EXHAUSTED",
                        retryable=True,
                        error_details={
                            "attempts": attempt,
                            "error_category": error_category,
                            "error_details": error_details,
                        },
                    )
                    return None
                continue
        if plan is None:
            await self.orch._fail_run(
                run_id,
                "PLANNING",
                "LONGFORM_PLAN_MISSING",
                retryable=True,
            )
            return None
        return plan

    def _fallback_research_brief(self, *, run: RunRecord) -> dict[str, Any]:
        return {
            "audience": run.input.audience,
            "purpose": run.input.purpose,
            "tone": run.input.tone,
            "narrative_arc": "context -> key ideas -> evidence -> synthesis",
            "section_focus": [
                f"Section {idx}: focus on {run.input.topic} theme {idx}"
                for idx in range(1, run.input.target_section_count + 1)
            ],
            "source_themes": [],
        }
