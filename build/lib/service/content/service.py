from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..infra.store import now_iso
from ..llm import LLMTimeoutError, LongFormFormatError
from ..models import (
    ContentBlock,
    ConfirmLongFormPlanRequest,
    EventType,
    LongFormDraft,
    LongFormDraftSection,
    LongFormDraftStats,
    LongFormPlan,
    LongFormPlanHistoryEntry,
    LongFormRunDetailResponse,
    LongFormRunRequest,
    LongFormSectionRevisionResponse,
    ReviseLongFormSectionRequest,
    RunRecord,
    RunStatus,
    RunSummaryResponse,
)
from ..rag import StratumindSearchError, build_rag_context_snippets


class LongFormContentService:
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator

    async def create_run(self, req: LongFormRunRequest) -> RunSummaryResponse:
        run_id = str(uuid4())
        trace_id = str(uuid4())
        artifact_dir = self.orch.artifacts_base / run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        run = RunRecord(
            run_id=run_id,
            trace_id=trace_id,
            status=RunStatus.PLANNING,
            input=req,
            artifact_dir=str(artifact_dir),
        )
        await self.orch.store.add_run(run)
        self.orch._spawn(self.start_plan(run_id))
        return RunSummaryResponse(run_id=run_id, trace_id=trace_id, status=run.status)

    async def get_run_detail(self, run_id: str) -> LongFormRunDetailResponse | None:
        run = await self.orch.store.get_run(run_id)
        if run is None or getattr(run.input, "capability", "") != "content":
            return None
        return LongFormRunDetailResponse(
            run_id=run.run_id,
            trace_id=run.trace_id,
            status=run.status,
            plan=run.longform_plan,
            plan_history=run.longform_plan_history,
            draft=run.longform_draft,
            stage_timings=run.longform_stage_timings,
            error_code=run.error_code,
            failed_stage=run.failed_stage,
            retryable=run.retryable,
            error_details=run.error_details,
            research_report=run.research_report,
            events=run.events,
        )

    async def confirm_plan(
        self, run_id: str, req: ConfirmLongFormPlanRequest
    ) -> RunSummaryResponse | None:
        run = await self.orch.store.get_run(run_id)
        if run is None or getattr(run.input, "capability", "") != "content":
            return None
        if run.status != RunStatus.AWAITING_PLAN_CONFIRM:
            raise ValueError("run is not awaiting plan confirmation")
        if run.longform_plan is None:
            raise ValueError("run plan is missing")
        if req.plan is not None:
            if req.base_version != run.longform_plan.version:
                raise ValueError(
                    f"base_version mismatch: expected {run.longform_plan.version}, got {req.base_version}"
                )
            if req.plan.version <= run.longform_plan.version:
                req.plan.version = run.longform_plan.version + 1

        def apply_confirm(record: RunRecord) -> None:
            current_version = (
                record.longform_plan.version if record.longform_plan is not None else None
            )
            if req.plan is not None:
                record.longform_plan = req.plan
            record.status = (
                RunStatus.DRAFTING if req.approved else RunStatus.AWAITING_PLAN_CONFIRM
            )
            new_version = (
                record.longform_plan.version if record.longform_plan is not None else None
            )
            action = (
                "confirmed"
                if req.approved
                else ("updated" if req.plan is not None else "rejected")
            )
            record.longform_plan_history.append(
                LongFormPlanHistoryEntry(
                    action=action,
                    approved=req.approved,
                    base_version=current_version,
                    new_version=new_version,
                    change_reason=req.change_reason,
                    at=now_iso(),
                )
            )

        await self.orch.store.update_run(run_id, apply_confirm)
        if req.plan is not None:
            await self.orch._publish(
                run_id,
                EventType.PLAN_UPDATED,
                {
                    "approved": req.approved,
                    "base_version": req.base_version,
                    "new_version": req.plan.version,
                    "change_reason": req.change_reason,
                },
            )
        if req.approved:
            self.orch._spawn(self.generate_draft(run_id))
        updated = await self.orch.store.get_run(run_id)
        assert updated is not None
        return RunSummaryResponse(
            run_id=updated.run_id, trace_id=updated.trace_id, status=updated.status
        )

    async def revise_section(
        self, run_id: str, section_id: str, req: ReviseLongFormSectionRequest
    ) -> LongFormSectionRevisionResponse | None:
        run = await self.orch.store.get_run(run_id)
        if run is None or getattr(run.input, "capability", "") != "content":
            return None
        if run.status != RunStatus.SUCCEEDED:
            raise ValueError("run must be in SUCCEEDED state")
        if run.longform_plan is None or run.longform_draft is None:
            raise ValueError("long-form draft is not ready")
        current_section = next(
            (item for item in run.longform_draft.sections if item.section_id == section_id),
            None,
        )
        if current_section is None:
            raise ValueError("section not found")
        if current_section.revision != req.base_revision:
            raise ValueError(
                "section revision conflict: "
                f"expected {req.base_revision}, current {current_section.revision}"
            )
        plan_section = next(
            (
                item
                for item in run.longform_plan.sections
                if item.section_id == section_id
            ),
            None,
        )
        if plan_section is None:
            raise ValueError("plan section not found")
        rag_context_snippets = self._stored_rag_context_snippets(run)
        started = time.perf_counter()
        try:
            revised = await self.orch._call_outline_with_timeout_retry(
                run_id=run_id,
                phase="content.section.revise",
                action=lambda: self.orch.llm_client.revise_section_draft(
                    topic=run.input.topic,
                    project_id=run.input.project_id,
                    audience=run.input.audience,
                    purpose=run.input.purpose,
                    tone=run.input.tone,
                    plan=run.longform_plan,
                    current_section=current_section,
                    instruction=req.instruction,
                    preserve_structure=req.preserve_structure,
                    rag_source_ids=run.input.rag_source_ids,
                    rag_context_snippets=rag_context_snippets,
                ),
            )
        except LongFormFormatError as exc:
            raise ValueError(str(exc)) from exc
        revised = self._normalize_revised_section(
            revised=revised,
            current=current_section,
            plan_source_refs=plan_section.source_refs,
            preserve_structure=req.preserve_structure,
        )

        def apply_revision(record: RunRecord) -> None:
            draft = record.longform_draft
            assert draft is not None
            next_sections: list[LongFormDraftSection] = []
            for item in draft.sections:
                next_sections.append(revised if item.section_id == section_id else item)
            citations = self._collect_draft_citations(next_sections)
            record.longform_draft = LongFormDraft(
                version=max(1, draft.version + 1),
                title=draft.title,
                summary=draft.summary,
                sections=next_sections,
                citations=citations,
                stats=self._build_draft_stats(next_sections, citations),
            )
            record.longform_stage_timings.revision_ms += int(
                (time.perf_counter() - started) * 1000
            )

        await self.orch.store.update_run(run_id, apply_revision)
        await self.orch._publish(
            run_id,
            EventType.SECTION_REVISED,
            {
                "section_id": revised.section_id,
                "revision": revised.revision,
                "citation_count": len(revised.citations),
            },
        )
        updated = await self.orch.store.get_run(run_id)
        assert updated is not None and updated.longform_draft is not None
        latest = next(
            item
            for item in updated.longform_draft.sections
            if item.section_id == section_id
        )
        return LongFormSectionRevisionResponse(
            run_id=updated.run_id,
            trace_id=updated.trace_id,
            status=updated.status,
            draft_version=updated.longform_draft.version,
            section=latest,
        )

    async def start_plan(self, run_id: str) -> None:
        run = await self.orch.store.get_run(run_id)
        if run is None or getattr(run.input, "capability", "") != "content":
            return
        started = time.perf_counter()
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
            return

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
            "content_source_mode": "rag_first" if run.input.rag_source_ids else "project_all",
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

        async def on_token(token: str) -> None:
            await self.orch._publish(run_id, EventType.PLAN_TOKEN, {"token": token})

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
                    return
                continue
        if plan is None:
            await self.orch._fail_run(
                run_id,
                "PLANNING",
                "LONGFORM_PLAN_MISSING",
                retryable=True,
            )
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

    async def generate_draft(self, run_id: str) -> None:
        run = await self.orch.store.get_run(run_id)
        if run is None or getattr(run.input, "capability", "") != "content":
            return
        if run.longform_plan is None:
            await self.orch._fail_run(
                run_id, "DRAFTING", "LONGFORM_PLAN_MISSING", retryable=False
            )
            return
        started = time.perf_counter()
        rag_context_snippets = self._stored_rag_context_snippets(run)
        sections: list[LongFormDraftSection] = []
        for section in run.longform_plan.sections:
            try:
                drafted = await self.orch._call_outline_with_timeout_retry(
                    run_id=run_id,
                    phase="content.section.generate",
                    action=lambda current=section: self.orch.llm_client.generate_section_draft(
                        topic=run.input.topic,
                        project_id=run.input.project_id,
                        audience=run.input.audience,
                        purpose=run.input.purpose,
                        tone=run.input.tone,
                        plan=run.longform_plan,
                        section_id=current.section_id,
                        rag_source_ids=run.input.rag_source_ids,
                        rag_context_snippets=rag_context_snippets,
                    ),
                )
            except LongFormFormatError as exc:
                await self.orch._fail_run(
                    run_id,
                    "DRAFTING",
                    "LONGFORM_SECTION_DRAFT_INVALID",
                    retryable=True,
                    error_details={
                        "section_id": section.section_id,
                        "error_category": exc.category,
                        "error_details": exc.details,
                    },
                )
                return
            sections.append(drafted)
            await self.orch._publish(
                run_id,
                EventType.SECTION_GENERATED,
                {
                    "section_id": drafted.section_id,
                    "revision": drafted.revision,
                    "citation_count": len(drafted.citations),
                },
            )
        citations = self._collect_draft_citations(sections)
        draft = LongFormDraft(
            version=1,
            title=run.longform_plan.title,
            summary=run.longform_plan.summary,
            sections=sections,
            citations=citations,
            stats=self._build_draft_stats(sections, citations),
        )

        def apply_draft(record: RunRecord) -> None:
            record.longform_draft = draft
            record.longform_stage_timings.draft_ms = int(
                (time.perf_counter() - started) * 1000
            )

        await self.orch.store.update_run(run_id, apply_draft)
        await self.orch._finalize_run_success(
            run_id=run_id,
            from_stage="DRAFTING",
            reason="longform drafting completed",
        )

    async def _retrieve_rag_context(
        self, *, run_id: str, run: RunRecord
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        selected_file_ids = [
            str(item).strip()
            for item in (run.input.rag_source_ids or [])
            if str(item).strip()
        ]
        retrieval_mode = "selected_files" if selected_file_ids else "project_all"
        top_k = self.orch._rag_query_top_k(
            target_slide_count=run.input.target_section_count
        )
        await self.orch._publish(
            run_id,
            EventType.RAG_RETRIEVAL_STARTED,
            {
                "mode": retrieval_mode,
                "selected_file_count": len(selected_file_ids),
                "top_k": top_k,
                "query": run.input.topic,
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
            query=run.input.topic,
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

    def _stored_rag_context_snippets(self, run: RunRecord) -> list[dict[str, Any]]:
        report = run.research_report if isinstance(run.research_report, dict) else {}
        raw = report.get("rag_context_snippets", [])
        return list(raw) if isinstance(raw, list) else []

    def _collect_draft_citations(
        self, sections: list[LongFormDraftSection]
    ) -> list[str]:
        citations: list[str] = []
        seen: set[str] = set()
        for section in sections:
            for item in section.citations:
                value = str(item).strip()
                if value and value not in seen:
                    seen.add(value)
                    citations.append(value)
        return citations

    def _build_draft_stats(
        self, sections: list[LongFormDraftSection], citations: list[str]
    ) -> LongFormDraftStats:
        return LongFormDraftStats(
            section_count=len(sections),
            block_count=sum(len(section.blocks) for section in sections),
            citation_count=len(citations),
        )

    def _normalize_revised_section(
        self,
        *,
        revised: LongFormDraftSection,
        current: LongFormDraftSection,
        plan_source_refs: list[str],
        preserve_structure: bool,
    ) -> LongFormDraftSection:
        fallback_heading = current.heading
        normalized_blocks = list(revised.blocks or [])
        if preserve_structure:
            fallback_kinds = [block.kind for block in current.blocks]
            if [block.kind for block in normalized_blocks] != fallback_kinds:
                normalized_blocks = list(current.blocks)
        if not normalized_blocks:
            normalized_blocks = [
                ContentBlock(kind="heading", text=fallback_heading),
                ContentBlock(
                    kind="paragraph",
                    text=f"{fallback_heading} revision preserves the section focus.",
                ),
            ]
        citations = self._normalize_citations(
            list(revised.citations or []),
            fallbacks=[*current.citations, *plan_source_refs],
        )
        return LongFormDraftSection(
            section_id=current.section_id,
            heading=(
                current.heading
                if preserve_structure
                else (str(revised.heading or "").strip() or current.heading)
            ),
            blocks=normalized_blocks,
            citations=citations,
            revision=max(current.revision + 1, int(revised.revision or 0)),
        )

    def _normalize_citations(
        self, values: list[str], *, fallbacks: list[str]
    ) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in [*values, *fallbacks]:
            value = str(item).strip()
            if value and value not in seen:
                seen.add(value)
                normalized.append(value)
        return normalized[:6]
