from __future__ import annotations

import hashlib
from typing import Iterable, TypeVar

from ..style_catalog.selection import get_style_dna_by_id
from .contracts import DesignProfile, StyleRecipe

PALETTES: list[tuple[str, tuple[str, str, str, str, str]]] = [
    ("Modern & Wellness", ("006D77", "83C5BE", "EDF6F9", "FFDDD2", "E29578")),
    ("Business & Authority", ("2B2D42", "8D99AE", "EDF2F4", "EF233C", "D90429")),
    ("Nature & Outdoors", ("606C38", "283618", "FEFAE0", "DDA15E", "BC6C25")),
    ("Vintage & Academic", ("780000", "C1121F", "FDF0D5", "003049", "669BBC")),
    ("Soft & Creative", ("CDB4DB", "FFC8DD", "FFAFCC", "BDE0FE", "A2D2FF")),
    ("Bohemian", ("CCD5AE", "E9EDC9", "FEFAE0", "FAEDCD", "D4A373")),
    ("Vibrant & Tech", ("8ECAE6", "219EBC", "023047", "FFB703", "FB8500")),
    ("Craft & Artisan", ("7F5539", "A68A64", "EDE0D4", "656D4A", "414833")),
    ("Tech & Night", ("000814", "001D3D", "003566", "FFC300", "FFD60A")),
    ("Education & Charts", ("264653", "2A9D8F", "E9C46A", "F4A261", "E76F51")),
    ("Forest & Eco", ("DAD7CD", "A3B18A", "588157", "3A5A40", "344E41")),
    ("Elegant & Fashion", ("EDAFB8", "F7E1D7", "DEDBD2", "B0C4B1", "4A5759")),
    ("Art & Food", ("335C67", "FFF3B0", "E09F3E", "9E2A2B", "540B0E")),
    ("Luxury & Mysterious", ("22223B", "4A4E69", "9A8C98", "C9ADA7", "F2E9E4")),
    ("Pure Tech Blue", ("03045E", "0077B6", "00B4D8", "90E0EF", "CAF0F8")),
    ("Coastal Coral", ("0081A7", "00AFB9", "FDFCDC", "FED9B7", "F07167")),
    ("Vibrant Orange Mint", ("FF9F1C", "FFBF69", "FFFFFF", "CBF3F0", "2EC4B6")),
    ("Platinum White Gold", ("0A0A0A", "0070F3", "D4AF37", "F5F5F5", "FFFFFF")),
]

FONT_PAIRS: list[tuple[str, str]] = [
    ("Georgia", "Calibri"),
    ("Arial", "Arial"),
    ("Cambria", "Calibri"),
    ("Trebuchet MS", "Calibri"),
    ("Palatino Linotype", "Garamond"),
]

STYLE_RECIPES: dict[str, StyleRecipe] = {
    "sharp": StyleRecipe(
        name="sharp",
        corner_small=0.03,
        corner_medium=0.05,
        corner_large=0.08,
        page_margin=0.3,
        block_gap=0.3,
        element_gap=0.2,
        badge_pill=False,
    ),
    "soft": StyleRecipe(
        name="soft",
        corner_small=0.05,
        corner_medium=0.08,
        corner_large=0.12,
        page_margin=0.4,
        block_gap=0.4,
        element_gap=0.25,
        badge_pill=True,
    ),
    "rounded": StyleRecipe(
        name="rounded",
        corner_small=0.1,
        corner_medium=0.15,
        corner_large=0.25,
        page_margin=0.5,
        block_gap=0.55,
        element_gap=0.35,
        badge_pill=True,
    ),
    "pill": StyleRecipe(
        name="pill",
        corner_small=0.2,
        corner_medium=0.3,
        corner_large=0.5,
        page_margin=0.6,
        block_gap=0.7,
        element_gap=0.45,
        badge_pill=True,
    ),
}


def choose_design_profile(
    *, topic: str, template_style: str, style_dna_id: str | None = None
) -> DesignProfile:
    seed = f"{topic}|{template_style}|{style_dna_id}".lower()
    style_dna = get_style_dna_by_id(style_dna_id)
    if style_dna is not None:
        style = STYLE_RECIPES.get(style_dna.style_recipe, STYLE_RECIPES["soft"])
        theme = {
            key: str(style_dna.theme_hint.get(key, "")).strip().upper()
            for key in ("primary", "secondary", "accent", "light", "bg")
        }
        palette_name = style_dna.name
        title_font = (
            str(style_dna.typography_profile.get("title_font", "")).strip()
            or "Cambria"
        )
        body_font = (
            str(style_dna.typography_profile.get("body_font", "")).strip()
            or "Calibri"
        )
        return DesignProfile(
            palette_name=palette_name,
            theme=theme,
            title_font=title_font,
            body_font=body_font,
            style=style,
        )

    palette_name, palette = _choose(PALETTES, seed + "|palette")
    style = STYLE_RECIPES[_choose_style_name(template_style=template_style, seed=seed)]
    title_font, body_font = _choose(FONT_PAIRS, seed + "|fonts")
    theme = {
        "primary": palette[0],
        "secondary": palette[1],
        "accent": palette[4],
        "light": palette[3],
        "bg": palette[2],
    }
    return DesignProfile(
        palette_name=palette_name,
        theme=theme,
        title_font=title_font,
        body_font=body_font,
        style=style,
    )


def _choose_style_name(*, template_style: str, seed: str) -> str:
    lowered = template_style.lower()
    if any(
        word in lowered for word in ("sharp", "finance", "data", "report", "authority")
    ):
        return "sharp"
    if any(word in lowered for word in ("soft", "balanced", "education", "training")):
        return "soft"
    if any(
        word in lowered for word in ("rounded", "marketing", "creative", "product")
    ):
        return "rounded"
    if any(word in lowered for word in ("pill", "premium", "brand", "luxury")):
        return "pill"
    options = list(STYLE_RECIPES.keys())
    return options[_stable_index(seed=f"{seed}|style", size=len(options))]


T = TypeVar("T")


def _choose(items: Iterable[T], seed: str) -> T:
    lst = list(items)
    if not lst:
        raise ValueError("cannot choose from empty collection")
    return lst[_stable_index(seed=seed, size=len(lst))]


def _stable_index(*, seed: str, size: int) -> int:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % max(1, size)
