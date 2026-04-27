from __future__ import annotations

import json
from typing import Any

from ..models import OutlineNode, VisualPolicy
from .parsing import _extract_js_module
from .types import GeneratedSlide


class LLMSlideCodegenMixin:
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
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
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
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
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
        if isinstance(slide_brief, dict) and isinstance(
            slide_brief.get("style_dna"), dict
        ):
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
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
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
        if isinstance(slide_brief, dict) and isinstance(
            slide_brief.get("style_dna"), dict
        ):
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
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.slide_temperature,
        )
        return _extract_js_module(text)
