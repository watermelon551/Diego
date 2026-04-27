from __future__ import annotations

from service.design.design_resolution import (
    normalize_hex6,
    resolve_font_from_intent,
    resolve_style_recipe_name,
)


def test_normalize_hex6_should_expand_short_hex_and_reject_invalid_values() -> None:
    assert normalize_hex6("#abc") == "AABBCC"
    assert normalize_hex6("0f1e2d") == "0F1E2D"
    assert normalize_hex6("xyz") is None
    assert normalize_hex6("#12345") is None


def test_resolve_style_recipe_name_should_follow_generic_intent_keywords() -> None:
    assert (
        resolve_style_recipe_name(
            design_intent={},
            style_intent="finance authority",
            template_style="default",
            fallback="soft",
        )
        == "sharp"
    )
    assert (
        resolve_style_recipe_name(
            design_intent={},
            style_intent="creative marketing",
            template_style="default",
            fallback="soft",
        )
        == "rounded"
    )
    assert (
        resolve_style_recipe_name(
            design_intent={"style_recipe": "pill"},
            style_intent="ignored",
            template_style="ignored",
            fallback="soft",
        )
        == "pill"
    )


def test_resolve_font_from_intent_should_keep_repo_supported_fonts_only() -> None:
    assert resolve_font_from_intent(preferred="Georgia", fallback="Arial") == "Georgia"
    assert resolve_font_from_intent(preferred="Imaginary Sans", fallback="Arial") == "Arial"
