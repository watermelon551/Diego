from __future__ import annotations

from ._compat import maybe_warn_legacy_import
from .design.style_catalog import (
    STYLE_PRESET_AUTO,
    STYLE_PRESETS,
    STYLE_THEME_HINTS,
    StylePreset,
    get_style_theme_hint,
    is_valid_style_choice,
    list_style_presets,
    normalize_style_choice,
    resolve_style_choice,
)

maybe_warn_legacy_import(legacy="service.style_catalog", replacement="service.design.style_catalog")

__all__ = [
    "STYLE_PRESET_AUTO",
    "STYLE_PRESETS",
    "STYLE_THEME_HINTS",
    "StylePreset",
    "get_style_theme_hint",
    "is_valid_style_choice",
    "list_style_presets",
    "normalize_style_choice",
    "resolve_style_choice",
]
