from __future__ import annotations

from ._compat import maybe_warn_legacy_import
from .design.skill_profile import (
    FONT_PAIRS,
    LAYOUTS_BY_PAGE_TYPE,
    PALETTES,
    STYLE_RECIPES,
    DesignProfile,
    StyleRecipe,
    allowed_layouts_for,
    choose_design_profile,
    enforce_layout_variety,
)

maybe_warn_legacy_import(legacy="service.skill_profile", replacement="service.design.skill_profile")

__all__ = [
    "FONT_PAIRS",
    "LAYOUTS_BY_PAGE_TYPE",
    "PALETTES",
    "STYLE_RECIPES",
    "DesignProfile",
    "StyleRecipe",
    "allowed_layouts_for",
    "choose_design_profile",
    "enforce_layout_variety",
]
