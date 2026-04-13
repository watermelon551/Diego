from __future__ import annotations

import hashlib
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
        return f"{self.id}:{self.layout_family}:{self.style_recipe}:{self.density_profile}"


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
    content=("content-two-column", "content-stat-callout", "content-comparison", "content-showcase"),
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
    content=("content-showcase", "content-icon-rows", "content-comparison", "content-timeline"),
    summary=("summary-cta", "summary-thankyou", "summary-split"),
)
_POOL_RESEARCH = _layout_pool(
    cover=("cover-center", "cover-asymmetric"),
    toc=("toc-grid", "toc-list", "toc-sidebar"),
    section=("section-center", "section-accent-block"),
    content=("content-stat-callout", "content-two-column", "content-timeline", "content-comparison"),
    summary=("summary-takeaways", "summary-split", "summary-cta"),
)
_POOL_BRUTAL = _layout_pool(
    cover=("cover-asymmetric", "cover-center"),
    toc=("toc-sidebar", "toc-grid"),
    section=("section-accent-block", "section-split"),
    content=("content-comparison", "content-showcase", "content-two-column", "content-timeline"),
    summary=("summary-cta", "summary-split"),
)
_POOL_NARRATIVE = _layout_pool(
    cover=("cover-center", "cover-asymmetric"),
    toc=("toc-list", "toc-cards", "toc-sidebar"),
    section=("section-split", "section-center"),
    content=("content-showcase", "content-two-column", "content-icon-rows", "content-timeline"),
    summary=("summary-thankyou", "summary-cta", "summary-split"),
)


