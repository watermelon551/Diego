from __future__ import annotations

from typing import Any

from ..design.design_resolution import (
    apply_style_preset_to_requirements,
    compose_requirements_report,
    normalize_hex6,
    requested_template_style,
    resolve_content_source_mode,
    resolve_design_profile,
    resolve_font_from_intent,
    resolve_image_source_mode,
    resolve_palette_theme,
    resolve_style_recipe_name,
    resolved_style_dna_id,
    selected_style_dna,
    selected_style_preset,
)
from ..design.skill_profile import DesignProfile
from ..design.style_catalog import get_style_dna_by_id
from ..models import RunRecord


class RunDesignResolutionMixin:
    def _resolved_template_style(self, run: RunRecord) -> str:
        report = run.research_report if isinstance(run.research_report, dict) else {}
        style = str(report.get("effective_template_style", "")).strip()
        return style or run.input.template_style

    def _resolve_run_design(self, run: RunRecord) -> DesignProfile:
        return resolve_design_profile(
            topic=run.input.topic,
            template_style=self._resolved_template_style(run),
            requirements_report=(
                run.research_report if isinstance(run.research_report, dict) else {}
            ),
        )

    def _resolve_content_source_mode(self, run: RunRecord) -> str:
        return resolve_content_source_mode(run)

    def _resolve_image_source_mode(self, run: RunRecord) -> str:
        return resolve_image_source_mode(
            run=run,
            asset_provider=self.settings.asset_provider,
        )

    def _selected_style_preset(self, run: RunRecord):
        return selected_style_preset(run)

    def _selected_style_dna(self, run: RunRecord):
        return selected_style_dna(run)

    def _resolved_style_dna_id(self, run: RunRecord) -> str | None:
        return resolved_style_dna_id(run)

    def _resolved_style_dna(self, run: RunRecord):
        return get_style_dna_by_id(self._resolved_style_dna_id(run))

    def _requested_template_style(self, run: RunRecord) -> str:
        return requested_template_style(run)

    def _apply_style_preset_to_requirements(
        self, *, run: RunRecord, report: dict[str, Any]
    ) -> dict[str, Any]:
        return apply_style_preset_to_requirements(run=run, report=report)

    def _compose_requirements_report(
        self,
        *,
        run: RunRecord,
        research_brief: dict[str, Any],
        design_intent: dict[str, Any] | None = None,
        rag_context_snippets: list[dict[str, Any]] | None = None,
        rag_retrieval: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return compose_requirements_report(
            run=run,
            research_brief=research_brief,
            design_intent=design_intent,
            rag_context_snippets=rag_context_snippets,
            rag_retrieval=rag_retrieval,
            content_source_mode=self._resolve_content_source_mode(run),
            image_source_mode=self._resolve_image_source_mode(run),
        )

    def _normalize_hex6(self, raw: str) -> str | None:
        return normalize_hex6(raw)

    def _resolve_palette_theme(
        self, *, base: DesignProfile, design_intent: dict[str, Any]
    ) -> tuple[str, dict[str, str]]:
        return resolve_palette_theme(base=base, design_intent=design_intent)

    def _resolve_style_recipe_name(
        self,
        *,
        design_intent: dict[str, Any],
        style_intent: str,
        template_style: str,
        fallback: str,
    ) -> str:
        return resolve_style_recipe_name(
            design_intent=design_intent,
            style_intent=style_intent,
            template_style=template_style,
            fallback=fallback,
        )

    def _resolve_font_from_intent(self, *, preferred: str, fallback: str) -> str:
        return resolve_font_from_intent(preferred=preferred, fallback=fallback)

    def _resolve_design_profile(
        self, *, topic: str, template_style: str, requirements_report: dict[str, Any]
    ) -> DesignProfile:
        return resolve_design_profile(
            topic=topic,
            template_style=template_style,
            requirements_report=requirements_report,
        )
