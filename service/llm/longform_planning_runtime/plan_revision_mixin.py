from __future__ import annotations

import json
from typing import Any

from ...models import LongFormPlan


class LLMLongFormPlanRevisionMixin:
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
        system_prompt = (
            "You repair malformed long-form plan JSON. "
            "Return JSON only with keys: version, title, summary, sections. "
            "Each section must include: section_id, title, summary, key_points, intent, source_refs."
        )
        user_prompt = (
            f"topic={topic}\n"
            f"project_id={project_id}\n"
            f"audience={audience}\n"
            f"purpose={purpose}\n"
            f"tone={tone}\n"
            f"target_section_count={target_section_count}\n"
            f"rag_source_ids={json.dumps(rag_source_ids, ensure_ascii=False)}\n"
            f"rag_context_snippets={json.dumps(rag_context_snippets, ensure_ascii=False)}\n"
            f"error_category={error_category}\n"
            f"error_details={json.dumps(error_details, ensure_ascii=False)}\n"
            "Fix only the format/schema issues while preserving content intent.\n"
            f"previous_response=\n{previous_response[:20000]}\n"
            "Output JSON only."
        )
        response_format = self._longform_plan_response_format(
            target_section_count=target_section_count
        )
        text = await self._chat_text(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.outline_temperature,
            response_format=response_format,
            allow_response_format_fallback=True,
        )
        return self._parse_longform_plan_or_raise(
            text=text,
            topic=topic,
            target_section_count=target_section_count,
            rag_context_snippets=rag_context_snippets,
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
        system_prompt = (
            "You are a QA reviewer for structured long-form plans. "
            "Ensure the sequence is coherent, section intents are distinct, and source_refs remain concise. "
            "Return JSON only with the same schema."
        )
        user_prompt = (
            f"topic={topic}\n"
            f"audience={audience}\n"
            f"purpose={purpose}\n"
            f"tone={tone}\n"
            f"target_section_count={target_section_count}\n"
            f"plan={plan.model_dump_json()}\n"
            "Return improved plan JSON only."
        )
        response_format = self._longform_plan_response_format(
            target_section_count=target_section_count
        )
        text = await self._chat_text(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.outline_temperature,
            response_format=response_format,
            allow_response_format_fallback=True,
        )
        return self._parse_longform_plan_or_raise(
            text=text,
            topic=topic,
            target_section_count=target_section_count,
            rag_context_snippets=[],
        )
