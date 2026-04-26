from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import ValidationError

from ..models import (
    ContentBlock,
    LongFormDraftSection,
    LongFormPlan,
    LongFormPlanSection,
    OutlineDocument,
    OutlineNode,
    SlidePageType,
    VisualPolicy,
)
from ..design.skill_profile import allowed_layouts_for, enforce_layout_variety
from ..design.style_catalog import resolve_style_dna_choice
from .parsing import _extract_code_block, _extract_js_module, _extract_json_object, _normalize_page_type, _sanitize_llm_text
from .types import (
    GeneratedSlide,
    LLMEmptyResponseError,
    LLMTimeoutError,
    LongFormFormatError,
    OutlineFormatError,
    SlideSpec,
    TokenCallback,
)

class OpenAICompatibleLLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        api_style: str = "openai_chat",
        timeout_sec: float = 60.0,
        outline_temperature: float = 0.3,
        slide_temperature: float = 0.6,
        outline_structured_output: bool = True,
        sanitize_think_tags: bool = True,
        json_repair_retry: int = 1,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.api_style = api_style
        self.timeout_sec = timeout_sec
        self.outline_temperature = outline_temperature
        self.slide_temperature = slide_temperature
        self.outline_structured_output = outline_structured_output
        self.sanitize_think_tags = bool(sanitize_think_tags)
        self.json_repair_retry = max(0, int(json_repair_retry))

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
            "design_notes(list[str]), style_intent, effective_template_style. "
            "When rag_context_snippets is non-empty, ground page_focus and design_notes in that evidence."
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
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=self.outline_temperature,
        )
        payload = await self._extract_json_object_with_repair(
            text=text,
            expected_keys=["score", "issues", "repair_directives"],
            temperature=self.outline_temperature,
        )
        page_focus = payload.get("page_focus", [])
        if not isinstance(page_focus, list):
            page_focus = []
        notes = payload.get("design_notes", [])
        if not isinstance(notes, list):
            notes = []
        return {
            "audience": str(payload.get("audience", "")).strip() or "general",
            "purpose": str(payload.get("purpose", "")).strip() or "inform",
            "tone": str(payload.get("tone", "")).strip() or "professional",
            "narrative_arc": str(payload.get("narrative_arc", "")).strip() or "problem -> analysis -> solution -> summary",
            "page_focus": [str(item).strip() for item in page_focus if str(item).strip()][:target_slide_count],
            "design_notes": [str(item).strip() for item in notes if str(item).strip()][:8],
            "style_intent": str(payload.get("style_intent", "")).strip(),
            "effective_template_style": str(payload.get("effective_template_style", "")).strip(),
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
        )
        user_prompt = (
            f"topic={topic}\n"
            f"template_style={template_style}\n"
            f"target_slide_count={target_slide_count}\n"
            f"research_brief={json.dumps(research_brief, ensure_ascii=False)}\n"
            "Select a coherent design system that matches audience, tone, and narrative arc."
        )
        text = await self._chat_text(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=self.outline_temperature,
        )
        payload = await self._extract_json_object_with_repair(
            text=text,
            expected_keys=["score", "issues", "repair_directives"],
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
        system_prompt = (
            "You are a long-form drafting research planner. "
            "Return JSON only with keys: audience, purpose, tone, narrative_arc, section_focus(list[str]), source_themes(list[str]). "
            "Ground section_focus and source_themes in rag_context_snippets when present."
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
            "Provide concise planning guidance for a structured long-form draft."
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
                "section_focus",
                "source_themes",
            ],
            temperature=self.outline_temperature,
        )
        section_focus = payload.get("section_focus", [])
        source_themes = payload.get("source_themes", [])
        if not isinstance(section_focus, list):
            section_focus = []
        if not isinstance(source_themes, list):
            source_themes = []
        return {
            "audience": str(payload.get("audience", "")).strip() or audience,
            "purpose": str(payload.get("purpose", "")).strip() or purpose,
            "tone": str(payload.get("tone", "")).strip() or tone,
            "narrative_arc": str(payload.get("narrative_arc", "")).strip()
            or "context -> key ideas -> evidence -> synthesis",
            "section_focus": [
                str(item).strip() for item in section_focus if str(item).strip()
            ][:target_section_count],
            "source_themes": [
                str(item).strip() for item in source_themes if str(item).strip()
            ][:8],
        }

    async def generate_outline(
        self,
        *,
        topic: str,
        project_id: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, Any]],
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
        response_format = self._outline_response_format(target_slide_count=target_slide_count)
        text = await self._chat_text(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.outline_temperature,
            response_format=response_format,
            allow_response_format_fallback=True,
        )
        # Maintain token event compatibility for CLI/event consumers.
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
        rag_context_snippets: list[dict[str, Any]],
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
        response_format = self._outline_response_format(target_slide_count=target_slide_count)
        text = await self._chat_text(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
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
        response_format = self._outline_response_format(target_slide_count=target_slide_count)
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
        section = next(
            item for item in plan.sections if item.section_id == section_id
        )
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

    async def generate_slide(
        self,
        *,
        topic: str,
        project_id: str,
        template_style: str,
        slide_no: int,
        target_slide_count: int,
        outline_node: OutlineNode,
        rag_source_ids: list[str],
    ) -> GeneratedSlide:
        system_prompt = (
            "You are a PPT slide content writer. "
            "Return JSON with keys: title, bullets(list[str]), citations(list[str]), page_type, layout_hint. "
            "Never use placeholder wording."
        )
        user_prompt = (
            f"topic={topic}\nproject_id={project_id}\ntemplate_style={template_style}\n"
            f"slide_no={slide_no}\ntarget_slide_count={target_slide_count}\n"
            f"outline_node={outline_node.model_dump_json()}\n"
            f"rag_source_ids={json.dumps(rag_source_ids, ensure_ascii=False)}\n"
            "Output JSON only."
        )
        text = await self._chat_text(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=self.slide_temperature,
        )
        return self._parse_generated_slide(text=text, fallback=outline_node)

    async def review_slide(
        self,
        *,
        topic: str,
        template_style: str,
        slide_no: int,
        target_slide_count: int,
        outline_node: OutlineNode,
        candidate: GeneratedSlide,
        rule_violations: list[str],
    ) -> GeneratedSlide:
        system_prompt = (
            "You are a PPT quality reviewer. "
            "Fix slide content to satisfy style/clarity rules and return JSON with same keys. "
            "Do not output placeholders."
        )
        user_prompt = (
            f"topic={topic}\ntemplate_style={template_style}\nslide_no={slide_no}\n"
            f"target_slide_count={target_slide_count}\noutline_node={outline_node.model_dump_json()}\n"
            f"candidate={json.dumps(candidate.__dict__, ensure_ascii=False)}\n"
            f"rule_violations={json.dumps(rule_violations, ensure_ascii=False)}\n"
            "Output corrected JSON only."
        )
        text = await self._chat_text(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=self.slide_temperature,
        )
        return self._parse_generated_slide(text=text, fallback=outline_node)

    async def generate_slide_js(
        self,
        *,
        topic: str,
        template_style: str,
        slide_no: int,
        target_slide_count: int,
        outline_node: OutlineNode,
        theme: dict[str, str],
        title_font: str,
        body_font: str,
        rag_source_ids: list[str],
        visual_policy: VisualPolicy = VisualPolicy.AUTO,
        slide_plan: dict[str, Any] | None = None,
        slide_brief: dict[str, Any] | None = None,
    ) -> str:
        style_dna_payload = {}
        if isinstance(slide_brief, dict) and isinstance(slide_brief.get("style_dna"), dict):
            style_dna_payload = dict(slide_brief.get("style_dna", {}))
        system_prompt = (
            "You are a PPT code agent. Return JavaScript only (no markdown fences) for one runnable slide module. "
            "Must export synchronous createSlide(pres, theme) and slideConfig exactly. "
            "Use only theme keys: primary, secondary, accent, light, bg. "
            "API whitelist: use slide.background = { color: theme.bg }; use addShape with pres.shapes.* only; use fit: 'shrink' as plain string. "
            "API blacklist: NEVER use ShapeType.*, slide.shapes.*, slide.background(...), pres.Fit.*, addGroup(), async createSlide(). "
            "Hard layout constraints: body text left-aligned, title clearly dominates body text, content slides include non-text visuals, "
            "safe margins/spacing, and avoid overlaps/out-of-bounds. "
            "Treat style_dna as authoritative visual direction and allow structural composition changes to match it. "
            "Never output placeholders, pseudo code, or markdown fences."
        )
        user_prompt = (
            f"topic={topic}\n"
            f"template_style={template_style}\n"
            f"slide_no={slide_no}\n"
            f"target_slide_count={target_slide_count}\n"
            f"outline_node={outline_node.model_dump_json()}\n"
            f"theme={json.dumps(theme, ensure_ascii=False)}\n"
            f"title_font={title_font}\n"
            f"body_font={body_font}\n"
            f"rag_source_ids={json.dumps(rag_source_ids, ensure_ascii=False)}\n"
            f"visual_policy={visual_policy.value}\n"
            f"slide_plan={json.dumps(slide_plan or {}, ensure_ascii=False)}\n"
            f"slide_brief={json.dumps(slide_brief or {}, ensure_ascii=False)}\n"
            f"style_dna={json.dumps(style_dna_payload, ensure_ascii=False)}\n"
            "If slide_plan.api_contract is present, treat it as the highest-priority runtime contract.\n"
            "Requirements: LAYOUT_16x9; title 36pt+ (or equivalent dominant scale); "
            "body paragraphs/lists left-aligned; content slides include >=1 non-text visual; "
            "respect slide_plan.constraints and style_dna density/layout family before generic defaults; "
            "fit:'shrink' on title and long body text; natural-language content only. "
            "Use addPageBadge(pres, slide, theme, slideConfig.index) on non-cover slides at x:9.3, y:5.1. "
            "If using LINE shape, keep positive w/h (never zero). "
            "When slide_plan.visual_plan.assets is present: MUST call slide.addImage({ path|data, ...options }) using object-literal signature only; "
            "MUST consume slot='main' asset path in createSlide; slot='secondary' is optional; "
            "MUST NOT leave image placeholder labels such as [主视觉图像], [辅助图像], [流程图], [示意图], [image placeholder]."
        )
        text = await self._chat_text(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=self.slide_temperature,
        )
        return _extract_js_module(text)

    async def critique_slide_js(
        self,
        *,
        topic: str,
        template_style: str,
        slide_no: int,
        target_slide_count: int,
        outline_node: OutlineNode,
        candidate_js: str,
        issues: list[str],
        failure_context: dict[str, Any] | None = None,
        visual_policy: VisualPolicy = VisualPolicy.AUTO,
        slide_plan: dict[str, Any] | None = None,
        repair_directives: list[str] | None = None,
        preview_text: str = "",
        slide_brief: dict[str, Any] | None = None,
    ) -> str:
        style_dna_payload = {}
        if isinstance(slide_brief, dict) and isinstance(slide_brief.get("style_dna"), dict):
            style_dna_payload = dict(slide_brief.get("style_dna", {}))
        system_prompt = (
            "You are a strict PPT code reviewer. Rewrite and return full JavaScript module only. "
            "Keep createSlide synchronous and keep module export contract exact. Fix all listed issues while preserving content intent. "
            "Prioritize hard constraints first: compile/API legality, bounds/overlap, page badge, visual policy, then typography/spacing. "
            "Never use ShapeType.*, slide.shapes.*, slide.background(...), pres.Fit.*, addGroup(), or zero-length LINE geometry. "
            "You may do structural layout re-composition when it improves style_dna alignment while keeping narrative intent."
        )
        user_prompt = (
            f"topic={topic}\n"
            f"template_style={template_style}\n"
            f"slide_no={slide_no}\n"
            f"target_slide_count={target_slide_count}\n"
            f"outline_node={outline_node.model_dump_json()}\n"
            f"issues={json.dumps(issues, ensure_ascii=False)}\n"
            f"failure_context={json.dumps(failure_context or {}, ensure_ascii=False)}\n"
            f"repair_directives={json.dumps(repair_directives or [], ensure_ascii=False)}\n"
            f"visual_policy={visual_policy.value}\n"
            f"slide_plan={json.dumps(slide_plan or {}, ensure_ascii=False)}\n"
            f"slide_brief={json.dumps(slide_brief or {}, ensure_ascii=False)}\n"
            f"style_dna={json.dumps(style_dna_payload, ensure_ascii=False)}\n"
            f"preview_text={preview_text[:2000]}\n"
            "Follow slide_plan.api_contract exactly when present.\n"
            "If failure_context includes compile/runtime diagnostics, treat them as authoritative and fix them first. "
            "Example: pres.shapes.ELLIPSE is invalid in PptxGenJS, use pres.shapes.OVAL.\n"
            "When failure_context contains line numbers/focus windows, patch those lines first, then re-compose if style_dna requires it.\n"
            "Must satisfy: body text left-aligned, clear title/body size contrast, fit:'shrink' on title and long body text, "
            "safe margins and spacing, content slide must keep non-text visual element, non-cover slides must include page badge.\n"
            "When slide_plan.visual_plan.assets is present, preserve slot semantics and enforce strict image contract:\n"
            "- use slide.addImage({ path|data, ...opts }) object form only\n"
            "- consume slot='main' asset in createSlide\n"
            "- remove image placeholder labels and replace with actual addImage usage\n"
            f"candidate_js=\n{candidate_js}\n"
        )
        text = await self._chat_text(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=self.slide_temperature,
        )
        return _extract_js_module(text)

    async def generate_slide_spec(
        self,
        *,
        topic: str,
        template_style: str,
        slide_no: int,
        target_slide_count: int,
        outline_node: OutlineNode,
        rag_source_ids: list[str],
        visual_policy: VisualPolicy = VisualPolicy.AUTO,
        slide_plan: dict[str, Any] | None = None,
        slide_brief: dict[str, Any] | None = None,
    ) -> SlideSpec:
        system_prompt = (
            "You are a PPT slide planner following skill-level constraints. "
            "Return JSON only with keys: title, subtitle, bullets, page_type, layout_hint, visual_kind, emphasis, citations. "
            "Do not output JavaScript, markdown fences, pseudo code, or placeholders."
        )
        user_prompt = (
            f"topic={topic}\n"
            f"template_style={template_style}\n"
            f"slide_no={slide_no}\n"
            f"target_slide_count={target_slide_count}\n"
            f"outline_node={outline_node.model_dump_json()}\n"
            f"rag_source_ids={json.dumps(rag_source_ids, ensure_ascii=False)}\n"
            f"visual_policy={visual_policy.value}\n"
            f"slide_plan={json.dumps(slide_plan or {}, ensure_ascii=False)}\n"
            f"slide_brief={json.dumps(slide_brief or {}, ensure_ascii=False)}\n"
            "Hard constraints:\n"
            "- natural language only, concise and specific; no API names/code snippets\n"
            "- keep strong title/body hierarchy intent (title short, bullets informative)\n"
            "- bullets: 3-6 preferred on content pages, avoid empty fluff\n"
            "- respect layout_hint/page_type and keep citations as short source ids\n"
            "- visual_kind in {image, chart, shape}; if visual_policy=media_required use image; if basic_graphics_only avoid image"
        )
        response_format = self._slide_spec_response_format()
        text = await self._chat_text(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=self.slide_temperature,
            response_format=response_format,
            allow_response_format_fallback=True,
        )
        payload = await self._extract_json_object_with_repair(
            text=text,
            expected_keys=["title", "subtitle", "bullets", "page_type", "layout_hint", "visual_kind", "emphasis", "citations"],
            temperature=self.slide_temperature,
        )
        return self._parse_slide_spec(text=json.dumps(payload, ensure_ascii=False), fallback=outline_node)

    async def repair_slide_spec(
        self,
        *,
        topic: str,
        template_style: str,
        slide_no: int,
        target_slide_count: int,
        outline_node: OutlineNode,
        previous_spec: SlideSpec,
        issues: list[str],
        repair_directives: list[str] | None = None,
        visual_policy: VisualPolicy = VisualPolicy.AUTO,
        slide_plan: dict[str, Any] | None = None,
        slide_brief: dict[str, Any] | None = None,
    ) -> SlideSpec:
        system_prompt = (
            "You repair PPT slide specs under strict quality constraints. "
            "Return JSON only with keys: title, subtitle, bullets, page_type, layout_hint, visual_kind, emphasis, citations. "
            "Do not output JavaScript or explanations."
        )
        user_prompt = (
            f"topic={topic}\n"
            f"template_style={template_style}\n"
            f"slide_no={slide_no}\n"
            f"target_slide_count={target_slide_count}\n"
            f"outline_node={outline_node.model_dump_json()}\n"
            f"previous_spec={json.dumps(previous_spec.__dict__, ensure_ascii=False)}\n"
            f"issues={json.dumps(issues, ensure_ascii=False)}\n"
            f"repair_directives={json.dumps(repair_directives or [], ensure_ascii=False)}\n"
            f"visual_policy={visual_policy.value}\n"
            f"slide_plan={json.dumps(slide_plan or {}, ensure_ascii=False)}\n"
            f"slide_brief={json.dumps(slide_brief or {}, ensure_ascii=False)}\n"
            "Repair goals:\n"
            "- keep intent, but make text clearer and denser where needed\n"
            "- remove vague filler and any non-natural-language artifacts\n"
            "- keep layout/page type valid and match visual policy constraints\n"
            "- if issues mention overflow/fit/spacing, shorten bullets and prioritize readability"
        )
        response_format = self._slide_spec_response_format()
        text = await self._chat_text(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=self.slide_temperature,
            response_format=response_format,
            allow_response_format_fallback=True,
        )
        payload = await self._extract_json_object_with_repair(
            text=text,
            expected_keys=["title", "subtitle", "bullets", "page_type", "layout_hint", "visual_kind", "emphasis", "citations"],
            temperature=self.slide_temperature,
        )
        return self._parse_slide_spec(text=json.dumps(payload, ensure_ascii=False), fallback=outline_node)

    async def evaluate_slide_quality(
        self,
        *,
        topic: str,
        template_style: str,
        slide_no: int,
        target_slide_count: int,
        outline_node: OutlineNode,
        candidate_js: str,
        preview_text: str,
        hard_issues: list[str],
        visual_policy: VisualPolicy = VisualPolicy.AUTO,
        slide_brief: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        system_prompt = (
            "You are a strict PPT slide QA judge. "
            "Return JSON only with keys: score(0-100 int), issues(list[str]), repair_directives(list[str]). "
            "Judge against concrete constraints: title/body hierarchy, left-aligned body text, safe margins, block spacing, no overflow/overlap, "
            "required non-text visual elements on content slides, and natural-language quality. "
            "repair_directives must be specific code-edit instructions."
        )
        user_prompt = (
            f"topic={topic}\n"
            f"template_style={template_style}\n"
            f"slide_no={slide_no}\n"
            f"target_slide_count={target_slide_count}\n"
            f"outline_node={outline_node.model_dump_json()}\n"
            f"visual_policy={visual_policy.value}\n"
            f"hard_issues={json.dumps(hard_issues, ensure_ascii=False)}\n"
            f"slide_brief={json.dumps(slide_brief or {}, ensure_ascii=False)}\n"
            f"preview_text={preview_text[:2000]}\n"
            f"candidate_js=\n{candidate_js[:16000]}\n"
        )
        text = await self._chat_text(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=self.outline_temperature,
        )
        payload = await self._extract_json_object_with_repair(
            text=text,
            expected_keys=["score", "issues", "repair_directives"],
            temperature=self.outline_temperature,
        )
        raw_score = payload.get("score", 0)
        try:
            score = int(raw_score)
        except (TypeError, ValueError):
            score = 0
        score = max(0, min(100, score))
        issues_raw = payload.get("issues", [])
        if not isinstance(issues_raw, list):
            issues_raw = []
        directives_raw = payload.get("repair_directives", [])
        if not isinstance(directives_raw, list):
            directives_raw = []
        issues = [str(item).strip() for item in issues_raw if str(item).strip()]
        directives = [str(item).strip() for item in directives_raw if str(item).strip()]
        return {"score": score, "issues": issues, "repair_directives": directives}

    def _parse_generated_slide(self, *, text: str, fallback: OutlineNode) -> GeneratedSlide:
        payload = _extract_json_object(text)
        title = str(payload.get("title", "")).strip() or fallback.title
        bullets_raw = payload.get("bullets", [])
        if not isinstance(bullets_raw, list):
            bullets_raw = []
        bullets = [str(item).strip() for item in bullets_raw if str(item).strip()]
        if not bullets:
            bullets = fallback.bullets or [f"{title} point 1", f"{title} point 2"]

        citations_raw = payload.get("citations", [])
        if not isinstance(citations_raw, list):
            citations_raw = []
        citations = [str(item).strip() for item in citations_raw if str(item).strip()]
        page_type = _normalize_page_type(str(payload.get("page_type", "")))
        layout_hint = self._normalize_layout_hint(
            raw=str(payload.get("layout_hint", "")).strip(),
            page_type=page_type,
            fallback=fallback.layout_hint,
        )
        return GeneratedSlide(
            title=title,
            bullets=bullets,
            citations=citations,
            page_type=page_type,
            layout_hint=layout_hint,
        )

    def _parse_slide_spec(self, *, text: str, fallback: OutlineNode) -> SlideSpec:
        payload = _extract_json_object(text)
        title = str(payload.get("title", "")).strip() or fallback.title
        subtitle = str(payload.get("subtitle", "")).strip()
        emphasis = str(payload.get("emphasis", "")).strip()
        bullets_raw = payload.get("bullets", [])
        if not isinstance(bullets_raw, list):
            bullets_raw = []
        bullets = [str(item).strip() for item in bullets_raw if str(item).strip()]
        if not bullets:
            bullets = list(fallback.bullets) if fallback.bullets else [f"{title} point 1", f"{title} point 2"]
        citations_raw = payload.get("citations", [])
        if not isinstance(citations_raw, list):
            citations_raw = []
        citations = [str(item).strip() for item in citations_raw if str(item).strip()]
        page_type = _normalize_page_type(str(payload.get("page_type", ""))) or fallback.page_type
        layout_hint = self._normalize_layout_hint(
            raw=str(payload.get("layout_hint", "")).strip(),
            page_type=page_type,
            fallback=fallback.layout_hint,
        )
        visual_kind = str(payload.get("visual_kind", "")).strip().lower()
        if visual_kind not in {"image", "chart", "shape"}:
            visual_kind = "shape"
        return SlideSpec(
            title=title,
            subtitle=subtitle,
            bullets=bullets,
            page_type=page_type,
            layout_hint=layout_hint,
            visual_kind=visual_kind,
            emphasis=emphasis,
            citations=citations,
        )

    async def _extract_json_object_with_repair(
        self,
        *,
        text: str,
        expected_keys: list[str],
        temperature: float,
    ) -> dict[str, Any]:
        try:
            return _extract_json_object(text)
        except Exception as exc:
            last_exc: Exception = exc

        if self.json_repair_retry <= 0:
            raise last_exc

        expected = ", ".join(expected_keys)
        prompt = (
            "Return one valid JSON object only. Do not include markdown fences, explanations, or tags.\n"
            f"Required keys: {expected}\n"
            f"Previous parse error: {str(last_exc)[:500]}\n"
            f"Raw model output:\n{text[:20000]}"
        )
        repaired_text = text
        for _ in range(self.json_repair_retry):
            repaired_text = await self._chat_text(
                messages=[
                    {"role": "system", "content": "You are a strict JSON repair assistant."},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
            )
            try:
                return _extract_json_object(repaired_text)
            except Exception as inner_exc:
                last_exc = inner_exc
                prompt = (
                    "Still invalid JSON. Return one valid JSON object only.\n"
                    f"Required keys: {expected}\n"
                    f"Parse error: {str(inner_exc)[:500]}\n"
                    f"Raw model output:\n{repaired_text[:20000]}"
                )
        raise last_exc

    def _ensure_js_executable_contract(self, js_code: str) -> None:
        missing: list[str] = []
        if not re.search(r"\bfunction\s+createSlide\s*\(", js_code):
            missing.append("createSlide")
        if "module.exports" not in js_code:
            missing.append("module.exports")
        if missing:
            raise ValueError(f"LLM_OUTPUT_NOT_EXECUTABLE: missing {', '.join(missing)}")

    async def _chat_text(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float,
        response_format: dict[str, Any] | None = None,
        allow_response_format_fallback: bool = False,
    ) -> str:
        if self.api_style == "anthropic_messages":
            return await self._anthropic_text(messages=messages, temperature=temperature)
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if response_format and self.outline_structured_output:
            payload["response_format"] = response_format
        headers = {"Authorization": f"Bearer {self.api_key}"}
        endpoint = self._openai_completions_endpoint()
        attempted_fallback = False
        while True:
            try:
                async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                    resp = await client.post(endpoint, json=payload, headers=headers)
                    resp.raise_for_status()
                    body = resp.json()
                content = body["choices"][0]["message"]["content"]
                text = self._clean_response_text(self._response_content_to_text(content))
                if not text:
                    raise LLMEmptyResponseError(phase="chat.text", reason="provider returned empty text content")
                return text
            except httpx.HTTPStatusError as exc:
                if (
                    allow_response_format_fallback
                    and not attempted_fallback
                    and "response_format" in payload
                    and self._is_response_format_unsupported(exc)
                ):
                    attempted_fallback = True
                    payload.pop("response_format", None)
                    continue
                raise

    async def _chat_stream_text(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float,
        on_token: TokenCallback,
    ) -> str:
        if self.api_style == "anthropic_messages":
            text = self._clean_response_text(await self._anthropic_text(messages=messages, temperature=temperature))
            for token in text.split():
                await on_token(token + " ")
            return text

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        endpoint = self._openai_completions_endpoint()

        chunks: list[str] = []
        async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
            async with client.stream("POST", endpoint, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    part = json.loads(raw)
                    token = part.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if token:
                        chunks.append(token)
                        await on_token(token)
        text = self._clean_response_text("".join(chunks))
        if not text:
            raise LLMEmptyResponseError(phase="chat.stream", reason="stream completed without visible text")
        return text

    async def _anthropic_text(self, *, messages: list[dict[str, str]], temperature: float) -> str:
        system = ""
        converted_messages: list[dict[str, str]] = []
        for item in messages:
            if item["role"] == "system":
                system += item["content"] + "\n"
            else:
                converted_messages.append({"role": item["role"], "content": item["content"]})
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4000,
            "messages": converted_messages,
            "temperature": temperature,
        }
        if system.strip():
            payload["system"] = system.strip()

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        endpoint = self._anthropic_messages_endpoint()
        async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
            resp = await client.post(endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
        content = body.get("content", [])
        if isinstance(content, list):
            texts = [str(part.get("text", "")) for part in content if isinstance(part, dict)]
            return "".join(texts)
        return str(content)

    def _response_content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text", "")
                    if text:
                        chunks.append(str(text))
                elif part:
                    chunks.append(str(part))
            return "".join(chunks)
        return str(content)

    def _clean_response_text(self, text: str) -> str:
        if not self.sanitize_think_tags:
            return str(text or "").replace("\ufeff", "").strip()
        return _sanitize_llm_text(text)

    def _is_response_format_unsupported(self, exc: httpx.HTTPStatusError) -> bool:
        status = exc.response.status_code
        if status not in {400, 404, 415, 422}:
            return False
        body = ""
        try:
            body = exc.response.text
        except Exception:
            body = ""
        hint = body.lower()
        return "response_format" in hint or "json_schema" in hint or "schema" in hint

    def _outline_response_format(self, *, target_slide_count: int) -> dict[str, Any] | None:
        if not self.outline_structured_output or self.api_style == "anthropic_messages":
            return None
        
        # Minimax 不支持复杂的 json_schema 类型，使用简单的 json_object 类型
        # 依靠 prompt 中的 JSON 格式示例来保证输出格式
        if "minimax" in self.model.lower():
            return {"type": "json_object"}
        
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "version": {"type": "integer", "minimum": 1},
                "summary": {"type": "string"},
                "nodes": {
                    "type": "array",
                    "minItems": target_slide_count,
                    "maxItems": target_slide_count,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "title": {"type": "string"},
                            "bullets": {"type": "array", "items": {"type": "string"}},
                            "page_type": {
                                "type": "string",
                                "enum": [
                                    SlidePageType.COVER.value,
                                    SlidePageType.TOC.value,
                                    SlidePageType.SECTION.value,
                                    SlidePageType.CONTENT.value,
                                    SlidePageType.SUMMARY.value,
                                ],
                            },
                            "layout_hint": {"type": ["string", "null"]},
                        },
                        "required": ["title", "bullets", "page_type", "layout_hint"],
                    },
                },
            },
            "required": ["version", "summary", "nodes"],
        }
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "outline_document",
                "strict": True,
                "schema": schema,
            },
        }

    def _longform_plan_response_format(
        self, *, target_section_count: int
    ) -> dict[str, Any] | None:
        if not self.outline_structured_output or self.api_style == "anthropic_messages":
            return None
        if "minimax" in self.model.lower():
            return {"type": "json_object"}
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "version": {"type": "integer", "minimum": 1},
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "sections": {
                    "type": "array",
                    "minItems": target_section_count,
                    "maxItems": target_section_count,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "section_id": {"type": "string"},
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                            "key_points": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "intent": {"type": "string"},
                            "source_refs": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "section_id",
                            "title",
                            "summary",
                            "key_points",
                            "intent",
                            "source_refs",
                        ],
                    },
                },
            },
            "required": ["version", "title", "summary", "sections"],
        }
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "longform_plan",
                "strict": True,
                "schema": schema,
            },
        }

    def _longform_section_response_format(self) -> dict[str, Any] | None:
        if not self.outline_structured_output or self.api_style == "anthropic_messages":
            return None
        if "minimax" in self.model.lower():
            return {"type": "json_object"}
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "section_id": {"type": "string"},
                "heading": {"type": "string"},
                "blocks": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": ["heading", "paragraph", "bullet_list", "quote"],
                            },
                            "text": {"type": "string"},
                            "items": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["kind", "text", "items"],
                    },
                },
                "citations": {"type": "array", "items": {"type": "string"}},
                "revision": {"type": "integer", "minimum": 1},
            },
            "required": ["section_id", "heading", "blocks", "citations", "revision"],
        }
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "longform_section_draft",
                "strict": True,
                "schema": schema,
            },
        }

    def _slide_spec_response_format(self) -> dict[str, Any] | None:
        if not self.outline_structured_output or self.api_style == "anthropic_messages":
            return None

        if "minimax" in self.model.lower():
            return {"type": "json_object"}

        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string"},
                "subtitle": {"type": "string"},
                "bullets": {"type": "array", "items": {"type": "string"}},
                "page_type": {
                    "type": "string",
                    "enum": [
                        SlidePageType.COVER.value,
                        SlidePageType.TOC.value,
                        SlidePageType.SECTION.value,
                        SlidePageType.CONTENT.value,
                        SlidePageType.SUMMARY.value,
                    ],
                },
                "layout_hint": {"type": ["string", "null"]},
                "visual_kind": {"type": "string", "enum": ["image", "chart", "shape"]},
                "emphasis": {"type": "string"},
                "citations": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "subtitle", "bullets", "page_type", "layout_hint", "visual_kind", "emphasis", "citations"],
        }
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "slide_spec",
                "strict": True,
                "schema": schema,
            },
        }

    def _openai_completions_endpoint(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def _anthropic_messages_endpoint(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/messages"
        return f"{self.base_url}/v1/messages"

    def _fit_outline(self, outline: OutlineDocument, *, topic: str, target_slide_count: int, template_style: str) -> OutlineDocument:
        nodes = list(outline.nodes)
        if len(nodes) > target_slide_count:
            nodes = nodes[:target_slide_count]
        while len(nodes) < target_slide_count:
            idx = len(nodes) + 1
            nodes.append(
                OutlineNode(
                    title=f"{topic} - Section {idx}",
                    bullets=[f"Point {idx}.1", f"Point {idx}.2"],
                    page_type=SlidePageType.CONTENT,
                    layout_hint="content-two-column",
                )
            )
        self._assign_page_types(nodes)
        style_dna = resolve_style_dna_choice(
            "auto",
            template_style=template_style,
            seed=f"{topic}|{target_slide_count}|outline",
        )
        enforce_layout_variety(
            nodes=nodes,
            seed=f"{topic}|{target_slide_count}",
            style_dna_id=style_dna.id,
        )
        return OutlineDocument(version=max(1, outline.version), summary=outline.summary, nodes=nodes)

    def _parse_outline_or_raise(
        self,
        *,
        text: str,
        topic: str,
        target_slide_count: int,
        template_style: str,
    ) -> OutlineDocument:
        try:
            payload = _extract_json_object(text)
        except Exception as exc:
            raise OutlineFormatError(
                category="parse",
                details=[str(exc)],
                raw_response=text,
            ) from exc
        try:
            outline = OutlineDocument.model_validate(payload)
        except ValidationError as exc:
            details: list[str] = []
            for item in exc.errors():
                loc = ".".join(str(x) for x in item.get("loc", ()))
                msg = str(item.get("msg", "validation error"))
                details.append(f"{loc}: {msg}")
            if not details:
                details = [str(exc)]
            raise OutlineFormatError(
                category="schema",
                details=details[:10],
                raw_response=text,
            ) from exc
        return self._fit_outline(
            outline,
            topic=topic,
            target_slide_count=target_slide_count,
            template_style=template_style,
        )

    def _fit_longform_plan(
        self,
        plan: LongFormPlan,
        *,
        topic: str,
        target_section_count: int,
        rag_context_snippets: list[dict[str, Any]],
    ) -> LongFormPlan:
        sections = list(plan.sections)
        default_refs = [
            str(item.get("chunk_id") or item.get("source_id") or f"src-{idx}")
            for idx, item in enumerate(rag_context_snippets[:2], start=1)
        ]
        if len(sections) > target_section_count:
            sections = sections[:target_section_count]
        while len(sections) < target_section_count:
            idx = len(sections) + 1
            sections.append(
                LongFormPlanSection(
                    section_id=f"section-{idx}",
                    title=f"{topic} - Section {idx}",
                    summary=f"Explain theme {idx} of {topic}.",
                    key_points=[f"{topic} point {idx}.1", f"{topic} point {idx}.2"],
                    intent=f"clarify theme {idx}",
                    source_refs=list(default_refs),
                )
            )
        normalized: list[LongFormPlanSection] = []
        for idx, section in enumerate(sections, start=1):
            normalized.append(
                LongFormPlanSection(
                    section_id=str(section.section_id or f"section-{idx}").strip()
                    or f"section-{idx}",
                    title=str(section.title or f"{topic} - Section {idx}").strip()
                    or f"{topic} - Section {idx}",
                    summary=str(section.summary or "").strip(),
                    key_points=[
                        str(item).strip()
                        for item in list(section.key_points or [])
                        if str(item).strip()
                    ][:6]
                    or [f"{topic} point {idx}.1", f"{topic} point {idx}.2"],
                    intent=str(section.intent or "").strip() or f"clarify theme {idx}",
                    source_refs=[
                        str(item).strip()
                        for item in list(section.source_refs or [])
                        if str(item).strip()
                    ][:4]
                    or list(default_refs),
                )
            )
        return LongFormPlan(
            version=max(1, plan.version),
            title=str(plan.title or topic).strip() or topic,
            summary=str(plan.summary or "").strip(),
            sections=normalized,
        )

    def _parse_longform_plan_or_raise(
        self,
        *,
        text: str,
        topic: str,
        target_section_count: int,
        rag_context_snippets: list[dict[str, Any]],
    ) -> LongFormPlan:
        try:
            payload = _extract_json_object(text)
        except Exception as exc:
            raise LongFormFormatError(
                category="parse",
                details=[str(exc)],
                raw_response=text,
            ) from exc
        try:
            plan = LongFormPlan.model_validate(payload)
        except ValidationError as exc:
            details: list[str] = []
            for item in exc.errors():
                loc = ".".join(str(x) for x in item.get("loc", ()))
                msg = str(item.get("msg", "validation error"))
                details.append(f"{loc}: {msg}")
            if not details:
                details = [str(exc)]
            raise LongFormFormatError(
                category="schema",
                details=details[:10],
                raw_response=text,
            ) from exc
        return self._fit_longform_plan(
            plan,
            topic=topic,
            target_section_count=target_section_count,
            rag_context_snippets=rag_context_snippets,
        )

    def _parse_longform_section_or_raise(
        self,
        *,
        text: str,
        section_id: str,
        heading: str,
        key_points: list[str],
        source_refs: list[str],
    ) -> LongFormDraftSection:
        try:
            payload = _extract_json_object(text)
        except Exception as exc:
            raise LongFormFormatError(
                category="parse",
                details=[str(exc)],
                raw_response=text,
            ) from exc
        try:
            section = LongFormDraftSection.model_validate(payload)
        except ValidationError as exc:
            details: list[str] = []
            for item in exc.errors():
                loc = ".".join(str(x) for x in item.get("loc", ()))
                msg = str(item.get("msg", "validation error"))
                details.append(f"{loc}: {msg}")
            if not details:
                details = [str(exc)]
            raise LongFormFormatError(
                category="schema",
                details=details[:10],
                raw_response=text,
            ) from exc
        normalized_blocks = list(section.blocks or [])
        if not normalized_blocks:
            normalized_blocks = [
                ContentBlock(kind="heading", text=heading),
                ContentBlock(
                    kind="paragraph",
                    text=f"{heading} explains the section scope clearly.",
                ),
                ContentBlock(kind="bullet_list", items=list(key_points or [heading])),
            ]
        return LongFormDraftSection(
            section_id=str(section.section_id or section_id).strip() or section_id,
            heading=str(section.heading or heading).strip() or heading,
            blocks=normalized_blocks,
            citations=[
                str(item).strip()
                for item in list(section.citations or [])
                if str(item).strip()
            ][:6]
            or list(source_refs),
            revision=max(1, int(section.revision or 1)),
        )

    def _assign_page_types(self, nodes: list[OutlineNode]) -> None:
        if not nodes:
            return
        nodes[0].page_type = SlidePageType.COVER
        if len(nodes) > 1:
            nodes[1].page_type = SlidePageType.TOC
        if len(nodes) > 2:
            nodes[-1].page_type = SlidePageType.SUMMARY
        for i in range(2, len(nodes) - 1):
            if i % 4 == 0:
                nodes[i].page_type = SlidePageType.SECTION
            elif nodes[i].page_type not in {SlidePageType.SECTION, SlidePageType.CONTENT}:
                nodes[i].page_type = SlidePageType.CONTENT

    def _normalize_layout_hint(self, *, raw: str, page_type: SlidePageType, fallback: str | None) -> str | None:
        allowed = allowed_layouts_for(page_type)
        if raw in allowed:
            return raw
        if fallback and fallback in allowed:
            return fallback
        return allowed[0] if allowed else None
