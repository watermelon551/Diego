from __future__ import annotations

import re
from typing import Any

from ...models import EventType, RunRecord
from ...rag import StratumindSearchError
from ..outline_reporting import (
    build_outline_rag_degraded_payload,
    build_requirements_analyzed_payload,
)
from .outline_flow_errors import OutlineFlowStopped


class OutlineRequirementsMixin:
    async def _prepare_outline_requirements(
        self, *, run_id: str, run: RunRecord
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], str]:
        orch = self.orch
        requested_template_style = orch._requested_template_style(run)
        await orch._publish(
            run_id,
            EventType.REQUIREMENTS_ANALYZING_STARTED,
            {
                "target_slide_count": run.input.target_slide_count,
                "project_id": run.input.project_id,
                "has_rag": bool(run.input.rag_source_ids),
            },
        )
        selected_sources = [
            item for item in run.input.rag_source_ids if str(item).strip()
        ]
        try:
            rag_context_snippets, rag_retrieval = await orch._retrieve_outline_rag_context(
                run_id=run_id, run=run
            )
        except StratumindSearchError as exc:
            if selected_sources:
                await orch._fail_run(
                    run_id,
                    "OUTLINE_DRAFTING",
                    "OUTLINE_RAG_RETRIEVAL_FAILED",
                    retryable=exc.retryable,
                    error_details={
                        "error_code": exc.code,
                        "status_code": exc.status_code,
                        "reason": exc.message,
                        "details": exc.details or {},
                    },
                )
                raise OutlineFlowStopped from exc
            rag_context_snippets = []
            rag_retrieval = build_outline_rag_degraded_payload(
                target_slide_count=run.input.target_slide_count,
                top_k=orch._rag_query_top_k(
                    target_slide_count=run.input.target_slide_count
                ),
                enabled=bool(getattr(orch.rag_client, "enabled", False)),
                error_code=exc.code,
                status_code=exc.status_code,
                retryable=exc.retryable,
                reason=exc.message,
                details=exc.details or {},
            )
        rag_enabled = bool(rag_retrieval.get("enabled", True))
        if selected_sources and not rag_context_snippets and rag_enabled:
            error_code = (
                "OUTLINE_RAG_UNAVAILABLE"
                if not rag_enabled
                else "OUTLINE_RAG_NO_MATCH_FOR_SELECTED_SOURCES"
            )
            await orch._fail_run(
                run_id,
                "OUTLINE_DRAFTING",
                error_code,
                retryable=False,
                error_details={
                    "project_id": run.input.project_id,
                    "topic": run.input.topic,
                    "selected_file_ids": selected_sources,
                    "retrieval": rag_retrieval,
                },
            )
            raise OutlineFlowStopped(error_code)

        if self._pptd_fast_requirements_enabled():
            base_research = self._build_pptd_fast_research_brief(
                topic=run.input.topic,
                template_style=requested_template_style,
                target_slide_count=run.input.target_slide_count,
                rag_context_snippets=rag_context_snippets,
            )
            design_intent = self._build_pptd_fast_design_intent(
                topic=run.input.topic,
                template_style=requested_template_style,
                has_rag=bool(rag_context_snippets),
            )
        else:
            try:
                base_research = await orch._call_outline_with_timeout_retry(
                    run_id=run_id,
                    phase="requirements.analyze",
                    action=lambda: orch.llm_client.generate_research_brief(
                        topic=run.input.topic,
                        project_id=run.input.project_id,
                        rag_source_ids=run.input.rag_source_ids,
                        rag_context_snippets=rag_context_snippets,
                        template_style=requested_template_style,
                        target_slide_count=run.input.target_slide_count,
                    ),
                )
            except Exception:
                base_research = orch._fallback_research_brief(
                    topic=run.input.topic,
                    template_style=requested_template_style,
                    target_slide_count=run.input.target_slide_count,
                )
            try:
                design_intent = await orch._call_outline_with_timeout_retry(
                    run_id=run_id,
                    phase="requirements.design_intent",
                    action=lambda: orch.llm_client.generate_design_intent(
                        topic=run.input.topic,
                        template_style=requested_template_style,
                        target_slide_count=run.input.target_slide_count,
                        research_brief=base_research,
                    ),
                )
            except Exception:
                design_intent = {}
        requirements_report = orch._compose_requirements_report(
            run=run,
            research_brief=base_research,
            design_intent=design_intent,
            rag_context_snippets=rag_context_snippets,
            rag_retrieval=rag_retrieval,
        )
        requirements_report = orch._apply_style_preset_to_requirements(
            run=run, report=requirements_report
        )
        if self._pptd_fast_requirements_enabled():
            requirements_report["requirements_mode"] = "pptd_fast_deterministic"
        effective_template_style = (
            str(requirements_report.get("effective_template_style", "")).strip()
            or run.input.template_style
        )
        await orch.store.update_run(
            run_id, lambda r: setattr(r, "research_report", requirements_report)
        )
        requirements_payload = build_requirements_analyzed_payload(
            requirements_report=requirements_report,
            target_slide_count=run.input.target_slide_count,
            rag_retrieval=rag_retrieval,
        )
        requirements_payload["effective_template_style"] = effective_template_style
        await orch._publish(
            run_id, EventType.REQUIREMENTS_ANALYZING_COMPLETED, requirements_payload
        )
        await orch._publish(
            run_id, EventType.REQUIREMENTS_ANALYZED, requirements_payload
        )
        return (
            rag_context_snippets,
            rag_retrieval,
            requirements_report,
            effective_template_style,
        )

    def _pptd_fast_requirements_enabled(self) -> bool:
        settings = self.orch.settings
        return (
            bool(getattr(settings, "pptd_fast_requirements_enabled", True))
            and str(getattr(settings, "compile_provider", "") or "").lower() == "pptd"
        )

    def _build_pptd_fast_research_brief(
        self,
        *,
        topic: str,
        template_style: str,
        target_slide_count: int,
        rag_context_snippets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        has_rag = bool(rag_context_snippets)
        profile = self._pptd_skill_scenario_profile(template_style=template_style, topic=topic)
        page_focus = self._page_focus_from_rag(
            topic=topic,
            target_slide_count=target_slide_count,
            rag_context_snippets=rag_context_snippets,
        )
        return {
            "audience": "learners and reviewers",
            "purpose": f"explain {topic} through a source-grounded PPTD deck",
            "tone": "professional, evidence-grounded",
            "narrative_arc": (
                "source context -> key concepts -> mechanisms -> comparison -> synthesis"
                if has_rag
                else "context -> key concepts -> mechanisms -> examples -> synthesis"
            ),
            "page_focus": page_focus,
            "design_notes": [
                f"Use {template_style or 'auto'} as a style hint, not a legacy template.",
                "Use PPTD-native structure: diagrams, tables, timelines, and comparison pages.",
                "Keep classroom/report pages light-background and projector-readable.",
                "When sources exist, keep claims traceable to retrieved snippets.",
            ],
            "style_intent": "PPTD-first course/report deck with clear visual explanation",
            "effective_template_style": template_style,
            "requirements_mode": "pptd_fast_deterministic",
            "scenario_profile": profile,
            "visual_mode": "template" if "preset:" in template_style else "creative",
            "content_mode": "summary" if has_rag else "search",
            "density_guidance": self._pptd_skill_density_guidance(profile=profile),
            "font_guidance": self._pptd_skill_font_guidance(profile=profile),
            "risk_prohibitions": self._pptd_skill_risk_prohibitions(profile=profile),
        }

    def _build_pptd_fast_design_intent(
        self, *, topic: str, template_style: str, has_rag: bool
    ) -> dict[str, Any]:
        return {
            "palette_name": "PPTD Professional Light",
            "style_recipe": "soft",
            "title_font": "Source Han Sans",
            "body_font": "Source Han Sans",
            "visual_strategy": (
                "source-grounded diagrams and comparison structures"
                if has_rag
                else "concept diagrams, tables, and step-by-step explanations"
            ),
            "density": "medium",
            "rationale": (
                f"Use a neutral PPTD-first design for {topic}; "
                f"treat {template_style or 'auto'} as a style hint."
            ),
        }

    def _page_focus_from_rag(
        self,
        *,
        topic: str,
        target_slide_count: int,
        rag_context_snippets: list[dict[str, Any]],
    ) -> list[str]:
        focus: list[str] = []
        for snippet in rag_context_snippets:
            excerpt = self._compact_excerpt(str(snippet.get("excerpt", "")))
            if not excerpt:
                continue
            filename = str(snippet.get("filename", "")).strip()
            page = snippet.get("page_number")
            source = filename
            if page not in (None, ""):
                source = f"{source} P{page}" if source else f"P{page}"
            prefix = f"{source}: " if source else ""
            focus.append(f"{prefix}{excerpt}")
            if len(focus) >= target_slide_count:
                break
        if focus:
            return focus[:target_slide_count]
        return [
            f"{topic}: build concrete slide {idx} around one knowledge point"
            for idx in range(1, target_slide_count + 1)
        ]

    def _compact_excerpt(self, text: str) -> str:
        cleaned = re.sub(r"<details>.*?</details>", " ", text, flags=re.S)
        cleaned = re.sub(r"```.*?```", " ", cleaned, flags=re.S)
        cleaned = re.sub(r"#+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned[:180]

    def _pptd_skill_scenario_profile(self, *, template_style: str, topic: str) -> str:
        lowered = f"{template_style} {topic}".lower()
        if any(token in lowered for token in ("education", "course", "training", "teaching", "课程", "教学", "课件", "本科", "大学", "lecture")):
            return "education"
        if any(token in lowered for token in ("academic", "research", "thesis", "paper", "论文", "答辩", "学术")):
            return "academic"
        if any(token in lowered for token in ("business", "finance", "market", "strategy", "商业", "金融", "战略")):
            return "business_insight"
        return "general"

    def _pptd_skill_density_guidance(self, *, profile: str) -> str:
        if profile == "education":
            return "university/courseware medium-high density 65-80%; one knowledge point per page; avoid dense text walls"
        if profile == "academic":
            return "research/defense medium-high density; argument-evidence-summary per page"
        if profile == "business_insight":
            return "insight/report medium-high density; claim, evidence, implication, action"
        return "balanced medium density; readable zoning instead of crowded paragraphs"

    def _pptd_skill_font_guidance(self, *, profile: str) -> str:
        if profile == "education":
            return "courseware title 26-30px, body 18-22px, annotations 12-16px; projector-readable"
        return "title/body hierarchy with body usually 18-22px and annotations no smaller than 12px"

    def _pptd_skill_risk_prohibitions(self, *, profile: str) -> list[str]:
        risks = [
            "checker warnings are visual defects and must be cleared",
            "do not use decorative placeholders instead of diagrams/tables/comparisons",
            "do not repeat adjacent layouts without communicative reason",
        ]
        if profile == "education":
            risks.extend(
                [
                    "content pages should stay light-background for projector readability",
                    "page titles must state the knowledge point or conclusion",
                    "formula/code pages need examples or visual explanation, not pure text lists",
                ]
            )
        return risks