STYLE_DNAS: tuple[StyleDNA, ...] = (
    _make_dna(
        style_id="minimal-teaching",
        name="简约教学",
        prompt="传统教学课件风格，结构清晰、层级明确、稳定统一、便于讲授。",
        template_style_hint="preset:minimal-teaching education training",
        style_recipe="soft",
        theme_hint={"primary": "1F3A5F", "secondary": "4E6A8E", "accent": "2E86DE", "light": "E9EEF5", "bg": "F7FAFC"},
        layout_family="classroom-structured",
        layout_pool_by_page_type=_POOL_GRID_FORMAL,
        layout_weights_by_page_type=_layout_weights(
            _POOL_GRID_FORMAL,
            content={"content-two-column": 4, "content-stat-callout": 3, "content-comparison": 2, "content-showcase": 1},
            toc={"toc-list": 3, "toc-grid": 2, "toc-sidebar": 1},
        ),
        typography_profile={"title_font": "Cambria", "body_font": "Calibri"},
        density_profile="balanced",
        shape_language="rounded-calm",
        decoration_policy="minimal-instructional",
        visual_strategy_profile="diagram-first",
        tone_keywords=("education", "training", "clarity"),
    ),
    _make_dna(
        style_id="academic",
        name="学术",
        prompt="学术风格，理性、规范、清晰，强调研究表达、逻辑结构与图表可读性。",
        template_style_hint="preset:academic report data authority",
        style_recipe="sharp",
        theme_hint={"primary": "1F2937", "secondary": "4B5563", "accent": "2563EB", "light": "E5E7EB", "bg": "F9FAFB"},
        layout_family="research-grid",
        layout_pool_by_page_type=_POOL_RESEARCH,
        layout_weights_by_page_type=_layout_weights(
            _POOL_RESEARCH,
            content={"content-stat-callout": 4, "content-two-column": 3, "content-timeline": 2, "content-comparison": 2},
            summary={"summary-takeaways": 4, "summary-split": 2, "summary-cta": 1},
        ),
        typography_profile={"title_font": "Georgia", "body_font": "Calibri"},
        density_profile="dense",
        shape_language="line-precision",
        decoration_policy="journal-clean",
        visual_strategy_profile="evidence-priority",
        tone_keywords=("research", "academic", "thesis"),
    ),
    _make_dna(
        style_id="minimal",
        name="极简",
        prompt="极简风格，干净克制，突出留白、层级和信息节奏，减少装饰。",
        template_style_hint="preset:minimal balanced",
        style_recipe="soft",
        theme_hint={"primary": "1A1A1A", "secondary": "666666", "accent": "3B82F6", "light": "EDEDED", "bg": "FFFFFF"},
        layout_family="whitespace-editorial",
        layout_pool_by_page_type=_POOL_MINIMAL,
        layout_weights_by_page_type=_layout_weights(
            _POOL_MINIMAL,
            content={"content-two-column": 4, "content-comparison": 3, "content-showcase": 2},
            summary={"summary-split": 3, "summary-thankyou": 2},
        ),
        typography_profile={"title_font": "Trebuchet MS", "body_font": "Calibri"},
        density_profile="airy",
        shape_language="thin-subtle",
        decoration_policy="strict-minimal",
        visual_strategy_profile="focus-block",
        tone_keywords=("minimal", "clean", "quiet"),
    ),
    _make_dna(
        style_id="professional",
        name="专业",
        prompt="专业商务科技风格，沉稳正式，模块化表达，强调可信度。",
        template_style_hint="preset:professional finance report authority",
        style_recipe="sharp",
        theme_hint={"primary": "0B1F3A", "secondary": "1E3A5F", "accent": "00A3FF", "light": "E8EEF5", "bg": "F4F7FB"},
        layout_family="enterprise-modular",
        layout_pool_by_page_type=_POOL_GRID_FORMAL,
        layout_weights_by_page_type=_layout_weights(
            _POOL_GRID_FORMAL,
            content={"content-stat-callout": 4, "content-two-column": 3, "content-showcase": 2, "content-comparison": 2},
            toc={"toc-grid": 3, "toc-sidebar": 2, "toc-list": 2},
        ),
        typography_profile={"title_font": "Cambria", "body_font": "Calibri"},
        density_profile="balanced",
        shape_language="modular-solid",
        decoration_policy="low-gloss-tech",
        visual_strategy_profile="data-callout",
        tone_keywords=("business", "enterprise", "strategy"),
    ),
    _make_dna(
        style_id="botanical",
        name="植境",
        prompt="自然生态风格，清新安静，轻纹理与植物意象，重视舒适阅读。",
        template_style_hint="preset:botanical creative",
        style_recipe="rounded",
        theme_hint={"primary": "2F5D50", "secondary": "5E8B7E", "accent": "8CBF5A", "light": "E9F2EB", "bg": "F7FBF7"},
        layout_family="organic-balance",
        layout_pool_by_page_type=_POOL_NARRATIVE,
        layout_weights_by_page_type=_layout_weights(
            _POOL_NARRATIVE,
            content={"content-showcase": 4, "content-two-column": 2, "content-icon-rows": 3, "content-timeline": 1},
            summary={"summary-thankyou": 3, "summary-cta": 2, "summary-split": 2},
        ),
        typography_profile={"title_font": "Palatino Linotype", "body_font": "Garamond"},
        density_profile="airy",
        shape_language="soft-organic",
        decoration_policy="light-texture",
        visual_strategy_profile="imagery-led",
        tone_keywords=("nature", "eco", "wellness"),
    ),
    _make_dna(
        style_id="wabi-sabi",
        name="侘寂",
        prompt="侘寂风格，低饱和质朴、留白克制，强调材质感与东方审美。",
        template_style_hint="preset:wabi-sabi soft balanced",
        style_recipe="soft",
        theme_hint={"primary": "4A3F35", "secondary": "7B6D5D", "accent": "B08B67", "light": "EDE6DE", "bg": "F7F3ED"},
        layout_family="asymmetric-quiet",
        layout_pool_by_page_type=_POOL_MINIMAL,
        layout_weights_by_page_type=_layout_weights(
            _POOL_MINIMAL,
            content={"content-showcase": 3, "content-two-column": 3, "content-comparison": 2},
            section={"section-center": 3, "section-split": 1},
        ),
        typography_profile={"title_font": "Georgia", "body_font": "Calibri"},
        density_profile="airy",
        shape_language="matte-imperfect",
        decoration_policy="texture-subtle",
        visual_strategy_profile="negative-space",
        tone_keywords=("wabi", "zen", "humanities"),
    ),
    _make_dna(
        style_id="memphis",
        name="孟菲斯",
        prompt="孟菲斯风格，活泼几何、强节奏、图形化，突出创意与年轻感。",
        template_style_hint="preset:memphis creative marketing",
        style_recipe="rounded",
        theme_hint={"primary": "111111", "secondary": "2A2A2A", "accent": "FF3D81", "light": "FFE66D", "bg": "FFF6EC"},
        layout_family="geo-pop",
        layout_pool_by_page_type=_POOL_CREATIVE,
        layout_weights_by_page_type=_layout_weights(
            _POOL_CREATIVE,
            content={"content-icon-rows": 4, "content-showcase": 3, "content-comparison": 2, "content-timeline": 2},
            toc={"toc-cards": 4, "toc-grid": 3, "toc-sidebar": 1},
        ),
        typography_profile={"title_font": "Trebuchet MS", "body_font": "Arial"},
        density_profile="balanced",
        shape_language="geometry-contrast",
        decoration_policy="decorative-allowed",
        visual_strategy_profile="shape-burst",
        tone_keywords=("memphis", "playful", "youth"),
    ),
    _make_dna(
        style_id="constructivism",
        name="构成主义",
        prompt="构成主义风格，高对比、斜切与非对称构图，强调力量感。",
        template_style_hint="preset:constructivism brutal sharp data",
        style_recipe="sharp",
        theme_hint={"primary": "111111", "secondary": "2E2E2E", "accent": "E10600", "light": "F5F5F5", "bg": "FFF8E1"},
        layout_family="poster-diagonal",
        layout_pool_by_page_type=_POOL_BRUTAL,
        layout_weights_by_page_type=_layout_weights(
            _POOL_BRUTAL,
            content={"content-comparison": 4, "content-showcase": 3, "content-two-column": 2, "content-timeline": 3},
            section={"section-accent-block": 4, "section-split": 3},
        ),
        typography_profile={"title_font": "Arial", "body_font": "Arial"},
        density_profile="dense",
        shape_language="hard-edges",
        decoration_policy="poster-strong",
        visual_strategy_profile="directional-flow",
        tone_keywords=("constructivism", "manifesto", "contrast"),
    ),
    _make_dna(
        style_id="neo-brutalism",
        name="新粗野主义",
        prompt="新粗野主义风格，直接硬朗、实验感强，粗体与块面优先。",
        template_style_hint="preset:neo-brutalism brutal sharp",
        style_recipe="sharp",
        theme_hint={"primary": "0A0A0A", "secondary": "1D1D1D", "accent": "00D1FF", "light": "F4F4F4", "bg": "FFFFFF"},
        layout_family="raw-block",
        layout_pool_by_page_type=_POOL_BRUTAL,
        layout_weights_by_page_type=_layout_weights(
            _POOL_BRUTAL,
            content={"content-showcase": 4, "content-comparison": 4, "content-two-column": 2, "content-timeline": 1},
            toc={"toc-sidebar": 4, "toc-grid": 2},
        ),
        typography_profile={"title_font": "Arial", "body_font": "Arial"},
        density_profile="compact",
        shape_language="thick-outline",
        decoration_policy="raw-ui",
        visual_strategy_profile="impact-first",
        tone_keywords=("brutalism", "raw", "experimental"),
    ),
    _make_dna(
        style_id="8bit",
        name="8-bit",
        prompt="像素复古风格，电子游戏界面语言，方块图形与像素边框。",
        template_style_hint="preset:8bit retro pixel",
        style_recipe="sharp",
        theme_hint={"primary": "1A1A1A", "secondary": "3A3A3A", "accent": "00E676", "light": "F9D65C", "bg": "F5F7FF"},
        layout_family="pixel-grid",
        layout_pool_by_page_type=_POOL_CREATIVE,
        layout_weights_by_page_type=_layout_weights(
            _POOL_CREATIVE,
            content={"content-icon-rows": 4, "content-two-column": 3, "content-timeline": 2, "content-showcase": 2},
            toc={"toc-cards": 3, "toc-grid": 3, "toc-sidebar": 1},
        ),
        typography_profile={"title_font": "Arial", "body_font": "Arial"},
        density_profile="compact",
        shape_language="square-pixel",
        decoration_policy="retro-ui",
        visual_strategy_profile="icon-heavy",
        tone_keywords=("pixel", "retro", "game"),
    ),
    _make_dna(
        style_id="electro-pop",
        name="流行电子",
        prompt="电子潮流风格，霓虹发光、未来感和高冲击构图。",
        template_style_hint="preset:electro-pop premium brand luxury",
        style_recipe="pill",
        theme_hint={"primary": "120024", "secondary": "3A0B63", "accent": "FF00C8", "light": "00E5FF", "bg": "0E0A1F"},
        layout_family="neon-stage",
        layout_pool_by_page_type=_POOL_CREATIVE,
        layout_weights_by_page_type=_layout_weights(
            _POOL_CREATIVE,
            content={"content-showcase": 4, "content-timeline": 3, "content-icon-rows": 2, "content-comparison": 2},
            section={"section-split": 4, "section-accent-block": 2, "section-center": 1},
        ),
        typography_profile={"title_font": "Arial", "body_font": "Calibri"},
        density_profile="balanced",
        shape_language="glow-rounded",
        decoration_policy="neon-accent",
        visual_strategy_profile="hero-visual",
        tone_keywords=("electro", "neon", "future"),
    ),
    _make_dna(
        style_id="geo-bold",
        name="几何粗体",
        prompt="几何粗体风格，块面结构与大字号标题，强调识别度。",
        template_style_hint="preset:geo-bold sharp data",
        style_recipe="sharp",
        theme_hint={"primary": "111111", "secondary": "2B2B2B", "accent": "FF6B00", "light": "E8F0FF", "bg": "FFFFFF"},
        layout_family="bold-geometry",
        layout_pool_by_page_type=_POOL_BRUTAL,
        layout_weights_by_page_type=_layout_weights(
            _POOL_BRUTAL,
            content={"content-comparison": 4, "content-two-column": 3, "content-showcase": 2, "content-timeline": 2},
            toc={"toc-grid": 3, "toc-sidebar": 2},
        ),
        typography_profile={"title_font": "Arial", "body_font": "Arial"},
        density_profile="balanced",
        shape_language="block-geometry",
        decoration_policy="high-contrast",
        visual_strategy_profile="headline-dominant",
        tone_keywords=("geometric", "bold", "graphic"),
    ),
    _make_dna(
        style_id="morandi",
        name="莫兰迪",
        prompt="莫兰迪风格，低饱和柔和配色，克制优雅，文艺舒缓。",
        template_style_hint="preset:morandi soft balanced",
        style_recipe="soft",
        theme_hint={"primary": "6E6A67", "secondary": "8F8A86", "accent": "BCA89F", "light": "E8E2DC", "bg": "F7F4F1"},
        layout_family="muted-editorial",
        layout_pool_by_page_type=_POOL_MINIMAL,
        layout_weights_by_page_type=_layout_weights(
            _POOL_MINIMAL,
            content={"content-showcase": 3, "content-two-column": 3, "content-comparison": 2},
            summary={"summary-thankyou": 3, "summary-split": 2},
        ),
        typography_profile={"title_font": "Palatino Linotype", "body_font": "Garamond"},
        density_profile="airy",
        shape_language="soft-muted",
        decoration_policy="subtle-gradient",
        visual_strategy_profile="calm-rhythm",
        tone_keywords=("morandi", "elegant", "art"),
    ),
    _make_dna(
        style_id="nordic-research",
        name="北欧研究",
        prompt="北欧研究风格，理性自然，清爽网格与低干扰背景。",
        template_style_hint="preset:nordic-research education",
        style_recipe="soft",
        theme_hint={"primary": "223344", "secondary": "4A5F70", "accent": "5FA8D3", "light": "E8EEF2", "bg": "F7FAFC"},
        layout_family="scandi-grid",
        layout_pool_by_page_type=_POOL_RESEARCH,
        layout_weights_by_page_type=_layout_weights(
            _POOL_RESEARCH,
            content={"content-two-column": 3, "content-stat-callout": 3, "content-timeline": 2, "content-comparison": 2},
            section={"section-center": 3, "section-accent-block": 1},
        ),
        typography_profile={"title_font": "Cambria", "body_font": "Calibri"},
        density_profile="balanced",
        shape_language="clean-functional",
        decoration_policy="low-noise",
        visual_strategy_profile="information-balanced",
        tone_keywords=("nordic", "scandi", "research"),
    ),
    _make_dna(
        style_id="emotional-flow",
        name="感性流动",
        prompt="感性流动风格，柔雾氛围、曲线与半透明层次，强调情绪表达。",
        template_style_hint="preset:emotional-flow creative rounded",
        style_recipe="rounded",
        theme_hint={"primary": "5A4E7C", "secondary": "7E6FAE", "accent": "F08AA6", "light": "F5EAF3", "bg": "FFF7FB"},
        layout_family="fluid-narrative",
        layout_pool_by_page_type=_POOL_NARRATIVE,
        layout_weights_by_page_type=_layout_weights(
            _POOL_NARRATIVE,
            content={"content-showcase": 4, "content-timeline": 3, "content-two-column": 2, "content-icon-rows": 2},
            toc={"toc-cards": 3, "toc-list": 2, "toc-sidebar": 1},
        ),
        typography_profile={"title_font": "Palatino Linotype", "body_font": "Garamond"},
        density_profile="airy",
        shape_language="curved-organic",
        decoration_policy="soft-glow",
        visual_strategy_profile="storytelling-flow",
        tone_keywords=("emotional", "flow", "story"),
    ),
    _make_dna(
        style_id="cinema-minimal",
        name="影院极简",
        prompt="影院极简风格，低照度电影感、光影聚焦、深邃克制。",
        template_style_hint="preset:cinema-minimal soft balanced",
        style_recipe="soft",
        theme_hint={"primary": "F2F2F2", "secondary": "BFBFBF", "accent": "F5C16C", "light": "2A2A2A", "bg": "111111"},
        layout_family="cinematic-focus",
        layout_pool_by_page_type=_POOL_MINIMAL,
        layout_weights_by_page_type=_layout_weights(
            _POOL_MINIMAL,
            content={"content-showcase": 4, "content-two-column": 2, "content-comparison": 2},
            cover={"cover-center": 3, "cover-asymmetric": 1},
        ),
        typography_profile={"title_font": "Georgia", "body_font": "Calibri"},
        density_profile="airy",
        shape_language="light-beam",
        decoration_policy="shadow-depth",
        visual_strategy_profile="spotlight-hero",
        tone_keywords=("cinema", "movie", "dark"),
    ),
    _make_dna(
        style_id="rational-blue",
        name="理性蓝调",
        prompt="理性蓝调风格，冷静专业，强调分析结构与科技可信感。",
        template_style_hint="preset:rational-blue finance data",
        style_recipe="sharp",
        theme_hint={"primary": "1B2A4A", "secondary": "345A8A", "accent": "4DA3FF", "light": "E7EEF8", "bg": "F5F8FD"},
        layout_family="analytic-blueprint",
        layout_pool_by_page_type=_POOL_RESEARCH,
        layout_weights_by_page_type=_layout_weights(
            _POOL_RESEARCH,
            content={"content-stat-callout": 4, "content-two-column": 3, "content-comparison": 2, "content-timeline": 2},
            toc={"toc-grid": 3, "toc-list": 2, "toc-sidebar": 2},
        ),
        typography_profile={"title_font": "Cambria", "body_font": "Calibri"},
        density_profile="balanced",
        shape_language="tech-clean",
        decoration_policy="subtle-tech-lines",
        visual_strategy_profile="analysis-first",
        tone_keywords=("rational", "tech", "analysis"),
    ),
    _make_dna(
        style_id="warm-vc",
        name="暖调创投",
        prompt="暖调创投风格，商业质感与亲和力并存，适合路演提案。",
        template_style_hint="preset:warm-vc marketing rounded",
        style_recipe="rounded",
        theme_hint={"primary": "4A2E22", "secondary": "7A4F3A", "accent": "F28C52", "light": "F9E7DA", "bg": "FFF9F4"},
        layout_family="pitch-narrative",
        layout_pool_by_page_type=_POOL_GRID_FORMAL,
        layout_weights_by_page_type=_layout_weights(
            _POOL_GRID_FORMAL,
            content={"content-showcase": 4, "content-two-column": 3, "content-stat-callout": 2, "content-comparison": 2},
            summary={"summary-cta": 4, "summary-takeaways": 2, "summary-split": 2},
        ),
        typography_profile={"title_font": "Trebuchet MS", "body_font": "Calibri"},
        density_profile="balanced",
        shape_language="rounded-card",
        decoration_policy="warm-gradient",
        visual_strategy_profile="narrative-callout",
        tone_keywords=("vc", "pitch", "brand"),
    ),
    _make_dna(
        style_id="contemporary-academic",
        name="当代学术",
        prompt="当代学术风格，现代简洁，研究展板式信息组织。",
        template_style_hint="preset:contemporary-academic report authority",
        style_recipe="sharp",
        theme_hint={"primary": "1E2430", "secondary": "4A5568", "accent": "6B8AF5", "light": "E8EBF2", "bg": "FAFBFD"},
        layout_family="poster-research",
        layout_pool_by_page_type=_POOL_RESEARCH,
        layout_weights_by_page_type=_layout_weights(
            _POOL_RESEARCH,
            content={"content-stat-callout": 3, "content-two-column": 3, "content-comparison": 3, "content-timeline": 2},
            section={"section-center": 2, "section-accent-block": 2},
        ),
        typography_profile={"title_font": "Georgia", "body_font": "Calibri"},
        density_profile="dense",
        shape_language="fine-lines",
        decoration_policy="exhibition-tags",
        visual_strategy_profile="concept-structure",
        tone_keywords=("contemporary", "academic", "poster"),
    ),
    _make_dna(
        style_id="academic-curation",
        name="学术策展",
        prompt="学术策展风格，轻盈克制、展签式排版，强调图文并置。",
        template_style_hint="preset:academic-curation education",
        style_recipe="soft",
        theme_hint={"primary": "2F3542", "secondary": "57606F", "accent": "70A1FF", "light": "EAF0F6", "bg": "FCFDFF"},
        layout_family="curation-caption",
        layout_pool_by_page_type=_POOL_NARRATIVE,
        layout_weights_by_page_type=_layout_weights(
            _POOL_NARRATIVE,
            content={"content-showcase": 3, "content-two-column": 2, "content-icon-rows": 2, "content-timeline": 3},
            toc={"toc-list": 3, "toc-cards": 2, "toc-sidebar": 1},
        ),
        typography_profile={"title_font": "Palatino Linotype", "body_font": "Garamond"},
        density_profile="balanced",
        shape_language="caption-light",
        decoration_policy="label-system",
        visual_strategy_profile="image-text-pair",
        tone_keywords=("curation", "exhibition", "culture"),
    ),
)


