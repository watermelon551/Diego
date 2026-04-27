from __future__ import annotations

from typing import Any

from .design_requirements_report import normalize_hex6
from .skill_profile import (
    FONT_PAIRS,
    PALETTES,
    STYLE_RECIPES,
    DesignProfile,
    choose_design_profile,
)


def resolve_palette_theme(
    *, base: DesignProfile, design_intent: dict[str, Any]
) -> tuple[str, dict[str, str]]:
    palette_name = str(design_intent.get("palette_name", "")).strip()
    for name, palette in PALETTES:
        if palette_name and name.lower() == palette_name.lower():
            return name, {
                "primary": palette[0],
                "secondary": palette[1],
                "accent": palette[4],
                "light": palette[3],
                "bg": palette[2],
            }

    theme = dict(base.theme)
    theme_payload = (
        design_intent.get("theme")
        if isinstance(design_intent.get("theme"), dict)
        else {}
    )
    for key in ("primary", "secondary", "accent", "light", "bg"):
        candidate = normalize_hex6(str(theme_payload.get(key, "")))
        if candidate:
            theme[key] = candidate
    return (palette_name or base.palette_name), theme


def resolve_style_recipe_name(
    *,
    design_intent: dict[str, Any],
    style_intent: str,
    template_style: str,
    fallback: str,
) -> str:
    explicit = str(design_intent.get("style_recipe", "")).strip().lower()
    if explicit in STYLE_RECIPES:
        return explicit
    merged = f"{style_intent} {template_style}".lower()
    if any(
        word in merged for word in ("brutal", "sharp", "authority", "finance", "data")
    ):
        return "sharp"
    if any(word in merged for word in ("premium", "luxury", "editorial", "brand")):
        return "pill"
    if any(
        word in merged for word in ("creative", "marketing", "rounded", "friendly")
    ):
        return "rounded"
    if any(word in merged for word in ("soft", "education", "training", "balanced")):
        return "soft"
    return fallback if fallback in STYLE_RECIPES else "soft"


def resolve_font_from_intent(*, preferred: str, fallback: str) -> str:
    normalized_preferred = preferred.strip()
    if not normalized_preferred:
        return fallback
    available = {font for pair in FONT_PAIRS for font in pair}
    return normalized_preferred if normalized_preferred in available else fallback


def resolve_design_profile(
    *, topic: str, template_style: str, requirements_report: dict[str, Any]
) -> DesignProfile:
    design_intent = requirements_report.get("design_intent", {})
    if not isinstance(design_intent, dict):
        design_intent = {}
    style_dna_id = str(design_intent.get("style_dna_id", "")).strip() or None
    base = choose_design_profile(
        topic=topic,
        template_style=template_style,
        style_dna_id=style_dna_id,
    )
    palette_name, theme = resolve_palette_theme(
        base=base,
        design_intent=design_intent,
    )
    style_name = resolve_style_recipe_name(
        design_intent=design_intent,
        style_intent=str(requirements_report.get("style_intent", "")),
        template_style=template_style,
        fallback=base.style.name,
    )
    style = STYLE_RECIPES.get(style_name, base.style)
    title_font = resolve_font_from_intent(
        preferred=str(design_intent.get("title_font", "")),
        fallback=base.title_font,
    )
    body_font = resolve_font_from_intent(
        preferred=str(design_intent.get("body_font", "")),
        fallback=base.body_font,
    )
    return DesignProfile(
        palette_name=palette_name,
        theme=theme,
        title_font=title_font,
        body_font=body_font,
        style=style,
    )

