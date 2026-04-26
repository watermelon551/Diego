from __future__ import annotations

from ._compat import maybe_warn_legacy_import
from .design.style_catalog import (
    PAGE_TYPE_CONTENT,
    PAGE_TYPE_COVER,
    PAGE_TYPE_SECTION,
    PAGE_TYPE_SUMMARY,
    PAGE_TYPE_TOC,
    STYLE_PRESET_AUTO,
    STYLE_PRESETS,
    STYLE_DNAS,
    STYLE_THEME_HINTS,
    StyleDNA,
    StylePreset,
    get_style_dna_by_id,
    get_style_theme_hint,
    is_valid_style_choice,
    list_style_dnas,
    list_style_presets,
    normalize_style_choice,
    resolve_style_dna_choice,
    resolve_style_choice,
)

maybe_warn_legacy_import(legacy="service.style_catalog", replacement="service.design.style_catalog")

__all__ = [
    "STYLE_PRESET_AUTO",
    "STYLE_PRESETS",
    "STYLE_DNAS",
    "STYLE_THEME_HINTS",
    "PAGE_TYPE_COVER",
    "PAGE_TYPE_TOC",
    "PAGE_TYPE_SECTION",
    "PAGE_TYPE_CONTENT",
    "PAGE_TYPE_SUMMARY",
    "StyleDNA",
    "StylePreset",
    "get_style_dna_by_id",
    "get_style_theme_hint",
    "is_valid_style_choice",
    "list_style_dnas",
    "list_style_presets",
    "normalize_style_choice",
    "resolve_style_dna_choice",
    "resolve_style_choice",
]
