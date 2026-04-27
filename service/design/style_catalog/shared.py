from __future__ import annotations

from dataclasses import dataclass

STYLE_PRESET_AUTO = "auto"

PAGE_TYPE_COVER = "cover"
PAGE_TYPE_TOC = "toc"
PAGE_TYPE_SECTION = "section"
PAGE_TYPE_CONTENT = "content"
PAGE_TYPE_SUMMARY = "summary"

_PAGE_TYPE_KEYS: tuple[str, ...] = (
    PAGE_TYPE_COVER,
    PAGE_TYPE_TOC,
    PAGE_TYPE_SECTION,
    PAGE_TYPE_CONTENT,
    PAGE_TYPE_SUMMARY,
)


@dataclass(frozen=True)
class StyleDNA:
    id: str
    name: str
    prompt: str
    template_style_hint: str
    style_recipe: str
    theme_hint: dict[str, str]
    layout_family: str
    layout_pool_by_page_type: dict[str, tuple[str, ...]]
    layout_weights_by_page_type: dict[str, dict[str, int]]
    typography_profile: dict[str, str]
    density_profile: str
    shape_language: str
    decoration_policy: str
    visual_strategy_profile: str
    tone_keywords: tuple[str, ...]

    @property
    def style_signature(self) -> str:
        return (
            f"{self.id}:{self.layout_family}:{self.style_recipe}:{self.density_profile}"
        )


@dataclass(frozen=True)
class StylePreset:
    id: str
    name: str
    prompt: str
    template_style_hint: str
    style_recipe_hint: str
    style_dna_id: str


def _layout_pool(
    *,
    cover: tuple[str, ...],
    toc: tuple[str, ...],
    section: tuple[str, ...],
    content: tuple[str, ...],
    summary: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    return {
        PAGE_TYPE_COVER: cover,
        PAGE_TYPE_TOC: toc,
        PAGE_TYPE_SECTION: section,
        PAGE_TYPE_CONTENT: content,
        PAGE_TYPE_SUMMARY: summary,
    }


def _layout_weights(
    pool: dict[str, tuple[str, ...]],
    *,
    cover: dict[str, int] | None = None,
    toc: dict[str, int] | None = None,
    section: dict[str, int] | None = None,
    content: dict[str, int] | None = None,
    summary: dict[str, int] | None = None,
) -> dict[str, dict[str, int]]:
    overrides = {
        PAGE_TYPE_COVER: cover or {},
        PAGE_TYPE_TOC: toc or {},
        PAGE_TYPE_SECTION: section or {},
        PAGE_TYPE_CONTENT: content or {},
        PAGE_TYPE_SUMMARY: summary or {},
    }
    out: dict[str, dict[str, int]] = {}
    for page_type in _PAGE_TYPE_KEYS:
        bucket: dict[str, int] = {}
        for layout in pool.get(page_type, ()):
            raw = overrides.get(page_type, {}).get(layout, 1)
            bucket[layout] = max(1, min(9, int(raw)))
        out[page_type] = bucket
    return out


def _make_dna(
    *,
    style_id: str,
    name: str,
    prompt: str,
    template_style_hint: str,
    style_recipe: str,
    theme_hint: dict[str, str],
    layout_family: str,
    layout_pool_by_page_type: dict[str, tuple[str, ...]],
    layout_weights_by_page_type: dict[str, dict[str, int]],
    typography_profile: dict[str, str],
    density_profile: str,
    shape_language: str,
    decoration_policy: str,
    visual_strategy_profile: str,
    tone_keywords: tuple[str, ...],
) -> StyleDNA:
    theme = {k: v.strip().upper().lstrip("#") for k, v in theme_hint.items()}
    return StyleDNA(
        id=style_id,
        name=name,
        prompt=prompt,
        template_style_hint=template_style_hint,
        style_recipe=style_recipe,
        theme_hint=theme,
        layout_family=layout_family,
        layout_pool_by_page_type=layout_pool_by_page_type,
        layout_weights_by_page_type=layout_weights_by_page_type,
        typography_profile=dict(typography_profile),
        density_profile=density_profile,
        shape_language=shape_language,
        decoration_policy=decoration_policy,
        visual_strategy_profile=visual_strategy_profile,
        tone_keywords=tone_keywords,
    )


_POOL_GRID_FORMAL = _layout_pool(
    cover=("cover-asymmetric", "cover-center"),
    toc=("toc-grid", "toc-list", "toc-sidebar"),
    section=("section-center", "section-split", "section-accent-block"),
    content=(
        "content-two-column",
        "content-stat-callout",
        "content-comparison",
        "content-showcase",
    ),
    summary=("summary-takeaways", "summary-cta", "summary-split"),
)
_POOL_MINIMAL = _layout_pool(
    cover=("cover-center", "cover-asymmetric"),
    toc=("toc-list", "toc-sidebar"),
    section=("section-center", "section-split"),
    content=("content-two-column", "content-comparison", "content-showcase"),
    summary=("summary-split", "summary-thankyou"),
)
_POOL_CREATIVE = _layout_pool(
    cover=("cover-asymmetric", "cover-center"),
    toc=("toc-cards", "toc-grid", "toc-sidebar"),
    section=("section-split", "section-accent-block", "section-center"),
    content=(
        "content-showcase",
        "content-icon-rows",
        "content-comparison",
        "content-timeline",
    ),
    summary=("summary-cta", "summary-thankyou", "summary-split"),
)
_POOL_RESEARCH = _layout_pool(
    cover=("cover-center", "cover-asymmetric"),
    toc=("toc-grid", "toc-list", "toc-sidebar"),
    section=("section-center", "section-accent-block"),
    content=(
        "content-stat-callout",
        "content-two-column",
        "content-timeline",
        "content-comparison",
    ),
    summary=("summary-takeaways", "summary-split", "summary-cta"),
)
_POOL_BRUTAL = _layout_pool(
    cover=("cover-asymmetric", "cover-center"),
    toc=("toc-sidebar", "toc-grid"),
    section=("section-accent-block", "section-split"),
    content=(
        "content-comparison",
        "content-showcase",
        "content-two-column",
        "content-timeline",
    ),
    summary=("summary-cta", "summary-split"),
)
_POOL_NARRATIVE = _layout_pool(
    cover=("cover-center", "cover-asymmetric"),
    toc=("toc-list", "toc-cards", "toc-sidebar"),
    section=("section-split", "section-center"),
    content=(
        "content-showcase",
        "content-two-column",
        "content-icon-rows",
        "content-timeline",
    ),
    summary=("summary-thankyou", "summary-cta", "summary-split"),
)

