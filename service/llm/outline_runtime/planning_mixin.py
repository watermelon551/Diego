from __future__ import annotations

import json

from ...models import OutlineDocument
from ..types import TokenCallback
from ..pptd_skill_guidance import (
    PPTD_OUTLINE_QUALITY_GUIDANCE,
    PPTD_SKILL_WORKFLOW_GUIDANCE,
)


class LLMOutlinePlanningMixin:
    async def generate_outline(
        self,
        *,
        topic: str,
        project_id: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, object]],
        template_style: str,
        requirements_report: dict[str, object] | None = None,
        target_slide_count: int,
        on_token: TokenCallback,
    ) -> OutlineDocument:
        skill_plan = self._pptd_skill_planning_context(requirements_report)
        system_prompt = (
            "You are a PPT planner following strict slide types. "
            "Return JSON only with keys: version, summary, nodes. "
            "Each node: title, bullets(list[str]), page_type(one of cover,toc,section,content,summary), layout_hint. "
            f"nodes length must equal {target_slide_count}. "
            "Layout hints must use skill-approved values only."
            f"\n\n{PPTD_SKILL_WORKFLOW_GUIDANCE}\n\n{PPTD_OUTLINE_QUALITY_GUIDANCE}"
        )
        user_prompt = (
            f"topic={topic}\n"
            f"project_id={project_id}\n"
            f"template_style={template_style}\n"
            f"target_slide_count={target_slide_count}\n"
            f"requirements_report={json.dumps(skill_plan, ensure_ascii=False)}\n"
            f"rag_source_ids={json.dumps(rag_source_ids, ensure_ascii=False)}\n"
            f"rag_context_snippets={json.dumps(rag_context_snippets, ensure_ascii=False)}\n"
            "Use requirements_report as the design/content contract: audience, scenario_profile, visual_mode, content_mode, density, prohibitions, and page_focus must guide the outline. "
            "Plan varied layouts and avoid repeating adjacent layouts. "
            "When target_slide_count is small, compress the complete narrative into those pages instead of producing generic summaries. "
            "For decks with 4 or fewer pages, do not insert a table-of-contents page unless the user explicitly asks for one; use content pages for core knowledge instead. "
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
        requirements_report: dict[str, object] | None = None,
        target_slide_count: int,
        previous_response: str,
        error_category: str,
        error_details: list[str],
    ) -> OutlineDocument:
        skill_plan = self._pptd_skill_planning_context(requirements_report)
        system_prompt = (
            "You repair malformed PPT outline JSON. "
            "Return JSON only with keys: version, summary, nodes. "
            "Each node must have: title, bullets(list[str]), page_type(one of cover,toc,section,content,summary), layout_hint."
            f"\n\n{PPTD_OUTLINE_QUALITY_GUIDANCE}"
        )
        user_prompt = (
            f"topic={topic}\n"
            f"project_id={project_id}\n"
            f"template_style={template_style}\n"
            f"target_slide_count={target_slide_count}\n"
            f"requirements_report={json.dumps(skill_plan, ensure_ascii=False)}\n"
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
        requirements_report: dict[str, object] | None = None,
    ) -> OutlineDocument:
        skill_plan = self._pptd_skill_planning_context(requirements_report)
        system_prompt = (
            "You are a QA reviewer for PPT outlines. "
            "Ensure page types are well-distributed and avoid repetitive layouts. "
            "Return JSON only with the same schema. "
            "Layout hints must be valid skill layout names."
            f"\n\n{PPTD_OUTLINE_QUALITY_GUIDANCE}"
        )
        user_prompt = (
            f"topic={topic}\n"
            f"template_style={template_style}\n"
            f"target_slide_count={target_slide_count}\n"
            f"requirements_report={json.dumps(skill_plan, ensure_ascii=False)}\n"
            f"outline={outline.model_dump_json()}\n"
            "Preserve the requirements_report contract while improving page roles, layout variety, and source-grounded focus. "
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

    def _pptd_skill_planning_context(
        self, requirements_report: dict[str, object] | None
    ) -> dict[str, object]:
        report = requirements_report if isinstance(requirements_report, dict) else {}
        design_intent_raw = report.get("design_intent")
        design_intent = design_intent_raw if isinstance(design_intent_raw, dict) else {}
        allowed_keys = {
            "audience",
            "purpose",
            "tone",
            "narrative_arc",
            "page_focus",
            "design_notes",
            "style_intent",
            "effective_template_style",
            "requirements_mode",
            "scenario_profile",
            "visual_mode",
            "content_mode",
            "density_guidance",
            "font_guidance",
            "risk_prohibitions",
        }
        context = {key: report[key] for key in allowed_keys if key in report}
        if design_intent:
            context["design_intent"] = {
                key: design_intent[key]
                for key in (
                    "palette_name",
                    "style_recipe",
                    "visual_strategy",
                    "density",
                    "layout_family",
                    "density_profile",
                    "visual_strategy_profile",
                    "rationale",
                )
                if key in design_intent
            }
        return context
