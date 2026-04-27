from __future__ import annotations

import time
from typing import Any

from ...llm import LongFormFormatError
from ...models import (
    EventType,
    LongFormDraft,
    LongFormDraftSection,
    LongFormSectionRevisionResponse,
    ReviseLongFormSectionRequest,
    RunRecord,
    RunStatus,
)


class ContentDraftRevisionMixin:
    orch: Any

    async def revise_section(
        self, run_id: str, section_id: str, req: ReviseLongFormSectionRequest
    ) -> LongFormSectionRevisionResponse | None:
        run = await self.orch.store.get_run(run_id)
        if run is None or getattr(run.input, "capability", "") != "content":
            return None
        if str(getattr(run.input, "content_kind", "")) != "longform_draft":
            raise ValueError("section revision is only available for longform_draft")
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
            (item for item in run.longform_plan.sections if item.section_id == section_id),
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
