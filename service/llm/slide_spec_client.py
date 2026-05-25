from __future__ import annotations

import json
from typing import Any

from ..models import OutlineNode, VisualPolicy
from .pptd_skill_guidance import PPTD_OUTLINE_QUALITY_GUIDANCE
from .types import SlideSpec


class LLMSlideSpecMixin:
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
            f"{PPTD_OUTLINE_QUALITY_GUIDANCE}\n"
            "Hard constraints:\n"
            "- natural language only, concise and specific; no API names/code snippets\n"
            "- keep strong title/body hierarchy intent (title short, bullets informative)\n"
            "- bullets: 3-6 preferred on content pages, avoid empty fluff\n"
            "- Chinese bullets must be PPT-box-ready: normally <=32 Chinese chars; split long clauses instead of relying on truncation\n"
            "- avoid ellipsis as planned visible content; rewrite to a shorter complete phrase instead\n"
            "- respect layout_hint/page_type and keep citations as short source ids\n"
            "- visual_kind in {image, chart, shape}; if visual_policy=media_required use image; if basic_graphics_only avoid image"
        )
        response_format = self._slide_spec_response_format()
        text = await self._chat_text(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.slide_temperature,
            response_format=response_format,
            allow_response_format_fallback=True,
        )
        payload = await self._extract_json_object_with_repair(
            text=text,
            expected_keys=[
                "title",
                "subtitle",
                "bullets",
                "page_type",
                "layout_hint",
                "visual_kind",
                "emphasis",
                "citations",
            ],
            temperature=self.slide_temperature,
        )
        return self._parse_slide_spec(
            text=json.dumps(payload, ensure_ascii=False),
            fallback=outline_node,
        )

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
            f"{PPTD_OUTLINE_QUALITY_GUIDANCE}\n"
            "Repair goals:\n"
            "- keep intent, but make text clearer and denser where needed\n"
            "- remove vague filler and any non-natural-language artifacts\n"
            "- keep layout/page type valid and match visual policy constraints\n"
            "- if issues mention overflow/fit/spacing, shorten bullets and prioritize readability\n"
            "- rewrite long visible text into complete compact phrases; do not use ellipsis as a fit strategy"
        )
        response_format = self._slide_spec_response_format()
        text = await self._chat_text(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.slide_temperature,
            response_format=response_format,
            allow_response_format_fallback=True,
        )
        payload = await self._extract_json_object_with_repair(
            text=text,
            expected_keys=[
                "title",
                "subtitle",
                "bullets",
                "page_type",
                "layout_hint",
                "visual_kind",
                "emphasis",
                "citations",
            ],
            temperature=self.slide_temperature,
        )
        return self._parse_slide_spec(
            text=json.dumps(payload, ensure_ascii=False),
            fallback=outline_node,
        )

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
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
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
        directives = [
            str(item).strip() for item in directives_raw if str(item).strip()
        ]
        return {
            "score": score,
            "issues": issues,
            "repair_directives": directives,
        }
