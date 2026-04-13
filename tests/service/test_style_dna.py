from __future__ import annotations

from service.design.skill_profile import allowed_layouts_for, enforce_layout_variety
from service.design.style_catalog import STYLE_PRESETS, list_style_dnas, resolve_style_dna_choice
from service.models import OutlineNode, SlidePageType


def _content_nodes(count: int) -> list[OutlineNode]:
    return [
        OutlineNode(
            title=f"slide-{idx}",
            bullets=[f"point-{idx}-1", f"point-{idx}-2"],
            page_type=SlidePageType.CONTENT,
            layout_hint="content-icon-rows",
        )
        for idx in range(1, count + 1)
    ]


def test_style_dna_catalog_should_cover_all_presets() -> None:
    dnas = list_style_dnas()
    assert len(dnas) == 20
    assert len({item.id for item in dnas}) == 20
    assert len(STYLE_PRESETS) == len(dnas)
    assert {item.style_dna_id for item in STYLE_PRESETS} == {item.id for item in dnas}


def test_style_dna_auto_choice_should_be_stable() -> None:
    first = resolve_style_dna_choice("auto", template_style="default", seed="stable-seed").id
    second = resolve_style_dna_choice("auto", template_style="default", seed="stable-seed").id
    assert first == second


def test_enforce_layout_variety_should_respect_style_pool_and_content_diversity() -> None:
    nodes = _content_nodes(10)
    enforce_layout_variety(nodes=nodes, seed="deck-seed", style_dna_id="minimal")
    allowed = set(allowed_layouts_for(SlidePageType.CONTENT, style_dna_id="minimal"))
    chosen = [str(node.layout_hint or "") for node in nodes]
    assert all(item in allowed for item in chosen)
    assert len(set(chosen)) >= 3


def test_enforce_layout_variety_should_produce_distinct_sequences_across_styles() -> None:
    nodes_a = _content_nodes(8)
    nodes_b = _content_nodes(8)
    enforce_layout_variety(nodes=nodes_a, seed="same-seed", style_dna_id="minimal")
    enforce_layout_variety(nodes=nodes_b, seed="same-seed", style_dna_id="memphis")
    seq_a = [node.layout_hint for node in nodes_a]
    seq_b = [node.layout_hint for node in nodes_b]
    assert seq_a != seq_b
