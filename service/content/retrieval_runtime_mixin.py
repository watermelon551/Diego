from __future__ import annotations

from typing import Any

from ..models import EventType, RunRecord
from ..rag import StratumindSearchError, build_rag_context_snippets


class ContentRetrievalRuntimeMixin:
    orch: Any

    async def _retrieve_rag_context(
        self, *, run_id: str, run: RunRecord
    ) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
        query = self._content_query_text(run)
        selected_file_ids = self._content_source_ids(run)
        retrieval_mode = "selected_files" if selected_file_ids else "project_all"
        top_k = self.orch._rag_query_top_k(target_slide_count=self._content_target_units(run))
        await self.orch._publish(
            run_id,
            EventType.RAG_RETRIEVAL_STARTED,
            {
                "mode": retrieval_mode,
                "selected_file_count": len(selected_file_ids),
                "top_k": top_k,
                "query": query,
            },
        )
        if not self.orch.rag_client.enabled:
            payload = {
                "mode": retrieval_mode,
                "selected_file_count": len(selected_file_ids),
                "top_k": top_k,
                "enabled": False,
                "hit_count": 0,
                "reason": "stratumind_not_configured",
            }
            await self.orch._publish(run_id, EventType.RAG_RETRIEVAL_COMPLETED, payload)
            return [], payload
        response = await self.orch.rag_client.search_text(
            project_id=run.input.project_id,
            query=query,
            top_k=top_k,
            file_ids=selected_file_ids or None,
        )
        snippets = build_rag_context_snippets(
            response,
            max_items=max(
                1, int(getattr(self.orch.settings, "rag_context_max_snippets", 10))
            ),
            max_chars=max(
                120, int(getattr(self.orch.settings, "rag_context_max_chars", 700))
            ),
        )
        payload = {
            "mode": retrieval_mode,
            "selected_file_count": len(selected_file_ids),
            "top_k": top_k,
            "enabled": True,
            "hit_count": len(snippets),
            "total": int(response.get("total", len(snippets)) or len(snippets)),
            "ranking_stage": str(response.get("ranking_stage", "")).strip(),
            "degraded": bool(response.get("degraded", False)),
            "degrade_reason": str(response.get("degrade_reason", "")).strip(),
        }
        await self.orch._publish(run_id, EventType.RAG_RETRIEVAL_COMPLETED, payload)
        return snippets, payload

    async def _safe_retrieve_generic_context(
        self, *, run_id: str, run: RunRecord
    ) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
        try:
            return await self._retrieve_rag_context(run_id=run_id, run=run)
        except StratumindSearchError as exc:
            await self.orch._fail_run(
                run_id,
                "PLANNING",
                "CONTENT_RAG_RETRIEVAL_FAILED",
                retryable=exc.retryable,
                error_details={
                    "error_code": exc.code,
                    "status_code": exc.status_code,
                    "reason": exc.message,
                    "details": exc.details or {},
                },
            )
            return None

    def _stored_rag_context_snippets(self, run: RunRecord) -> list[dict[str, Any]]:
        report = run.research_report if isinstance(run.research_report, dict) else {}
        raw = report.get("rag_context_snippets", [])
        return list(raw) if isinstance(raw, list) else []

    def _content_query_text(self, run: RunRecord) -> str:
        topic = str(getattr(run.input, "topic", "") or "").strip()
        if topic:
            return topic
        goal = str(getattr(run.input, "generation_goal", "") or "").strip()
        if goal:
            return goal
        return "content generation"

    def _content_target_units(self, run: RunRecord) -> int:
        section_count = getattr(run.input, "target_section_count", None)
        if isinstance(section_count, int) and section_count > 0:
            return section_count
        constraints = getattr(run.input, "constraints", {})
        if isinstance(constraints, dict):
            for key in ("max_units", "max_items"):
                value = constraints.get(key)
                if isinstance(value, int) and value > 0:
                    return value
        return 3

    def _content_source_ids(self, run: RunRecord) -> list[str]:
        source_ids: list[str] = []
        for item in getattr(run.input, "rag_source_ids", []) or []:
            value = str(item).strip()
            if value:
                source_ids.append(value)
        source_scope = getattr(run.input, "source_scope", None)
        if (
            source_scope is not None
            and str(getattr(source_scope, "mode", "")).strip() == "selected_sources"
        ):
            for item in getattr(source_scope, "selected_source_ids", []) or []:
                value = str(item).strip()
                if value and value not in source_ids:
                    source_ids.append(value)
        return source_ids
