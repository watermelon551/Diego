from __future__ import annotations

import json

from ...models import OutlineDocument
from ..types import TokenCallback


class LLMOutlinePlanningMixin:
    async def generate_outline(
        self,
        *,
        topic: str,
        project_id: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, object]],
        template_style: str,
        target_slide_count: int,
        on_token: TokenCallback,
    ) -> OutlineDocument:
        system_prompt = (
            "You are a PPT planner following strict slide types. "
            "Return JSON only with keys: version, summary, nodes. "
            "Each node: title, bullets(list[str]), page_type(one of cover,toc,section,content,summary), layout_hint. "
            f"nodes length must equal {target_slide_count}. "
            "Layout hints must use skill-approved values only."
        )
        user_prompt = (
            f"topic={topic}\n"
            f"project_id={project_id}\n"
            f"template_style={template_style}\n"
            f"target_slide_count={target_slide_count}\n"
            f"rag_source_ids={json.dumps(rag_source_ids, ensure_ascii=False)}\n"
            f"rag_context_snippets={json.dumps(rag_context_snippets, ensure_ascii=False)}\n"
            "Plan varied layouts and avoid repeating adjacent layouts. Output JSON only."
        )
        response_format = self._outline_response_format(
            target_slide_count=target_slide_count
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
        return self._parse_outline_or_raise(
            text=text,
            topic=topic,
            target_slide_count=target_slide_count,
            template_style=template_style,
        )

    async def repair_outline(
        self,
        *,
        topic: str,
        project_id: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, object]],
        template_style: str,
        target_slide_count: int,
        previous_response: str,
        error_category: str,
        error_details: list[str],
    ) -> OutlineDocument:
        system_prompt = (
            "You repair malformed PPT outline JSON. "
            "Return JSON only with keys: version, summary, nodes. "
            "Each node must have: title, bullets(list[str]), page_type(one of cover,toc,section,content,summary), layout_hint."
        )
        user_prompt = (
            f"topic={topic}\n"
            f"project_id={project_id}\n"
            f"template_style={template_style}\n"
            f"target_slide_count={target_slide_count}\n"
            f"rag_source_ids={json.dumps(rag_source_ids, ensure_ascii=False)}\n"
            f"rag_context_snippets={json.dumps(rag_context_snippets, ensure_ascii=False)}\n"
            f"error_category={error_category}\n"
            f"error_details={json.dumps(error_details, ensure_ascii=False)}\n"
            "Previous invalid response below. Fix only the format/schema issues while preserving content intent.\n"
            f"previous_response=\n{previous_response[:20000]}\n"
            "Output JSON only."
        )
        response_format = self._outline_response_format(
            target_slide_count=target_slide_count
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
        return self._parse_outline_or_raise(
            text=text,
            topic=topic,
            target_slide_count=target_slide_count,
            template_style=template_style,
        )

    async def critique_outline(
        self,
        *,
        topic: str,
        template_style: str,
        target_slide_count: int,
        outline: OutlineDocument,
    ) -> OutlineDocument:
        system_prompt = (
            "You are a QA reviewer for PPT outlines. "
            "Ensure page types are well-distributed and avoid repetitive layouts. "
            "Return JSON only with the same schema. "
            "Layout hints must be valid skill layout names."
        )
        user_prompt = (
            f"topic={topic}\n"
            f"template_style={template_style}\n"
            f"target_slide_count={target_slide_count}\n"
            f"outline={outline.model_dump_json()}\n"
            "Return improved outline JSON only."
        )
        response_format = self._outline_response_format(
            target_slide_count=target_slide_count
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
        return self._parse_outline_or_raise(
            text=text,
            topic=topic,
            target_slide_count=target_slide_count,
            template_style=template_style,
        )
