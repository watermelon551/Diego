from __future__ import annotations

from typing import Any

from ..models import EventType, RunRecord
from ..rag import StratumindSearchError


class ContentPlanRequirementsMixin:
    orch: Any

    async def _prepare_plan_requirements(
        self, *, run_id: str, run: RunRecord
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        await self.orch._publish(
            run_id,
            EventType.REQUIREMENTS_ANALYZING_STARTED,
            {
                "target_section_count": run.input.target_section_count,
                "project_id": run.input.project_id,
                "has_rag": bool(run.input.rag_source_ids),
            },
        )
        try:
            rag_context_snippets, rag_retrieval = await self._retrieve_rag_context(
                run_id=run_id, run=run
            )
        except StratumindSearchError as exc:
            await self.orch._fail_run(
                run_id,
                "PLANNING",
                "LONGFORM_RAG_RETRIEVAL_FAILED",
                retryable=exc.retryable,
                error_details={
                    "error_code": exc.code,
                    "status_code": exc.status_code,
                    "reason": exc.message,
                    "details": exc.details or {},
                },
            )
            raise

        try:
            research_brief = await self.orch._call_outline_with_timeout_retry(
                run_id=run_id,
                phase="content.requirements.analyze",
                action=lambda: self.orch.llm_client.generate_longform_research_brief(
                    topic=run.input.topic,
                    project_id=run.input.project_id,
                    rag_source_ids=run.input.rag_source_ids,
                    rag_context_snippets=rag_context_snippets,
                    audience=run.input.audience,
                    purpose=run.input.purpose,
                    tone=run.input.tone,
                    target_section_count=run.input.target_section_count,
                ),
            )
        except Exception:
            research_brief = self._fallback_research_brief(run=run)

        research_report = {
            **dict(research_brief or {}),
            "rag_context_snippets": rag_context_snippets,
            "rag_retrieval": rag_retrieval,
            "section_count_fixed": run.input.target_section_count,
            "content_source_mode": "rag_first"
            if run.input.rag_source_ids
            else "project_all",
            "canonical_output": "content_blocks_v1",
        }
        await self.orch.store.update_run(
            run_id, lambda record: setattr(record, "research_report", research_report)
        )
        requirements_payload = {
            "section_count_fixed": run.input.target_section_count,
            "audience": research_report.get("audience", run.input.audience),
            "purpose": research_report.get("purpose", run.input.purpose),
            "tone": research_report.get("tone", run.input.tone),
            "content_source_mode": research_report.get("content_source_mode", ""),
            "rag_hit_count": rag_retrieval.get("hit_count", 0),
        }
        await self.orch._publish(
            run_id, EventType.REQUIREMENTS_ANALYZING_COMPLETED, requirements_payload
        )
        await self.orch._publish(
            run_id, EventType.REQUIREMENTS_ANALYZED, requirements_payload
        )
        return rag_context_snippets, rag_retrieval, research_report
