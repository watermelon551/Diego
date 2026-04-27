from __future__ import annotations

from ...models import ContentBlock, LongFormDraftSection, LongFormPlan


class MockLongFormDraftingMixin:
    async def generate_section_draft(
        self,
        *,
        topic: str,
        project_id: str,
        audience: str,
        purpose: str,
        tone: str,
        plan: LongFormPlan,
        section_id: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, object]],
    ) -> LongFormDraftSection:
        section = next(item for item in plan.sections if item.section_id == section_id)
        citations = list(section.source_refs or rag_source_ids[:2])
        return LongFormDraftSection(
            section_id=section.section_id,
            heading=section.title,
            blocks=[
                ContentBlock(kind="heading", text=section.title),
                ContentBlock(
                    kind="paragraph",
                    text=f"This section explains {section.summary or section.title} for {audience}.",
                ),
                ContentBlock(
                    kind="bullet_list", items=list(section.key_points or [section.title])
                ),
            ],
            citations=citations,
            revision=1,
        )

    async def revise_section_draft(
        self,
        *,
        topic: str,
        project_id: str,
        audience: str,
        purpose: str,
        tone: str,
        plan: LongFormPlan,
        current_section: LongFormDraftSection,
        instruction: str,
        preserve_structure: bool,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, object]],
    ) -> LongFormDraftSection:
        blocks = list(current_section.blocks)
        if preserve_structure:
            rewritten: list[ContentBlock] = []
            for block in blocks:
                if block.kind == "paragraph":
                    rewritten.append(
                        ContentBlock(
                            kind="paragraph",
                            text=f"{block.text} Revision focus: {instruction.strip()}",
                        )
                    )
                else:
                    rewritten.append(block)
            blocks = rewritten
        else:
            blocks = [
                ContentBlock(kind="heading", text=current_section.heading),
                ContentBlock(
                    kind="paragraph",
                    text=f"{current_section.heading} rewritten with instruction: {instruction.strip()}",
                ),
            ]
        return LongFormDraftSection(
            section_id=current_section.section_id,
            heading=current_section.heading,
            blocks=blocks,
            citations=list(current_section.citations or rag_source_ids[:2]),
            revision=current_section.revision + 1,
        )