STYLE_PRESETS: tuple[StylePreset, ...] = tuple(
    StylePreset(
        id=item.id,
        name=item.name,
        prompt=item.prompt,
        template_style_hint=item.template_style_hint,
        style_recipe_hint=item.style_recipe,
        style_dna_id=item.id,
    )
    for item in STYLE_DNAS
)

STYLE_THEME_HINTS: dict[str, dict[str, str]] = {item.id: dict(item.theme_hint) for item in STYLE_DNAS}

_DNA_BY_ID = {item.id.lower(): item for item in STYLE_DNAS}
_PRESET_BY_ID = {item.id.lower(): item for item in STYLE_PRESETS}
_PRESET_BY_NAME = {item.name.lower(): item for item in STYLE_PRESETS}

_AUTO_KEYWORD_TO_DNA: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("teach", ("minimal-teaching",)),
    ("training", ("minimal-teaching", "nordic-research")),
    ("academic", ("academic", "contemporary-academic", "academic-curation")),
    ("research", ("academic", "nordic-research", "contemporary-academic")),
    ("minimal", ("minimal", "cinema-minimal")),
    ("business", ("professional", "rational-blue", "warm-vc")),
    ("finance", ("professional", "rational-blue")),
    ("eco", ("botanical",)),
    ("nature", ("botanical", "wabi-sabi")),
    ("wabi", ("wabi-sabi",)),
    ("memphis", ("memphis",)),
    ("construct", ("constructivism",)),
    ("brutal", ("neo-brutalism",)),
    ("8bit", ("8bit",)),
    ("pixel", ("8bit",)),
    ("electro", ("electro-pop",)),
    ("neon", ("electro-pop",)),
    ("geo", ("geo-bold",)),
    ("morandi", ("morandi",)),
    ("nordic", ("nordic-research",)),
    ("emotion", ("emotional-flow",)),
    ("cinema", ("cinema-minimal",)),
    ("blue", ("rational-blue",)),
    ("vc", ("warm-vc",)),
    ("pitch", ("warm-vc",)),
    ("curation", ("academic-curation",)),
)


