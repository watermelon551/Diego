from __future__ import annotations

from typing import Any

from ..models import RunRecord
from .design_profile_resolution import (
    resolve_design_profile as resolve_design_profile_impl,
    resolve_font_from_intent as resolve_font_from_intent_impl,
    resolve_palette_theme as resolve_palette_theme_impl,
    resolve_style_recipe_name as resolve_style_recipe_name_impl,
)
from .design_requirements_report import (
    apply_style_preset_to_requirements as apply_style_preset_to_requirements_impl,
    compose_requirements_report as compose_requirements_report_impl,
    normalize_hex6 as normalize_hex6_impl,
)
from .skill_profile import DesignProfile


def normalize_hex6(raw: str) -> str | None:
    return normalize_hex6_impl(raw)


def apply_style_preset_to_requirements(
    *, run: RunRecord, report: dict[str, Any]
) -> dict[str, Any]:
    return apply_style_preset_to_requirements_impl(run=run, report=report)


def compose_requirements_report(
    *,
    run: RunRecord,
    research_brief: dict[str, Any],
    design_intent: dict[str, Any] | None = None,
    rag_context_snippets: list[dict[str, Any]] | None = None,
    rag_retrieval: dict[str, Any] | None = None,
    content_source_mode: str,
    image_source_mode: str,
) -> dict[str, Any]:
    return compose_requirements_report_impl(
        run=run,
        research_brief=research_brief,
        design_intent=design_intent,
        rag_context_snippets=rag_context_snippets,
        rag_retrieval=rag_retrieval,
        content_source_mode=content_source_mode,
        image_source_mode=image_source_mode,
    )


def resolve_palette_theme(
    *, base: DesignProfile, design_intent: dict[str, Any]
) -> tuple[str, dict[str, str]]:
    return resolve_palette_theme_impl(base=base, design_intent=design_intent)


def resolve_style_recipe_name(
    *,
    design_intent: dict[str, Any],
    style_intent: str,
    template_style: str,
    fallback: str,
) -> str:
    return resolve_style_recipe_name_impl(
        design_intent=design_intent,
        style_intent=style_intent,
        template_style=template_style,
        fallback=fallback,
    )


def resolve_font_from_intent(*, preferred: str, fallback: str) -> str:
    return resolve_font_from_intent_impl(preferred=preferred, fallback=fallback)


def resolve_design_profile(
    *, topic: str, template_style: str, requirements_report: dict[str, Any]
) -> DesignProfile:
    return resolve_design_profile_impl(
        topic=topic,
        template_style=template_style,
        requirements_report=requirements_report,
    )

