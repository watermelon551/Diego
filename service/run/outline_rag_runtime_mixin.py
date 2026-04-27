from __future__ import annotations

from typing import Any

from ..models import EventType, RunRecord
from ..rag import StratumindSearchError, build_rag_context_snippets


class RunOutlineRagRuntimeMixin:
    async def _publish(
        self, run_id: str, event_type: EventType, payload: dict[str, Any]
    ) -> None:
        await self._kernel.publish(run_id, event_type, payload)

    def _rag_query_top_k(self, *, target_slide_count: int) -> int:
        baseline = max(1, int(getattr(self.settings, "rag_top_k", 10)))
        return max(baseline, max(1, int(target_slide_count)))

    async def _retrieve_outline_rag_context(
        self,
        *,
        run_id: str,
        run: RunRecord,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        selected_file_ids = [
            str(item).strip()
            for item in (run.input.rag_source_ids or [])
            if str(item).strip()
        ]
        retrieval_mode = "selected_files" if selected_file_ids else "project_all"
        top_k = self._rag_query_top_k(target_slide_count=run.input.target_slide_count)
        await self._publish(
            run_id,
            EventType.RAG_RETRIEVAL_STARTED,
            {
                "mode": retrieval_mode,
                "selected_file_count": len(selected_file_ids),
                "top_k": top_k,
                "query": run.input.topic,
            },
        )
        if not self.rag_client.enabled:
            payload = {
                "mode": retrieval_mode,
                "selected_file_count": len(selected_file_ids),
                "top_k": top_k,
                "enabled": False,
                "hit_count": 0,
                "reason": "stratumind_not_configured",
            }
            await self._publish(run_id, EventType.RAG_RETRIEVAL_COMPLETED, payload)
            return [], payload
        try:
            response = await self.rag_client.search_text(
                project_id=run.input.project_id,
                query=run.input.topic,
                top_k=top_k,
                file_ids=selected_file_ids or None,
            )
        except StratumindSearchError as exc:
            await self._publish(
                run_id,
                EventType.RAG_RETRIEVAL_FAILED,
                {
                    "mode": retrieval_mode,
                    "selected_file_count": len(selected_file_ids),
                    "error_code": exc.code,
                    "status_code": exc.status_code,
                    "retryable": exc.retryable,
                    "reason": exc.message,
                    "details": exc.details or {},
                },
            )
            raise
        snippets = build_rag_context_snippets(
            response,
            max_items=max(
                1, int(getattr(self.settings, "rag_context_max_snippets", 10))
            ),
            max_chars=max(
                120, int(getattr(self.settings, "rag_context_max_chars", 700))
            ),
        )
        raw_total = response.get("total", len(snippets))
        try:
            total = int(raw_total)
        except (TypeError, ValueError):
            total = len(snippets)
        payload = {
            "mode": retrieval_mode,
            "selected_file_count": len(selected_file_ids),
            "top_k": top_k,
            "enabled": True,
            "hit_count": len(snippets),
            "total": total,
            "ranking_stage": str(response.get("ranking_stage", "")).strip(),
            "degraded": bool(response.get("degraded", False)),
            "degrade_reason": str(response.get("degrade_reason", "")).strip(),
        }
        await self._publish(run_id, EventType.RAG_RETRIEVAL_COMPLETED, payload)
        return snippets, payload
