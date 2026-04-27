from __future__ import annotations

from .expressive import EXPRESSIVE_STYLE_DNAS
from .instructional import INSTRUCTIONAL_STYLE_DNAS
from .shared import STYLE_PRESET_AUTO, StyleDNA, StylePreset

STYLE_DNAS: tuple[StyleDNA, ...] = (
    *INSTRUCTIONAL_STYLE_DNAS,
    *EXPRESSIVE_STYLE_DNAS,
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

STYLE_THEME_HINTS: dict[str, dict[str, str]] = {
    item.id: dict(item.theme_hint) for item in STYLE_DNAS
}

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