def _stable_index(*, seed: str, size: int) -> int:
    if size <= 1:
        return 0
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % size


def normalize_style_choice(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return STYLE_PRESET_AUTO
    lowered = raw.lower()
    if lowered == STYLE_PRESET_AUTO:
        return STYLE_PRESET_AUTO
    if lowered in _PRESET_BY_ID:
        return _PRESET_BY_ID[lowered].id
    if lowered in _PRESET_BY_NAME:
        return _PRESET_BY_NAME[lowered].id
    return raw


def is_valid_style_choice(value: str | None) -> bool:
    normalized = normalize_style_choice(value)
    return normalized == STYLE_PRESET_AUTO or normalized.lower() in _PRESET_BY_ID


def resolve_style_choice(value: str | None) -> StylePreset | None:
    normalized = normalize_style_choice(value)
    if normalized == STYLE_PRESET_AUTO:
        return None
    return _PRESET_BY_ID.get(normalized.lower())


def get_style_dna_by_id(style_dna_id: str | None) -> StyleDNA | None:
    key = (style_dna_id or "").strip().lower()
    if not key:
        return None
    return _DNA_BY_ID.get(key)


def list_style_presets() -> list[StylePreset]:
    return list(STYLE_PRESETS)


def list_style_dnas() -> list[StyleDNA]:
    return list(STYLE_DNAS)


def _infer_style_dna_candidates(*, template_style: str) -> list[str]:
    lowered = template_style.strip().lower()
    if not lowered:
        return [item.id for item in STYLE_DNAS]
    picked: list[str] = []
    for keyword, dna_ids in _AUTO_KEYWORD_TO_DNA:
        if keyword in lowered:
            for dna_id in dna_ids:
                if dna_id not in picked:
                    picked.append(dna_id)
    return picked or [item.id for item in STYLE_DNAS]


def resolve_style_dna_choice(
    value: str | None,
    *,
    template_style: str = "",
    seed: str = "",
) -> StyleDNA:
    normalized = normalize_style_choice(value)
    if normalized != STYLE_PRESET_AUTO:
        matched = get_style_dna_by_id(normalized)
        if matched is not None:
            return matched

    candidates = _infer_style_dna_candidates(template_style=template_style)
    idx = _stable_index(seed=f"{normalized}|{template_style}|{seed}|style_dna", size=len(candidates))
    selected_id = candidates[idx]
    selected = get_style_dna_by_id(selected_id)
    if selected is not None:
        return selected
    return STYLE_DNAS[0]


def get_style_theme_hint(style_choice: str | None) -> dict[str, str] | None:
    normalized = normalize_style_choice(style_choice)
    if normalized == STYLE_PRESET_AUTO:
        return None
    theme = STYLE_THEME_HINTS.get(normalized.lower())
    return dict(theme) if isinstance(theme, dict) else None
