from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StyleRecipe:
    name: str
    corner_small: float
    corner_medium: float
    corner_large: float
    page_margin: float
    block_gap: float
    element_gap: float
    badge_pill: bool


@dataclass(frozen=True)
class DesignProfile:
    palette_name: str
    theme: dict[str, str]
    title_font: str
    body_font: str
    style: StyleRecipe
