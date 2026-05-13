from tests.support.service_flow_shared import *  # noqa: F401,F403


def test_auto_canonicalize_should_rewrite_addimage_positional_signature(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    node = OutlineNode(
        title="Image Contract",
        bullets=["main point"],
        page_type=SlidePageType.CONTENT,
        layout_hint="content-two-column",
    )
    js_code = "\n".join(
        [
            "const slideConfig = { type: 'content', index: 2, total: 5, title: 'Image Contract', bullets: ['a'] };",
            "function createSlide(pres, theme) {",
            "  const slide = pres.addSlide();",
            "  const visualAsset = { path: 'imgs/hero.png' };",
            "  slide.addImage(visualAsset.path, { x: 1, y: 1.5, w: 3.6, h: 2.4 });",
            "  return slide;",
            "}",
            "module.exports = { createSlide, slideConfig };",
        ]
    )

    canonical, fixes = orch._auto_canonicalize_slide_js(
        js_code,
        slide_no=2,
        node=node,
        target_slide_count=5,
    )

    assert "slide.addImage({ path: visualAsset.path, x: 1, y: 1.5, w: 3.6, h: 2.4 })" in canonical
    assert any("normalize addImage(path, opts)" in item for item in fixes)


def test_auto_canonicalize_should_rewrite_addshape_positional_signature(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    js_code = "\n".join(
        [
            "const slideConfig = { type: 'content', index: 2, title: 'Bad AddShape', bullets: ['a', 'b'] };",
            "function createSlide(pres, theme) {",
            "  const slide = pres.addSlide();",
            "  slide.addShape(pres.shapes.LINE, 7.8, 2.65, 0, 0.4, { line: { color: theme.accent, width: 2 } });",
            "  return slide;",
            "}",
            "module.exports = { createSlide, slideConfig };",
        ]
    )

    canonical, fixes = orch._auto_canonicalize_slide_js(
        js_code,
        slide_no=2,
        node=OutlineNode(title="Bad AddShape", bullets=["a", "b"]),
        target_slide_count=8,
    )

    assert "normalize addShape(shape, x, y, w, h, opts)" in " ".join(fixes)
    assert "slide.addShape(pres.shapes.LINE, { x: 7.8, y: 2.65, w: 0.01, h: 0.4, line:" in canonical


def test_auto_canonicalize_should_fix_line_zero_geometry_with_nested_options(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    js_code = "\n".join(
        [
            "const slideConfig = { type: 'content', index: 2, title: 'Line', bullets: ['a', 'b'] };",
            "function createSlide(pres, theme) {",
            "  const slide = pres.addSlide();",
            "  slide.addShape(pres.shapes.LINE, { x: 1, y: 2, w: 8, h: 0, line: { color: theme.accent, width: 2 } });",
            "  return slide;",
            "}",
            "module.exports = { createSlide, slideConfig };",
        ]
    )

    canonical, fixes = orch._auto_canonicalize_slide_js(
        js_code,
        slide_no=2,
        node=OutlineNode(title="Line", bullets=["a", "b"]),
        target_slide_count=8,
    )

    assert "fix LINE shape zero geometry" in fixes
    assert "h: 0.01" in canonical
    assert "line: { color: theme.accent, width: 2 }" in canonical


def test_auto_canonicalize_should_fix_line_negative_geometry(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    js_code = "\n".join(
        [
            "const slideConfig = { type: 'content', index: 2, title: 'Line', bullets: ['a', 'b'] };",
            "function createSlide(pres, theme) {",
            "  const slide = pres.addSlide();",
            "  slide.addShape(pres.shapes.LINE, { x: 1, y: 2, w: 8, h: -0.24, line: { color: theme.accent, width: 2 } });",
            "  return slide;",
            "}",
            "module.exports = { createSlide, slideConfig };",
        ]
    )

    canonical, fixes = orch._auto_canonicalize_slide_js(
        js_code,
        slide_no=2,
        node=OutlineNode(title="Line", bullets=["a", "b"]),
        target_slide_count=8,
    )

    assert "fix LINE shape zero geometry" in fixes
    assert "h: 0.24" in canonical
    assert "h: -0.24" not in canonical


def test_local_guardrails_should_move_return_slide_out_of_slide_config(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    js_code = "\n".join(
        [
            "function createSlide(pres, theme) {",
            "  const slide = pres.addSlide();",
            "}",
            "const slideConfig = {",
            "  index: 4,",
            "  title: 'Broken'",
            "  return slide;",
            "};",
            "module.exports = { createSlide, slideConfig };",
        ]
    )

    guarded = orch._apply_local_js_guardrails(
        js_code=js_code,
        slide_no=4,
        page_type=SlidePageType.CONTENT,
    )

    assert "title: 'Broken'" in guarded
    assert "title: 'Broken'\n  return slide;" not in guarded
    assert "return slide;\n}" in guarded


def test_validate_contract_should_block_placeholder_when_assets_planned(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    slide_plan = {
        "visual_plan": {
            "assets": [
                {"slot": "main", "path": "imgs/slide-02-main.jpg"},
                {"slot": "secondary", "path": "imgs/slide-02-secondary.jpg"},
            ]
        }
    }
    js_code = "\n".join(
        [
            "const slideConfig = { type: 'content', index: 2, total: 6, title: 'Planned Asset', bullets: ['a', 'b'] };",
            "function createSlide(pres, theme) {",
            "  const slide = pres.addSlide();",
            "  const assets = [{ slot: 'main', path: 'imgs/slide-02-main.jpg' }];",
            "  slide.addText('[主视觉图占位]', { x: 1.0, y: 2.0, w: 3.0, h: 0.5, fontSize: 16, color: theme.primary });",
            "  return slide;",
            "}",
            "module.exports = { createSlide, slideConfig };",
        ]
    )

    issues = orch._validate_slide_js_contract(
        js_code,
        slide_no=2,
        page_type="content",
        slide_plan=slide_plan,
    )

    assert any("visual assets planned but addImage() missing" in item for item in issues)
    assert any("image placeholder text remains while visual assets are planned" in item for item in issues)


def test_preview_qa_should_fail_when_compile_logs_known_fatal_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    slide_js = tmp_path / "slide-02.js"
    slide_js.write_text(
        "\n".join(
            [
                "function createSlide(pres, theme) {",
                "  const slide = pres.addSlide();",
                "  return slide;",
                "}",
                "const slideConfig = { type: 'content', index: 2, total: 6, title: 'x', bullets: ['a'] };",
                "module.exports = { createSlide, slideConfig };",
            ]
        ),
        encoding="utf-8",
    )

    def fake_preview_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0] if args else kwargs.get("args"),
            returncode=0,
            stdout="compile ok",
            stderr="ERROR: addImage() requires either 'data' or 'path' parameter!",
        )

    monkeypatch.setattr(orch.subprocess, "run", fake_preview_run)
    issues, _, diagnostics = asyncio.run(
        orch._run_slide_preview_qa_with_text(
            run_id="missing-run-ok",
            slide_js=slide_js,
            slide_no=2,
        )
    )

    assert any("preview compile failed: addImage call signature invalid" in item for item in issues)
    assert diagnostics.get("error_message") == "addImage call signature invalid"


def test_compile_template_js_should_fail_on_known_fatal_stderr_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    slides_dir = tmp_path / "template_slides"
    slides_dir.mkdir(parents=True, exist_ok=True)

    def fake_compile_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0] if args else kwargs.get("args"),
            returncode=0,
            stdout="compile ok",
            stderr="ERROR: addImage() requires either 'data' or 'path' parameter!",
        )

    monkeypatch.setattr(orch.subprocess, "run", fake_compile_run)
    ok = asyncio.run(orch._compile_service.compile_template_js(template_slides_dir=slides_dir))
    assert ok is False


def test_compile_scratch_slides_should_fail_on_known_fatal_stderr_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    run = RunRecord(
        run_id="r-compile-fail",
        trace_id="trace-compile-fail",
        status=RunStatus.COMPILING,
        input=CreateRunRequest(
            topic="compile marker",
            project_id="p-compile-marker",
            target_slide_count=2,
            generation_mode=GenerationMode.SCRATCH,
        ),
        artifact_dir=str(tmp_path / "artifacts" / "r-compile-fail"),
    )
    asyncio.run(orch.store.add_run(run))
    slides_dir = Path(run.artifact_dir) / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)

    def fake_compile_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0] if args else kwargs.get("args"),
            returncode=0,
            stdout="compile ok",
            stderr="ERROR: addImage() requires either 'data' or 'path' parameter!",
        )

    monkeypatch.setattr(orch.subprocess, "run", fake_compile_run)
    ok = asyncio.run(orch._compile_service.compile_scratch_slides(run_id=run.run_id))
    assert ok is False


def test_missing_legacy_alias_should_raise_attribute_error_instead_of_recursing(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )

    with pytest.raises(AttributeError):
        _ = orch._missing_legacy_service
