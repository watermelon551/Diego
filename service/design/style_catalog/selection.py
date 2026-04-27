from __future__ import annotations

import hashlib

from .data import (
    STYLE_DNAS,
    STYLE_PRESETS,
    STYLE_PRESET_AUTO,
    StyleDNA,
    StylePreset,
    _AUTO_KEYWORD_TO_DNA,
    _DNA_BY_ID,
    _PRESET_BY_ID,
    _PRESET_BY_NAME,
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
    idx = _stable_index(
        seed=f"{normalized}|{template_style}|{seed}|style_dna",
        size=len(candidates),
    )
    selected_id = candidates[idx]
    selected = get_style_dna_by_id(selected_id)
    if selected is not None:
        return selected
    return STYLE_DNAS[0]


def get_style_theme_hint(style_choice: str | None) -> dict[str, str] | None:
    normalized = normalize_style_choice(style_choice)
    if normalized == STYLE_PRESET_AUTO:
        return None
    from .data import STYLE_THEME_HINTS

    theme = STYLE_THEME_HINTS.get(normalized.lower())
    return dict(theme) if isinstance(theme, dict) else None
