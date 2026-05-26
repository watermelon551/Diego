from __future__ import annotations

import json
from typing import Any

from ..pptd_skill_guidance import (
    PPTD_SKILL_WORKFLOW_GUIDANCE,
    PPTD_VISUAL_QUALITY_GUIDANCE,
)


class LLMOutlineRequirementsMixin:
    async def generate_research_brief(
        self,
        *,
        topic: str,
        project_id: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, Any]],
        template_style: str,
        target_slide_count: int,
    ) -> dict[str, Any]:
        system_prompt = (
            "You are a presentation research planner. "
            "Return JSON only with keys: audience, purpose, tone, narrative_arc, page_focus(list[str]), "
            "design_notes(list[str]), style_intent, effective_template_style, scenario_profile, visual_mode, content_mode, "
            "density_guidance, font_guidance, risk_prohibitions(list[str]). "
            "When rag_context_snippets is non-empty, ground page_focus and design_notes in that evidence."
            f"\n\n{PPTD_SKILL_WORKFLOW_GUIDANCE}"
        )
        user_prompt = (
            f"topic={topic}\n"
            f"project_id={project_id}\n"
            f"template_style={template_style}\n"
            f"target_slide_count={target_slide_count}\n"
            f"rag_source_ids={json.dumps(rag_source_ids, ensure_ascii=False)}\n"
            f"rag_context_snippets={json.dumps(rag_context_snippets, ensure_ascii=False)}\n"
            "Provide concise, practical planning guidance."
        )
        text = await self._chat_text(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.outline_temperature,
        )
        payload = await self._extract_json_object_with_repair(
            text=text,
            expected_keys=[
                "audience",
                "purpose",
                "tone",
                "narrative_arc",
                "page_focus",
                "design_notes",
                "style_intent",
                "effective_template_style",
                "scenario_profile",
                "visual_mode",
                "content_mode",
                "density_guidance",
                "font_guidance",
                "risk_prohibitions",
            ],
            temperature=self.outline_temperature,
        )
        page_focus = payload.get("page_focus", [])
        if not isinstance(page_focus, list):
            page_focus = []
        notes = payload.get("design_notes", [])
        if not isinstance(notes, list):
            notes = []
        risk_prohibitions = payload.get("risk_prohibitions", [])
        if not isinstance(risk_prohibitions, list):
            risk_prohibitions = []
        return {
            "audience": str(payload.get("audience", "")).strip() or "general",
            "purpose": str(payload.get("purpose", "")).strip() or "inform",
            "tone": str(payload.get("tone", "")).strip() or "professional",
            "narrative_arc": str(payload.get("narrative_arc", "")).strip()
            or "problem -> analysis -> solution -> summary",
            "page_focus": [
                str(item).strip() for item in page_focus if str(item).strip()
            ][:target_slide_count],
            "design_notes": [str(item).strip() for item in notes if str(item).strip()][
                :8
            ],
            "style_intent": str(payload.get("style_intent", "")).strip(),
            "effective_template_style": str(
                payload.get("effective_template_style", "")
            ).strip(),
            "scenario_profile": str(payload.get("scenario_profile", "")).strip(),
            "visual_mode": str(payload.get("visual_mode", "")).strip(),
            "content_mode": str(payload.get("content_mode", "")).strip(),
            "density_guidance": str(payload.get("density_guidance", "")).strip(),
            "font_guidance": str(payload.get("font_guidance", "")).strip(),
            "risk_prohibitions": [
                str(item).strip() for item in risk_prohibitions if str(item).strip()
            ][:8],
        }

    async def generate_design_intent(
        self,
        *,
        topic: str,
        template_style: str,
        target_slide_count: int,
        research_brief: dict[str, Any],
    ) -> dict[str, Any]:
        system_prompt = (
            "You are a presentation design director. Return JSON only with keys: "
            "palette_name, style_recipe, title_font, body_font, visual_strategy, density, rationale."
            f"\n\n{PPTD_VISUAL_QUALITY_GUIDANCE}"
        )
        user_prompt = (
            f"topic={topic}\n"
            f"template_style={template_style}\n"
            f"target_slide_count={target_slide_count}\n"
            f"research_brief={json.dumps(research_brief, ensure_ascii=False)}\n"
            "Select a coherent design system that matches audience, tone, and narrative arc."
        )
        text = await self._chat_text(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.outline_temperature,
        )
        payload = await self._extract_json_object_with_repair(
            text=text,
            expected_keys=[
                "palette_name",
                "style_recipe",
                "title_font",
                "body_font",
                "visual_strategy",
                "density",
                "rationale",
            ],
            temperature=self.outline_temperature,
        )
        return {
            "palette_name": str(payload.get("palette_name", "")).strip(),
            "style_recipe": str(payload.get("style_recipe", "")).strip(),
            "title_font": str(payload.get("title_font", "")).strip(),
            "body_font": str(payload.get("body_font", "")).strip(),
            "visual_strategy": str(payload.get("visual_strategy", "")).strip(),
            "density": str(payload.get("density", "")).strip(),
            "rationale": str(payload.get("rationale", "")).strip(),
        }
