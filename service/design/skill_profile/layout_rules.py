from __future__ import annotations

import hashlib

from ...models import OutlineNode, SlidePageType
from ..style_catalog.selection import get_style_dna_by_id

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
    SlidePageType.SUMMARY: [
        "summary-takeaways",
        "summary-cta",
        "summary-thankyou",
        "summary-split",
    ],
}


def enforce_layout_variety(
    *, nodes: list[OutlineNode], seed: str, style_dna_id: str | None = None
) -> None:
    prev_layout = ""

    content_positions = [
        idx for idx, node in enumerate(nodes) if node.page_type == SlidePageType.CONTENT
    ]
    content_choices = allowed_layouts_for(
        SlidePageType.CONTENT, style_dna_id=style_dna_id
    )
    content_weights = _layout_weights_for(
        page_type=SlidePageType.CONTENT, style_dna_id=style_dna_id
    )
    content_sequence = _build_weighted_layout_sequence(
        choices=content_choices,
        weights=content_weights,
        seed=f"{seed}|content",
        count=len(content_positions),
    )
    _ensure_content_variety(
        sequence=content_sequence,
        choices=content_choices,
        target_count=len(content_positions),
    )

    content_cursor = 0
    for idx, node in enumerate(nodes, start=1):
        choices = allowed_layouts_for(node.page_type, style_dna_id=style_dna_id)
        preferred = (node.layout_hint or "").strip().lower()
        if preferred in choices and preferred != prev_layout:
            layout = preferred
        else:
            if (
                node.page_type == SlidePageType.CONTENT
                and content_cursor < len(content_sequence)
            ):
                layout = content_sequence[content_cursor]
                content_cursor += 1
            else:
                weights = _layout_weights_for(
                    page_type=node.page_type,
                    style_dna_id=style_dna_id,
                )
                seq = _build_weighted_layout_sequence(
                    choices=choices,
                    weights=weights,
                    seed=f"{seed}|{node.page_type.value}|{idx}",
                    count=1,
                )
                layout = seq[0] if seq else (choices[0] if choices else "")
            if layout == prev_layout and len(choices) > 1:
                alternatives = [item for item in choices if item != prev_layout]
                if alternatives:
                    offset = _stable_index(
                        seed=f"{seed}|{idx}|fallback",
                        size=len(alternatives),
                    )
                    layout = alternatives[offset]
        node.layout_hint = layout or node.layout_hint
        prev_layout = node.layout_hint or ""


def allowed_layouts_for(
    page_type: SlidePageType, style_dna_id: str | None = None
) -> list[str]:
    style_dna = get_style_dna_by_id(style_dna_id)
    if style_dna is not None:
        pool = style_dna.layout_pool_by_page_type.get(page_type.value, ())
        filtered = [
            item for item in pool if item in LAYOUTS_BY_PAGE_TYPE[page_type]
        ]
        if filtered:
            return filtered
    return list(LAYOUTS_BY_PAGE_TYPE[page_type])


def _layout_weights_for(
    *, page_type: SlidePageType, style_dna_id: str | None = None
) -> dict[str, int]:
    style_dna = get_style_dna_by_id(style_dna_id)
    if style_dna is None:
        return {item: 1 for item in LAYOUTS_BY_PAGE_TYPE[page_type]}
    weights = style_dna.layout_weights_by_page_type.get(page_type.value, {})
    choices = allowed_layouts_for(page_type, style_dna_id=style_dna_id)
    return {item: max(1, int(weights.get(item, 1))) for item in choices}


def _build_weighted_layout_sequence(
    *,
    choices: list[str],
    weights: dict[str, int],
    seed: str,
    count: int,
) -> list[str]:
    if not choices or count <= 0:
        return []
    bag: list[str] = []
    for item in choices:
        bag.extend([item] * max(1, int(weights.get(item, 1))))
    if not bag:
        return [choices[0]] * count

    result: list[str] = []
    prev = ""
    for idx in range(count):
        pick_idx = _stable_index(seed=f"{seed}|{idx}", size=len(bag))
        candidate = bag[pick_idx]
        if candidate == prev and len(choices) > 1:
            alt = [item for item in choices if item != prev]
            candidate = alt[_stable_index(seed=f"{seed}|{idx}|alt", size=len(alt))]
        result.append(candidate)
        prev = candidate
    return result


def _ensure_content_variety(
    *, sequence: list[str], choices: list[str], target_count: int
) -> None:
    if target_count < 8 or len(choices) < 3 or not sequence:
        return
    required_unique = min(3, len(choices))
    seen = list(dict.fromkeys(sequence))
    if len(seen) >= required_unique:
        return
    missing = [item for item in choices if item not in seen][
        : required_unique - len(seen)
    ]
    for idx, item in enumerate(missing, start=1):
        pos = min(len(sequence) - 1, idx * 2)
        sequence[pos] = item


def _stable_index(*, seed: str, size: int) -> int:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % max(1, size)
