from __future__ import annotations

import asyncio
import time
from typing import Any

from ...llm import LongFormFormatError
from ...models import ContentBlock, EventType, LongFormDraft, LongFormDraftSection, RunStatus


class ContentDraftGenerationMixin:
    orch: Any

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
                drafted = await asyncio.wait_for(
                    self.orch._call_outline_with_timeout_retry(
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
                    ),
                    timeout=max(90.0, min(240.0, float(self.orch.settings.llm_timeout_sec))),
                )
            except asyncio.TimeoutError:
                drafted = self._section_from_confirmed_plan(section)
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

        def apply_draft(record) -> None:
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

    def _section_from_confirmed_plan(self, section: Any) -> LongFormDraftSection:
        return LongFormDraftSection(
            section_id=str(section.section_id),
            heading=str(section.title),
            blocks=[
                ContentBlock(kind="heading", text=str(section.title)),
                ContentBlock(kind="paragraph", text=str(section.summary or section.title)),
                ContentBlock(
                    kind="bullet_list",
                    items=[
                        str(item).strip()
                        for item in list(section.key_points or [])
                        if str(item).strip()
                    ]
                    or [str(section.summary or section.title)],
                ),
            ],
            citations=[
                str(item).strip()
                for item in list(section.source_refs or [])
                if str(item).strip()
            ][:6],
            revision=1,
        )
