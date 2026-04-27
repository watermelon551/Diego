from __future__ import annotations

from typing import Any

from ...models import EventType, RunRecord
from ...rag import StratumindSearchError
from ..outline_reporting import (
    build_outline_rag_degraded_payload,
    build_requirements_analyzed_payload,
)
from .outline_flow_errors import OutlineFlowStopped


class OutlineRequirementsMixin:
    async def _prepare_outline_requirements(
        self, *, run_id: str, run: RunRecord
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], str]:
        orch = self.orch
        requested_template_style = orch._requested_template_style(run)
        await orch._publish(
            run_id,
            EventType.REQUIREMENTS_ANALYZING_STARTED,
            {
                "target_slide_count": run.input.target_slide_count,
                "project_id": run.input.project_id,
                "has_rag": bool(run.input.rag_source_ids),
            },
        )
        selected_sources = [
            item for item in run.input.rag_source_ids if str(item).strip()
        ]
        try:
            rag_context_snippets, rag_retrieval = await orch._retrieve_outline_rag_context(
                run_id=run_id, run=run
            )
        except StratumindSearchError as exc:
            if selected_sources:
                await orch._fail_run(
                    run_id,
                    "OUTLINE_DRAFTING",
                    "OUTLINE_RAG_RETRIEVAL_FAILED",
                    retryable=exc.retryable,
                    error_details={
                        "error_code": exc.code,
                        "status_code": exc.status_code,
                        "reason": exc.message,
                        "details": exc.details or {},
                    },
                )
                raise OutlineFlowStopped from exc
            rag_context_snippets = []
            rag_retrieval = build_outline_rag_degraded_payload(
                target_slide_count=run.input.target_slide_count,
                top_k=orch._rag_query_top_k(
                    target_slide_count=run.input.target_slide_count
                ),
                enabled=bool(getattr(orch.rag_client, "enabled", False)),
                error_code=exc.code,
                status_code=exc.status_code,
                retryable=exc.retryable,
                reason=exc.message,
                details=exc.details or {},
            )
        rag_enabled = bool(rag_retrieval.get("enabled", True))
        if selected_sources and not rag_context_snippets and rag_enabled:
            error_code = (
                "OUTLINE_RAG_UNAVAILABLE"
                if not rag_enabled
                else "OUTLINE_RAG_NO_MATCH_FOR_SELECTED_SOURCES"
            )
            await orch._fail_run(
                run_id,
                "OUTLINE_DRAFTING",
                error_code,
                retryable=False,
                error_details={
                    "project_id": run.input.project_id,
                    "topic": run.input.topic,
                    "selected_file_ids": selected_sources,
                    "retrieval": rag_retrieval,
                },
            )
            raise OutlineFlowStopped(error_code)

        try:
            base_research = await orch._call_outline_with_timeout_retry(
                run_id=run_id,
                phase="requirements.analyze",
                action=lambda: orch.llm_client.generate_research_brief(
                    topic=run.input.topic,
                    project_id=run.input.project_id,
                    rag_source_ids=run.input.rag_source_ids,
                    rag_context_snippets=rag_context_snippets,
                    template_style=requested_template_style,
                    target_slide_count=run.input.target_slide_count,
                ),
            )
        except Exception:
            base_research = orch._fallback_research_brief(
                topic=run.input.topic,
                template_style=requested_template_style,
                target_slide_count=run.input.target_slide_count,
            )
        try:
            design_intent = await orch._call_outline_with_timeout_retry(
                run_id=run_id,
                phase="requirements.design_intent",
                action=lambda: orch.llm_client.generate_design_intent(
                    topic=run.input.topic,
                    template_style=requested_template_style,
                    target_slide_count=run.input.target_slide_count,
                    research_brief=base_research,
                ),
            )
        except Exception:
            design_intent = {}
        requirements_report = orch._compose_requirements_report(
            run=run,
            research_brief=base_research,
            design_intent=design_intent,
            rag_context_snippets=rag_context_snippets,
            rag_retrieval=rag_retrieval,
        )
        requirements_report = orch._apply_style_preset_to_requirements(
            run=run, report=requirements_report
        )
        effective_template_style = (
            str(requirements_report.get("effective_template_style", "")).strip()
            or run.input.template_style
        )
        await orch.store.update_run(
            run_id, lambda r: setattr(r, "research_report", requirements_report)
        )
        requirements_payload = build_requirements_analyzed_payload(
            requirements_report=requirements_report,
            target_slide_count=run.input.target_slide_count,
            rag_retrieval=rag_retrieval,
        )
        requirements_payload["effective_template_style"] = effective_template_style
        await orch._publish(
            run_id, EventType.REQUIREMENTS_ANALYZING_COMPLETED, requirements_payload
        )
        await orch._publish(
            run_id, EventType.REQUIREMENTS_ANALYZED, requirements_payload
        )
        return (
            rag_context_snippets,
            rag_retrieval,
            requirements_report,
            effective_template_style,
        )
