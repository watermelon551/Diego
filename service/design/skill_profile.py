from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable
from typing import TypeVar

from ..models import OutlineNode, SlidePageType


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


PALETTES: list[tuple[str, tuple[str, str, str, str, str]]] = [
    ("Modern & Wellness", ("006d77", "83c5be", "edf6f9", "ffddd2", "e29578")),
    ("Business & Authority", ("2b2d42", "8d99ae", "edf2f4", "ef233c", "d90429")),
    ("Nature & Outdoors", ("606c38", "283618", "fefae0", "dda15e", "bc6c25")),
    ("Vintage & Academic", ("780000", "c1121f", "fdf0d5", "003049", "669bbc")),
    ("Soft & Creative", ("cdb4db", "ffc8dd", "ffafcc", "bde0fe", "a2d2ff")),
    ("Bohemian", ("ccd5ae", "e9edc9", "fefae0", "faedcd", "d4a373")),
    ("Vibrant & Tech", ("8ecae6", "219ebc", "023047", "ffb703", "fb8500")),
    ("Craft & Artisan", ("7f5539", "a68a64", "ede0d4", "656d4a", "414833")),
    ("Tech & Night", ("000814", "001d3d", "003566", "ffc300", "ffd60a")),
    ("Education & Charts", ("264653", "2a9d8f", "e9c46a", "f4a261", "e76f51")),
    ("Forest & Eco", ("dad7cd", "a3b18a", "588157", "3a5a40", "344e41")),
    ("Elegant & Fashion", ("edafb8", "f7e1d7", "dedbd2", "b0c4b1", "4a5759")),
    ("Art & Food", ("335c67", "fff3b0", "e09f3e", "9e2a2b", "540b0e")),
    ("Luxury & Mysterious", ("22223b", "4a4e69", "9a8c98", "c9ada7", "f2e9e4")),
    ("Pure Tech Blue", ("03045e", "0077b6", "00b4d8", "90e0ef", "caf0f8")),
    ("Coastal Coral", ("0081a7", "00afb9", "fdfcdc", "fed9b7", "f07167")),
    ("Vibrant Orange Mint", ("ff9f1c", "ffbf69", "ffffff", "cbf3f0", "2ec4b6")),
    ("Platinum White Gold", ("0a0a0a", "0070f3", "d4af37", "f5f5f5", "ffffff")),
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


LAYOUTS_BY_PAGE_TYPE: dict[SlidePageType, list[str]] = {
    SlidePageType.COVER: ["cover-asymmetric", "cover-center"],
    SlidePageType.TOC: ["toc-list", "toc-grid", "toc-sidebar", "toc-cards"],
    SlidePageType.SECTION: ["section-center", "section-accent-block", "section-split"],
    SlidePageType.CONTENT: [
        "content-two-column",
        "content-icon-rows",
        "content-comparison",
        "content-timeline",
        "content-stat-callout",
        "content-showcase",
    ],
    SlidePageType.SUMMARY: ["summary-takeaways", "summary-cta", "summary-thankyou", "summary-split"],
}


def choose_design_profile(*, topic: str, template_style: str) -> DesignProfile:
    seed = f"{topic}|{template_style}".lower()
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


def enforce_layout_variety(*, nodes: list[OutlineNode], seed: str) -> None:
    prev_layout = ""
    content_layout_cursor = 0
    content_layouts = LAYOUTS_BY_PAGE_TYPE[SlidePageType.CONTENT]
    for idx, node in enumerate(nodes, start=1):
        choices = LAYOUTS_BY_PAGE_TYPE[node.page_type]
        preferred = (node.layout_hint or "").strip().lower()
        if preferred in choices and preferred != prev_layout:
            layout = preferred
        else:
            if node.page_type == SlidePageType.CONTENT:
                layout = content_layouts[content_layout_cursor % len(content_layouts)]
                content_layout_cursor += 1
                if layout == prev_layout:
                    layout = content_layouts[content_layout_cursor % len(content_layouts)]
                    content_layout_cursor += 1
            else:
                layout = choices[_stable_index(seed=f"{seed}|{idx}", size=len(choices))]
                if layout == prev_layout and len(choices) > 1:
                    layout = choices[(choices.index(layout) + 1) % len(choices)]
        node.layout_hint = layout
        prev_layout = layout


def allowed_layouts_for(page_type: SlidePageType) -> list[str]:
    return list(LAYOUTS_BY_PAGE_TYPE[page_type])


def _choose_style_name(*, template_style: str, seed: str) -> str:
    lowered = template_style.lower()
    if any(word in lowered for word in ("sharp", "finance", "data", "report", "authority")):
        return "sharp"
    if any(word in lowered for word in ("soft", "balanced", "education", "training")):
        return "soft"
    if any(word in lowered for word in ("rounded", "marketing", "creative", "product")):
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
    return int(digest[:8], 16) % size
