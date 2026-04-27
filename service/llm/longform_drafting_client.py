from __future__ import annotations

import json
from typing import Any

from ..models import LongFormDraftSection, LongFormPlan


class LLMLongFormDraftingMixin:
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
        rag_context_snippets: list[dict[str, Any]],
    ) -> LongFormDraftSection:
        section = next(item for item in plan.sections if item.section_id == section_id)
        system_prompt = (
            "You draft one structured long-form section. "
            "Return JSON only with keys: section_id, heading, blocks, citations, revision. "
            "blocks items must use kind in heading|paragraph|bullet_list|quote with either text or items."
        )
        user_prompt = (
            f"topic={topic}\n"
            f"project_id={project_id}\n"
            f"audience={audience}\n"
            f"purpose={purpose}\n"
            f"tone={tone}\n"
            f"section={section.model_dump_json()}\n"
            f"rag_source_ids={json.dumps(rag_source_ids, ensure_ascii=False)}\n"
            f"rag_context_snippets={json.dumps(rag_context_snippets, ensure_ascii=False)}\n"
            "Draft a clear, source-aware section with one heading, one paragraph, and one bullet_list at minimum."
        )
        text = await self._chat_text(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.slide_temperature,
            response_format=self._longform_section_response_format(),
            allow_response_format_fallback=True,
        )
        return self._parse_longform_section_or_raise(
            text=text,
            section_id=section.section_id,
            heading=section.title,
            key_points=section.key_points,
            source_refs=section.source_refs,
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
        rag_context_snippets: list[dict[str, Any]],
    ) -> LongFormDraftSection:
        system_prompt = (
            "You revise one structured long-form section. "
            "Return JSON only with keys: section_id, heading, blocks, citations, revision."
        )
        user_prompt = (
            f"topic={topic}\n"
            f"project_id={project_id}\n"
            f"audience={audience}\n"
            f"purpose={purpose}\n"
            f"tone={tone}\n"
            f"preserve_structure={json.dumps(preserve_structure)}\n"
            f"instruction={instruction}\n"
            f"plan={plan.model_dump_json()}\n"
            f"current_section={current_section.model_dump_json()}\n"
            f"rag_source_ids={json.dumps(rag_source_ids, ensure_ascii=False)}\n"
            f"rag_context_snippets={json.dumps(rag_context_snippets, ensure_ascii=False)}\n"
            "Apply the instruction while keeping citations concise and section-scoped."
        )
        text = await self._chat_text(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.slide_temperature,
            response_format=self._longform_section_response_format(),
            allow_response_format_fallback=True,
        )
        revised = self._parse_longform_section_or_raise(
            text=text,
            section_id=current_section.section_id,
            heading=current_section.heading,
            key_points=[],
            source_refs=current_section.citations,
        )
        if revised.revision <= current_section.revision:
            revised.revision = current_section.revision + 1
        return revised
