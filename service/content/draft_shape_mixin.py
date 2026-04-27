from __future__ import annotations

from typing import Any

from ..models import ContentBlock, LongFormDraftSection, LongFormDraftStats


class ContentDraftShapeMixin:
    orch: Any

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
