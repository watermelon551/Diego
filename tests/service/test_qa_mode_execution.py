from __future__ import annotations

import asyncio
from pathlib import Path

from service.models import SlideArtifact, VisualPolicy
from service.run.qa_mode_execution import run_scratch_qa, run_template_qa


def test_run_scratch_qa_should_collect_missing_pptx_and_preview_cache(tmp_path: Path) -> None:
    slides_dir = tmp_path / "slides"
    slides_dir.mkdir()
    slide = slides_dir / "slide-01.js"
    slide.write_text(
        "\n".join(
            [
                "module.exports = { createSlide, slideConfig };",
                "function createSlide(pres, theme) { return pres.addSlide(); }",
                "const slideConfig = { type: 'cover', layoutHint: 'cover-center' };",
                "theme.primary; theme.secondary; theme.accent; theme.light; theme.bg;",
            ]
        ),
        encoding="utf-8",
    )

    async def run_preview(**_kwargs):
        return ["slide-01.js: preview compile failed"]

    async def markitdown_check(_path: Path):
        return True, None

    result = asyncio.run(
        run_scratch_qa(
            run_id="run-1",
            slides_dir=slides_dir,
            pptx_path=None,
            verification_cycles=0,
            preview_cache_in={},
            visual_policy=VisualPolicy.AUTO,
            run_slide_preview_qa=run_preview,
            markitdown_check=markitdown_check,
            has_valid_page_badge=lambda *_args: True,
            extract_method_call_args=lambda *_args: [],
            dedupe_preserve_order=lambda items: list(dict.fromkeys(items)),
        )
    )
    assert "slide-01.js: preview compile failed" in result.issues
    assert "scratch mode output pptx missing" in result.issues
    assert result.preview_cache_out["slide-01.js"]["checked"] is True


def test_run_template_qa_should_validate_slide_paths_and_pptx_presence(tmp_path: Path) -> None:
    slide_path = tmp_path / "slide-01.js"
    slide_path.write_text("module.exports = { createSlide, slideConfig };", encoding="utf-8")

    async def run_preview(**_kwargs):
        return ["slide-01.js: preview issue"]

    async def markitdown_check(_path: Path):
        return False, "markitdown qa failed"

    result = asyncio.run(
        run_template_qa(
            run_id="run-2",
            slides=[
                SlideArtifact(slide_no=1, js_path=str(slide_path), js_code="", status="ok"),
                SlideArtifact(slide_no=2, js_path="", js_code="", status="ok"),
            ],
            pptx_path=str(tmp_path / "missing.pptx"),
            run_slide_preview_qa=run_preview,
            markitdown_check=markitdown_check,
        )
    )
    assert "slide-01.js: preview issue" in result.issues
    assert "slide-02: js_path missing" in result.issues
    assert "template mode output pptx missing" in result.issues
    assert result.preview_cache_out == {}
