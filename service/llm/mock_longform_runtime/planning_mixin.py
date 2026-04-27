from __future__ import annotations

from typing import Any

from ...models import LongFormPlan, LongFormPlanSection
from ..types import TokenCallback


class MockLongFormPlanningMixin:
    async def generate_longform_research_brief(
        self,
        *,
        topic: str,
        project_id: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, Any]],
        audience: str,
        purpose: str,
        tone: str,
        target_section_count: int,
    ) -> dict[str, Any]:
        return {
            "audience": audience,
            "purpose": purpose,
            "tone": tone,
            "narrative_arc": "context -> key ideas -> evidence -> synthesis",
            "section_focus": [
                f"Section {idx}: focus on {topic} theme {idx}"
                for idx in range(1, target_section_count + 1)
            ],
            "source_themes": [
                str(item.get("excerpt") or item.get("text", "")).strip()[:120]
                for item in rag_context_snippets[: min(3, len(rag_context_snippets))]
                if str(item.get("excerpt") or item.get("text", "")).strip()
            ],
        }

    async def generate_longform_plan(
        self,
        *,
        topic: str,
        project_id: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, Any]],
        audience: str,
        purpose: str,
        tone: str,
        target_section_count: int,
        on_token: TokenCallback,
    ) -> LongFormPlan:
        for token in ["planning", "content", topic]:
            await on_token(token + " ")
        source_refs = [
            str(item.get("chunk_id") or item.get("source_id") or f"src-{idx}")
            for idx, item in enumerate(rag_context_snippets[:2], start=1)
        ]
        sections = [
            LongFormPlanSection(
                section_id=f"section-{idx}",
                title=f"{topic} - Section {idx}",
                summary=f"Explain the {idx}th aspect of {topic}.",
                key_points=[f"{topic} point {idx}.1", f"{topic} point {idx}.2"],
                intent=f"clarify theme {idx} for {audience}",
                source_refs=list(source_refs),
            )
            for idx in range(1, target_section_count + 1)
        ]
        return LongFormPlan(
            version=1,
            title=topic,
            summary=f"Structured draft plan for {topic}",
            sections=sections,
        )

    async def repair_longform_plan(
        self,
        *,
        topic: str,
        project_id: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, Any]],
        audience: str,
        purpose: str,
        tone: str,
        target_section_count: int,
        previous_response: str,
        error_category: str,
        error_details: list[str],
    ) -> LongFormPlan:
        async def noop(_: str) -> None:
            return

        return await self.generate_longform_plan(
            topic=topic,
            project_id=project_id,
            rag_source_ids=rag_source_ids,
            rag_context_snippets=rag_context_snippets,
            audience=audience,
            purpose=purpose,
            tone=tone,
            target_section_count=target_section_count,
            on_token=noop,
        )

    async def critique_longform_plan(
        self,
        *,
        topic: str,
        audience: str,
        purpose: str,
        tone: str,
        target_section_count: int,
        plan: LongFormPlan,
    ) -> LongFormPlan:
        return plan
