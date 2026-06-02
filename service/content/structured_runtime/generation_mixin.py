from __future__ import annotations

import asyncio
import time
from typing import Any

from ...llm import LongFormFormatError
from ...models import (
    EventType,
    ItemGenerationRunRequest,
    StructureExpansionRunRequest,
)

# Overall timeout for structured content generation (LLM + RAG + processing)
# Must exceed per-attempt LLM timeout × max retries to avoid false timeouts.
# With LLM_TIMEOUT_SEC=1200 and OUTLINE_TIMEOUT_RETRIES=3, max retry time = 4800s.
_STRUCTURED_GENERATION_TIMEOUT_SEC = 6000  # 10 minutes hard cap


class StructuredContentGenerationMixin:
    orch: Any

    async def generate_structure_expansion(self, run_id: str) -> None:
        try:
            await asyncio.wait_for(
                self._generate_structure_expansion_inner(run_id),
                timeout=_STRUCTURED_GENERATION_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            await self.orch._fail_run(
                run_id,
                "DRAFTING",
                "STRUCTURE_EXPANSION_TIMEOUT",
                retryable=True,
                error_details={
                    "reason": f"Structure expansion exceeded overall timeout ({_STRUCTURED_GENERATION_TIMEOUT_SEC}s). LLM call may have hung.",
                },
            )

    async def _generate_structure_expansion_inner(self, run_id: str) -> None:
        run = await self.orch.store.get_run(run_id)
        if (
            run is None
            or getattr(run.input, "capability", "") != "content"
            or str(getattr(run.input, "content_kind", "")) != "structure_expansion"
        ):
            return
        started = time.perf_counter()
        retrieval = await self._safe_retrieve_generic_context(run_id=run_id, run=run)
        if retrieval is None:
            return
        rag_context_snippets, rag_retrieval = retrieval
        req = run.input
        assert isinstance(req, StructureExpansionRunRequest)
        try:
            result = await self.orch._call_outline_with_timeout_retry(
                run_id=run_id,
                phase="content.structure_expansion.generate",
                action=lambda: self.orch.llm_client.generate_structure_expansion(
                    generation_goal=req.generation_goal,
                    project_id=req.project_id,
                    source_scope=req.source_scope.model_dump(mode="json"),
                    evidence_refs=req.evidence_refs,
                    anchor_context=req.anchor_context,
                    constraints=req.constraints,
                    requested_output_shape=req.requested_output_shape,
                    rag_source_ids=req.rag_source_ids,
                    rag_context_snippets=rag_context_snippets,
                ),
            )
        except LongFormFormatError as exc:
            await self.orch._fail_run(
                run_id,
                "DRAFTING",
                "STRUCTURE_EXPANSION_INVALID",
                retryable=True,
                error_details={"error_category": exc.category, "error_details": exc.details},
            )
            return
        except Exception as exc:
            await self.orch._fail_run(
                run_id,
                "DRAFTING",
                "STRUCTURE_EXPANSION_FAILED",
                retryable=True,
                error_details={"reason": self.orch._exception_reason(exc)},
            )
            return

        def apply_result(record: Any) -> None:
            record.structure_expansion_result = result
            record.research_report = {
                "rag_context_snippets": rag_context_snippets,
                "rag_retrieval": rag_retrieval,
                "content_source_mode": "rag_first" if req.rag_source_ids else "project_all",
                "canonical_output": result.schema_version,
            }
            record.longform_stage_timings.draft_ms = int((time.perf_counter() - started) * 1000)

        await self.orch.store.update_run(run_id, apply_result)
        await self.orch._publish(
            run_id,
            EventType.STRUCTURE_EXPANSION_COMPLETED,
            {"unit_count": len(result.units), "warning_count": len(result.warnings)},
        )
        await self.orch._finalize_run_success(
            run_id=run_id,
            from_stage="DRAFTING",
            reason="structure expansion completed",
        )

    async def generate_item_generation(self, run_id: str) -> None:
        try:
            await asyncio.wait_for(
                self._generate_item_generation_inner(run_id),
                timeout=_STRUCTURED_GENERATION_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            await self.orch._fail_run(
                run_id,
                "DRAFTING",
                "ITEM_GENERATION_TIMEOUT",
                retryable=True,
                error_details={
                    "reason": f"Item generation exceeded overall timeout ({_STRUCTURED_GENERATION_TIMEOUT_SEC}s). LLM call may have hung.",
                },
            )

    async def _generate_item_generation_inner(self, run_id: str) -> None:
        run = await self.orch.store.get_run(run_id)
        if (
            run is None
            or getattr(run.input, "capability", "") != "content"
            or str(getattr(run.input, "content_kind", "")) != "item_generation"
        ):
            return
        started = time.perf_counter()
        retrieval = await self._safe_retrieve_generic_context(run_id=run_id, run=run)
        if retrieval is None:
            return
        rag_context_snippets, rag_retrieval = retrieval
        req = run.input
        assert isinstance(req, ItemGenerationRunRequest)
        try:
            result = await self.orch._call_outline_with_timeout_retry(
                run_id=run_id,
                phase="content.item_generation.generate",
                action=lambda: self.orch.llm_client.generate_item_generation(
                    generation_goal=req.generation_goal,
                    project_id=req.project_id,
                    source_scope=req.source_scope.model_dump(mode="json"),
                    evidence_refs=req.evidence_refs,
                    constraints=req.constraints,
                    requested_output_shape=req.requested_output_shape,
                    rag_source_ids=req.rag_source_ids,
                    rag_context_snippets=rag_context_snippets,
                ),
            )
        except LongFormFormatError as exc:
            await self.orch._fail_run(
                run_id,
                "DRAFTING",
                "ITEM_GENERATION_INVALID",
                retryable=True,
                error_details={"error_category": exc.category, "error_details": exc.details},
            )
            return
        except Exception as exc:
            await self.orch._fail_run(
                run_id,
                "DRAFTING",
                "ITEM_GENERATION_FAILED",
                retryable=True,
                error_details={"reason": self.orch._exception_reason(exc)},
            )
            return

        def apply_result(record: Any) -> None:
            record.item_generation_result = result
            record.research_report = {
                "rag_context_snippets": rag_context_snippets,
                "rag_retrieval": rag_retrieval,
                "content_source_mode": "rag_first" if req.rag_source_ids else "project_all",
                "canonical_output": result.schema_version,
            }
            record.longform_stage_timings.draft_ms = int((time.perf_counter() - started) * 1000)

        await self.orch.store.update_run(run_id, apply_result)
        await self.orch._publish(
            run_id,
            EventType.ITEM_GENERATION_COMPLETED,
            {"item_count": len(result.items), "warning_count": len(result.warnings)},
        )
        await self.orch._finalize_run_success(
            run_id=run_id,
            from_stage="DRAFTING",
            reason="item generation completed",
        )
