from __future__ import annotations

from service.design.skill_profile import DesignProfile, STYLE_RECIPES
from service.llm import GeneratedSlide
from service.models import OutlineNode, SlidePageType
from service.run.types import ChartPlan
from service.slides.skill_slide_renderer import build_compile_script, render_skill_slide_js


def _design() -> DesignProfile:
    return DesignProfile(
        palette_name="Test",
        theme={
            "primary": "111111",
            "secondary": "222222",
            "accent": "333333",
            "light": "EEEEEE",
            "bg": "FFFFFF",
        },
        title_font="Arial",
        body_font="Arial",
        style=STYLE_RECIPES["soft"],
    )


def test_build_compile_script_should_reference_theme_and_all_slides() -> None:
    script = build_compile_script(
        total=3,
        theme={
            "primary": "#111111",
            "secondary": "#222222",
            "accent": "#333333",
            "light": "#EEEEEE",
            "bg": "#FFFFFF",
        },
    )
    assert "const pptxgen = require('pptxgenjs');" in script
    assert "for (let i = 1; i <= 3; i++)" in script
    assert "mod.createSlide(pres, theme);" in script
    assert "primary: '111111'" in script


def test_render_skill_slide_js_should_emit_exported_slide_module() -> None:
    node = OutlineNode(
        title="Hello",
        bullets=["One", "Two"],
        page_type=SlidePageType.CONTENT,
        layout_hint="content-showcase",
    )
    generated = GeneratedSlide(
        title="Hello",
        bullets=["One", "Two"],
        citations=["src-1"],
        page_type=SlidePageType.CONTENT,
        layout_hint="content-showcase",
    )
    chart_plan = ChartPlan(
        has_verified_data=False,
        mode="qualitative_fallback",
        labels=[],
        values=[],
        unit="",
        note="No verified data",
        source="",
    )
    js_code = render_skill_slide_js(
        slide_no=2,
        total=5,
        node=node,
        generated=generated,
        design=_design(),
        chart_plan=chart_plan,
        visual_kind="image",
        visual_assets=[{"path": "asset.png", "slot": "main"}],
    )
    assert "function createSlide(pres, theme)" in js_code
    assert "module.exports = { createSlide, slideConfig };" in js_code
    assert "\"content\"" in js_code
    assert "\"asset.png\"" in js_code
    assert "slide.addImage(" in js_code
