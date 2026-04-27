from __future__ import annotations

from pathlib import Path

from service.models import VisualPolicy
from service.run.qa_static_checks import evaluate_scratch_slide_static


def test_evaluate_scratch_slide_static_should_collect_contract_and_cache_state() -> None:
    text = "\n".join(
        [
            "const slideConfig = { type: 'content', layoutHint: 'content-showcase' };",
            "function createSlide() {}",
            "slide.addText('placeholder', { color: '#FFFFFF' });",
            "slide.addImage({ path: 'img.png', x: 1, y: 1, w: 2, h: 2 });",
            "const theme = { primary: theme.primary, accent: theme.accent, light: theme.light };",
        ]
    )
    result = evaluate_scratch_slide_static(
        slide_js_path=Path("slide-02.js"),
        slide_no=2,
        text=text,
        visual_policy=VisualPolicy.BASIC_GRAPHICS_ONLY,
        preview_cache_in={"slide-02.js": {"hash": "deadbeef", "issues": ["old"]}},
        has_valid_page_badge=lambda _js, _slide_no: False,
        extract_method_call_args=lambda *_args: [],
        dedupe_preserve_order=lambda items: list(dict.fromkeys(items)),
    )
    assert result.page_type == "content"
    assert result.observed_layout == "content-showcase"
    assert result.unchanged_preview is False
    assert result.cached_preview_issues == ["old"]
    assert any("missing export contract" in item for item in result.static_issues)
    assert any("createSlide signature invalid" in item for item in result.static_issues)
    assert any("hex color with # is forbidden" in item for item in result.static_issues)
    assert any("missing required page badge position" in item for item in result.static_issues)
    assert any("theme key usage incomplete" in item for item in result.static_issues)
    assert any("visual_policy basic_graphics_only forbids addImage()" in item for item in result.static_issues)


def test_evaluate_scratch_slide_static_should_respect_cached_preview_hash() -> None:
    text = "\n".join(
        [
            "module.exports = { createSlide, slideConfig };",
            "function createSlide(pres, theme) { return pres.addSlide(); }",
            "const slideConfig = { type: 'cover', layoutHint: 'cover-center' };",
            "theme.primary; theme.secondary; theme.accent; theme.light; theme.bg;",
        ]
    )
    first = evaluate_scratch_slide_static(
        slide_js_path=Path("slide-01.js"),
        slide_no=1,
        text=text,
        visual_policy=VisualPolicy.AUTO,
        preview_cache_in={},
        has_valid_page_badge=lambda _js, _slide_no: True,
        extract_method_call_args=lambda *_args: [],
        dedupe_preserve_order=lambda items: items,
    )
    second = evaluate_scratch_slide_static(
        slide_js_path=Path("slide-01.js"),
        slide_no=1,
        text=text,
        visual_policy=VisualPolicy.AUTO,
        preview_cache_in={"slide-01.js": {"hash": first.checksum, "issues": ["cached"]}},
        has_valid_page_badge=lambda _js, _slide_no: True,
        extract_method_call_args=lambda *_args: [],
        dedupe_preserve_order=lambda items: items,
    )
    assert second.unchanged_preview is True
    assert second.cached_preview_issues == ["cached"]
