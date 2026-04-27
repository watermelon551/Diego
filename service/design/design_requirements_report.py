from __future__ import annotations

from typing import Any

from ..models import RunRecord
from .style_catalog import STYLE_PRESET_AUTO, get_style_theme_hint
from .style_selection import selected_style_dna, selected_style_preset


def normalize_hex6(raw: str) -> str | None:
    value = (raw or "").strip().lstrip("#")
    if len(value) == 3 and all(ch in "0123456789abcdefABCDEF" for ch in value):
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in value):
        return None
    return value.upper()


def apply_style_preset_to_requirements(
    *, run: RunRecord, report: dict[str, Any]
) -> dict[str, Any]:
    preset = selected_style_preset(run)
    style_dna = selected_style_dna(run)
    normalized = dict(report or {})
    normalized["style_preset"] = getattr(run.input, "style_preset", STYLE_PRESET_AUTO)
    if preset is None and style_dna is None:
        normalized["style_reference_name"] = ""
        return normalized

    reference_name = (
        style_dna.name
        if style_dna is not None
        else (preset.name if preset is not None else "")
    )
    style_intent = (
        style_dna.prompt
        if style_dna is not None
        else (preset.prompt if preset is not None else "")
    )
    effective_template_style = (
        style_dna.template_style_hint
        if style_dna is not None
        else (preset.template_style_hint if preset is not None else "")
    )
    normalized["style_reference_name"] = reference_name
    normalized["style_intent"] = style_intent
    normalized["effective_template_style"] = effective_template_style

    notes_raw = normalized.get("design_notes", [])
    notes = (
        [str(item).strip() for item in notes_raw if str(item).strip()]
        if isinstance(notes_raw, list)
        else []
    )
    if style_intent:
        notes = [style_intent] + [item for item in notes if item != style_intent]
    normalized["design_notes"] = notes[:8]

    design_intent = normalized.get("design_intent", {})
    if not isinstance(design_intent, dict):
        design_intent = {}
    if not str(design_intent.get("style_recipe", "")).strip() and style_dna is not None:
        design_intent["style_recipe"] = style_dna.style_recipe
    if not str(design_intent.get("rationale", "")).strip():
        design_intent["rationale"] = (
            f"apply selected style profile: {reference_name or 'auto'}"
        )
    style_theme = (
        dict(style_dna.theme_hint)
        if style_dna is not None
        else get_style_theme_hint(preset.id if preset is not None else "")
    )
    if style_theme:
        existing_theme_raw = (
            design_intent.get("theme")
            if isinstance(design_intent.get("theme"), dict)
            else {}
        )
        existing_theme: dict[str, str] = {}
        for key in ("primary", "secondary", "accent", "light", "bg"):
            candidate = normalize_hex6(str(existing_theme_raw.get(key, "")))
            if candidate:
                existing_theme[key] = candidate
        if len(existing_theme) >= 5:
            design_intent["theme"] = existing_theme
        else:
            merged_theme = dict(style_theme)
            merged_theme.update(existing_theme)
            design_intent["theme"] = merged_theme
        palette_name = str(design_intent.get("palette_name", "")).strip()
        if not palette_name:
            design_intent["palette_name"] = reference_name
            normalized["palette_name"] = reference_name
        else:
            normalized["palette_name"] = palette_name
    if style_dna is not None:
        design_intent.setdefault("layout_family", style_dna.layout_family)
        design_intent.setdefault("density_profile", style_dna.density_profile)
        design_intent.setdefault(
            "visual_strategy_profile", style_dna.visual_strategy_profile
        )
        design_intent["style_dna_id"] = style_dna.id
        design_intent["style_signature"] = style_dna.style_signature
        if not str(design_intent.get("title_font", "")).strip():
            design_intent["title_font"] = str(
                style_dna.typography_profile.get("title_font", "")
            )
        if not str(design_intent.get("body_font", "")).strip():
            design_intent["body_font"] = str(
                style_dna.typography_profile.get("body_font", "")
            )
    normalized["design_intent"] = design_intent
    return normalized


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
    report: dict[str, Any] = dict(research_brief or {})
    intent_raw = dict(design_intent or {})
    notes_raw = report.get("design_notes", [])
    notes = (
        [str(item).strip() for item in notes_raw if str(item).strip()]
        if isinstance(notes_raw, list)
        else []
    )
    page_focus_raw = report.get("page_focus", [])
    page_focus = (
        [str(item).strip() for item in page_focus_raw if str(item).strip()]
        if isinstance(page_focus_raw, list)
        else []
    )
    tone = str(report.get("tone", "")).strip()
    style_intent = (
        str(report.get("style_intent", "")).strip() or tone or "professional"
    )
    effective_template_style = (
        str(report.get("effective_template_style", "")).strip()
        or run.input.template_style
    )
    theme_overrides_raw = (
        intent_raw.get("theme") if isinstance(intent_raw.get("theme"), dict) else {}
    )
    theme_overrides = {
        key: value
        for key, value in {
            "primary": normalize_hex6(str(theme_overrides_raw.get("primary", ""))),
            "secondary": normalize_hex6(str(theme_overrides_raw.get("secondary", ""))),
            "accent": normalize_hex6(str(theme_overrides_raw.get("accent", ""))),
            "light": normalize_hex6(str(theme_overrides_raw.get("light", ""))),
            "bg": normalize_hex6(str(theme_overrides_raw.get("bg", ""))),
        }.items()
        if value
    }
    design_intent_norm = {
        "palette_name": str(intent_raw.get("palette_name", "")).strip(),
        "style_recipe": str(intent_raw.get("style_recipe", "")).strip().lower(),
        "title_font": str(intent_raw.get("title_font", "")).strip(),
        "body_font": str(intent_raw.get("body_font", "")).strip(),
        "visual_strategy": str(intent_raw.get("visual_strategy", "")).strip(),
        "density": str(intent_raw.get("density", "")).strip(),
        "layout_family": str(intent_raw.get("layout_family", "")).strip(),
        "density_profile": str(intent_raw.get("density_profile", "")).strip(),
        "visual_strategy_profile": str(
            intent_raw.get("visual_strategy_profile", "")
        ).strip(),
        "style_dna_id": str(intent_raw.get("style_dna_id", "")).strip(),
        "style_signature": str(intent_raw.get("style_signature", "")).strip(),
        "rationale": str(intent_raw.get("rationale", "")).strip(),
        "theme": theme_overrides,
    }
    report.update(
        {
            "audience": str(report.get("audience", "")).strip() or "general audience",
            "purpose": str(report.get("purpose", "")).strip()
            or f"explain {run.input.topic} clearly",
            "tone": tone or "professional",
            "narrative_arc": str(report.get("narrative_arc", "")).strip()
            or "problem -> analysis -> solution -> summary",
            "page_focus": page_focus[: run.input.target_slide_count],
            "design_notes": notes[:8],
            "style_intent": style_intent,
            "effective_template_style": effective_template_style,
            "design_intent": design_intent_norm,
            "style_preset": getattr(run.input, "style_preset", STYLE_PRESET_AUTO),
            "page_count_fixed": run.input.target_slide_count,
            "content_source_mode": content_source_mode,
            "image_source_mode": image_source_mode,
            "rag_context_snippets": list(rag_context_snippets or []),
            "rag_retrieval": dict(rag_retrieval or {}),
        }
    )
    return report

