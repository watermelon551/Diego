from __future__ import annotations

import json
from typing import Any

from ...models import LongFormPlan
from ..types import TokenCallback


class LLMLongFormPlanGenerationMixin:
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
        system_prompt = (
            "You are a structured long-form planner. "
            "Return JSON only with keys: version, title, summary, sections. "
            "Each section must include: section_id, title, summary, key_points(list[str]), intent, source_refs(list[str])."
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
            "Plan a source-aware long-form draft. Output JSON only."
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
        for token in text.split():
            await on_token(token + " ")
        return self._parse_longform_plan_or_raise(
            text=text,
            topic=topic,
            target_section_count=target_section_count,
            rag_context_snippets=rag_context_snippets,
        )
