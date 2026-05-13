from tests.support.service_flow_shared import *  # noqa: F401,F403

def test_outline_repair_exhausted_should_fail_with_error_details(tmp_path: Path) -> None:
    client = make_client(tmp_path, llm_client=AlwaysMalformedOutlineLLM())
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Outline Repair Exhausted",
            "project_id": "p-outline-fail",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 3,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    detail = wait_status(client, run_id, {"FAILED"})
    assert detail["error_code"] == "OUTLINE_REPAIR_EXHAUSTED"
    assert detail["failed_stage"] == "OUTLINE_DRAFTING"
    assert detail["error_details"]["error_category"] == "schema"
    assert detail["error_details"]["error_details"]

def test_agentic_engine_generates_js_and_cleans_preview_artifacts(tmp_path: Path) -> None:
    settings = make_settings()
    settings = Settings(
        **{
            **settings.__dict__,
            "generation_engine": "agentic_v2",
            "debug_keep_previews": False,
            "max_slide_repair_rounds": 2,
        }
    )
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=AgenticMockLLM(),
        settings=settings,
    )
    client = TestClient(create_app(base_dir=tmp_path, orchestrator=orch))

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Agentic Engine",
            "project_id": "p-agentic",
            "rag_source_ids": ["a", "b"],
            "template_style": "default",
            "target_slide_count": 3,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED"}, timeout=20.0)

    assert final["quality_report"]["engine"] == "agentic_v2"
    assert final["quality_report"]["slides"]
    assert final["quality_gate_report"]["rounds"]
    assert final["quality_gate_report"]["threshold"] == 0
    assert final["candidate_selection_report"]["rounds"]
    assert final["candidate_selection_report"]["final_by_slide"]
    assert final["artifact_cleanup_report"]["deleted_count"] >= 1
    slides_dir = Path(final["slides"][0]["js_path"]).parent
    assert not list(slides_dir.glob("slide-*-preview.pptx"))
    with client.stream("GET", f"/v1/ppt/runs/{run_id}/events") as stream:
        body = "".join(chunk for chunk in stream.iter_text())
    assert "event: slide.codegen.completed" in body
    assert "event: artifact.cleanup.completed" in body
    assert "event: slide.plan.completed" in body
    assert "event: slide.quality.gate.completed" in body
    assert "event: slide.candidate.generated" in body
    assert "event: slide.selection.completed" in body

def test_agentic_should_not_depend_on_evaluate_quality_calls(tmp_path: Path) -> None:
    settings = make_settings()
    settings = Settings(
        **{
            **settings.__dict__,
            "generation_engine": "agentic_v2",
            "debug_keep_previews": False,
            "max_slide_repair_rounds": 2,
            "outline_timeout_retries": 1,
            "outline_timeout_backoff_sec": 0.0,
        }
    )
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=EvaluateTimeoutAgenticLLM(),
        settings=settings,
    )
    client = TestClient(create_app(base_dir=tmp_path, orchestrator=orch))

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Timeout Degrade",
            "project_id": "p-agentic-timeout-degrade",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 3,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED"}, timeout=20.0)
    assert final["status"] == "SUCCEEDED"
    assert not any(
        item["event"] == "llm.request.timeout" and "candidate.1.evaluate" in str(item.get("payload", {}).get("phase", ""))
        for item in final["events"]
    )

def test_preview_error_summary_should_expose_meaningful_line(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    reason, details = orch._summarize_process_failure(
        stderr="SyntaxError: Unexpected token ')'\n    at module.js:1:2\nNode.js v22.22.0",
        stdout="",
    )
    assert "SyntaxError" in reason
    assert "Node.js v22.22.0" not in reason
    assert "module.js" in details

def test_validate_contract_should_flag_skill_layout_violations(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    js_code = "\\n".join(
        [
            "const pptxgen = require('pptxgenjs');",
            "const slideConfig = { type: 'content', index: 2, total: 8, title: 'Bad Layout', layoutHint: 'content-two-column', bullets: ['a','b'] };",
            "function addPageBadge(pres, slide, theme, n) {",
            "  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.accent }, line: { color: theme.accent } });",
            "  slide.addText(String(n), { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 10, color: 'FFFFFF', align: 'center', margin: 0 });",
            "}",
            "function createSlide(pres, theme) {",
            "  const slide = pres.addSlide();",
            "  slide.addText(slideConfig.title, { x: 0.3, y: 0.2, w: 9.4, h: 0.7, fontSize: 30, fontFace: 'Arial', color: theme.primary, bold: true });",
            "  slide.addText(slideConfig.bullets.join(' | '), { x: 0.2, y: 1.4, w: 9.6, h: 1.2, fontSize: 16, fontFace: 'Arial', color: theme.secondary, bold: true, align: 'center', margin: 0 });",
            "  slide.addShape(pres.shapes.RECTANGLE, { x: 9.6, y: 1.8, w: 1.0, h: 1.0, fill: { color: theme.light }, line: { color: theme.secondary } });",
            "  addPageBadge(pres, slide, theme, slideConfig.index);",
            "  return slide;",
            "}",
            "module.exports = { createSlide, slideConfig };",
        ]
    )
    issues = orch._validate_slide_js_contract(js_code, slide_no=2, page_type='content')
    assert any('body text must be left-aligned' in item for item in issues)
    assert any("missing fit:'shrink'" in item for item in issues)
    assert any('title font too small' in item for item in issues)
    assert any('margin too tight' in item for item in issues)
    assert any('out of slide bounds' in item for item in issues)

def test_validate_contract_should_accept_well_spaced_content_candidate(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    js_code = "\\n".join(
        [
            "const pptxgen = require('pptxgenjs');",
            "const slideConfig = { type: 'content', index: 2, total: 8, title: 'Good Layout', layoutHint: 'content-two-column', bullets: ['point a','point b'] };",
            "function addPageBadge(pres, slide, theme, n) {",
            "  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.accent }, line: { color: theme.accent } });",
            "  slide.addText(String(n), { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 10, color: 'FFFFFF', align: 'center', margin: 0 });",
            "}",
            "function createSlide(pres, theme) {",
            "  const slide = pres.addSlide();",
            "  slide.addText(slideConfig.title, { x: 0.5, y: 0.3, w: 9.0, h: 0.8, fontSize: 40, fontFace: 'Arial', color: theme.primary, bold: true, fit: 'shrink' });",
            "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.8, y: 1.5, w: 8.4, h: 2.9, fill: { color: theme.light }, line: { color: theme.secondary } });",
            "  slide.addText(slideConfig.bullets.join(' | '), { x: 1.1, y: 1.8, w: 7.6, h: 1.8, fontSize: 16, fontFace: 'Arial', color: theme.secondary, align: 'left', margin: 0, fit: 'shrink' });",
            "  addPageBadge(pres, slide, theme, slideConfig.index);",
            "  return slide;",
            "}",
            "module.exports = { createSlide, slideConfig };",
        ]
    )
    issues = orch._validate_slide_js_contract(js_code, slide_no=2, page_type='content')
    assert not any('body text must be left-aligned' in item for item in issues)
    assert not any("missing fit:'shrink'" in item for item in issues)
    assert not any('margin too tight' in item for item in issues)
    assert not any('out of slide bounds' in item for item in issues)

def test_validate_contract_should_reject_zero_length_line_shape(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    js_code = "\n".join(
        [
            "const pptxgen = require('pptxgenjs');",
            "const slideConfig = { type: 'content', index: 2, total: 8, title: 'Line Test', layoutHint: 'content-timeline', bullets: ['a','b'] };",
            "function addPageBadge(pres, slide, theme, n) {",
            "  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.accent }, line: { color: theme.accent } });",
            "  slide.addText(String(n), { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 10, color: 'FFFFFF', align: 'center', margin: 0 });",
            "}",
            "function createSlide(pres, theme) {",
            "  const slide = pres.addSlide();",
            "  slide.addText(slideConfig.title, { x: 0.6, y: 0.4, w: 8.8, h: 0.7, fontSize: 38, fontFace: 'Arial', color: theme.primary, bold: true, fit: 'shrink' });",
            "  slide.addShape(pres.shapes.LINE, { x: 1.0, y: 2.45, w: 8.0, h: 0, line: { color: theme.secondary, pt: 1 } });",
            "  slide.addShape(pres.shapes.RECTANGLE, { x: 1.0, y: 2.7, w: 8.0, h: 1.0, fill: { color: theme.light }, line: { color: theme.secondary } });",
            "  slide.addText('a | b', { x: 1.1, y: 2.85, w: 7.8, h: 0.6, fontSize: 14, fontFace: 'Arial', color: theme.secondary, align: 'left', margin: 0, fit: 'shrink' });",
            "  addPageBadge(pres, slide, theme, slideConfig.index);",
            "  return slide;",
            "}",
            "module.exports = { createSlide, slideConfig };",
        ]
    )
    issues = orch._validate_slide_js_contract(js_code, slide_no=2, page_type="content")
    assert any("line shape geometry invalid" in item for item in issues)


def test_validate_contract_should_not_flag_valid_line_when_later_shapes_have_zero_line_width(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    js_code = "\n".join(
        [
            "const pptxgen = require('pptxgenjs');",
            "const slideConfig = { type: 'content', index: 2, total: 8, title: 'Line Test', layoutHint: 'content-timeline', bullets: ['a','b'] };",
            "function addPageBadge(pres, slide, theme, n) {",
            "  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.accent }, line: { color: theme.accent, width: 0 } });",
            "  slide.addText(String(n), { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 10, color: 'FFFFFF', align: 'center', margin: 0 });",
            "}",
            "function createSlide(pres, theme) {",
            "  const slide = pres.addSlide();",
            "  slide.addText(slideConfig.title, { x: 0.6, y: 0.4, w: 8.8, h: 0.7, fontSize: 38, fontFace: 'Arial', color: theme.primary, bold: true, fit: 'shrink' });",
            "  slide.addShape(pres.shapes.LINE, { x: 1.0, y: 2.45, w: 8.0, h: 0.01, line: { color: theme.secondary, pt: 1 } });",
            "  slide.addShape(pres.shapes.RECTANGLE, { x: 1.0, y: 2.7, w: 8.0, h: 1.0, fill: { color: theme.light }, line: { color: theme.secondary, width: 0 } });",
            "  slide.addText('a | b', { x: 1.1, y: 2.85, w: 7.8, h: 0.6, fontSize: 14, fontFace: 'Arial', color: theme.secondary, align: 'left', margin: 0, fit: 'shrink' });",
            "  addPageBadge(pres, slide, theme, slideConfig.index);",
            "  return slide;",
            "}",
            "module.exports = { createSlide, slideConfig };",
        ]
    )

    issues = orch._validate_slide_js_contract(js_code, slide_no=2, page_type="content")

    assert not any("line shape geometry invalid" in item for item in issues)


def test_validate_contract_should_allow_small_text_inside_container_shape(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    js_code = "\n".join(
        [
            "const slideConfig = { type: 'summary', index: 3, title: 'Container Test' };",
            "function createSlide(pres, theme) {",
            "  const slide = pres.addSlide();",
            "  slide.addText(slideConfig.title, { x: 0.4, y: 0.28, w: 6.0, h: 0.65, fontSize: 38, color: theme.primary, fit: 'shrink' });",
            "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.4, y: 4.55, w: 9.2, h: 0.75, fill: { color: theme.accent, transparency: 90 }, line: { color: theme.accent, pt: 1.5 } });",
            "  slide.addText('选型依据', { x: 0.6, y: 4.62, w: 1.2, h: 0.28, fontSize: 13, color: theme.accent, bold: true, margin: 0 });",
            "  slide.addText('带宽需求 · 传输距离 · 成本预算 · 环境适应性', { x: 1.9, y: 4.62, w: 7.5, h: 0.55, fontSize: 14, color: theme.secondary, margin: 0, fit: 'shrink' });",
            "  return slide;",
            "}",
            "module.exports = { createSlide, slideConfig };",
        ]
    )

    issues = orch._validate_slide_js_contract(js_code, slide_no=3, page_type="summary")

    assert not any("overlaps" in item for item in issues)


def test_validate_contract_should_not_treat_short_labels_as_body_text(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    js_code = "\n".join(
        [
            "const pptxgen = require('pptxgenjs');",
            "const slideConfig = { type: 'content', index: 7, total: 8, title: 'Future', layoutHint: 'content-comparison', bullets: ['a','b','c','d'] };",
            "function addPageBadge(pres, slide, theme, n) {",
            "  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.accent }, line: { color: theme.accent } });",
            "  slide.addText(String(n), { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 10, color: 'FFFFFF', align: 'center', margin: 0 });",
            "}",
            "function createSlide(pres, theme) {",
            "  const slide = pres.addSlide();",
            "  slide.addText(slideConfig.title, { x: 0.5, y: 0.3, w: 9.0, h: 0.8, fontSize: 40, fontFace: 'Arial', color: theme.primary, bold: true, fit: 'shrink' });",
            "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.8, y: 1.25, w: 4.1, h: 3.7, fill: { color: theme.light }, line: { color: theme.secondary } });",
            "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 5.1, y: 1.25, w: 4.1, h: 3.7, fill: { color: theme.bg }, line: { color: theme.secondary } });",
            "  slide.addText('Track A', { x: 1.1, y: 1.53, w: 3.3, h: 0.45, fontSize: 20, fontFace: 'Arial', color: theme.primary, bold: true, margin: 0 });",
            "  slide.addText('Track B', { x: 5.4, y: 1.53, w: 3.3, h: 0.45, fontSize: 20, fontFace: 'Arial', color: theme.primary, bold: true, margin: 0 });",
            "  slide.addText('body text one | body text two', { x: 1.1, y: 2.2, w: 7.5, h: 0.7, fontSize: 14, fontFace: 'Arial', color: theme.secondary, align: 'left', margin: 0, fit: 'shrink' });",
            "  addPageBadge(pres, slide, theme, slideConfig.index);",
            "  return slide;",
            "}",
            "module.exports = { createSlide, slideConfig };",
        ]
    )
    issues = orch._validate_slide_js_contract(js_code, slide_no=7, page_type="content")
    assert not any("body text should not use bold" in item for item in issues)
    assert not any("body text missing fit:'shrink'" in item for item in issues)
    assert not any("body text must be left-aligned" in item for item in issues)

def test_validate_contract_should_ignore_visual_fallback_label_text(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    js_code = "\n".join(
        [
            "const pptxgen = require('pptxgenjs');",
            "const slideConfig = { type: 'content', index: 4, total: 8, title: 'Origin', layoutHint: 'content-two-column', bullets: ['a','b'] };",
            "function addPageBadge(pres, slide, theme, n) {",
            "  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.accent }, line: { color: theme.accent } });",
            "  slide.addText(String(n), { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 10, color: 'FFFFFF', align: 'center', margin: 0 });",
            "}",
            "function createSlide(pres, theme) {",
            "  const slide = pres.addSlide();",
            "  const visualKind = 'image';",
            "  const visualAsset = { path: 'imgs/pic.png' };",
            "  slide.addText(slideConfig.title, { x: 0.5, y: 0.3, w: 9.0, h: 0.8, fontSize: 40, fontFace: 'Arial', color: theme.primary, bold: true, fit: 'shrink' });",
            "  if (visualKind === 'image' && visualAsset && visualAsset.path) {",
            "    slide.addImage({ path: visualAsset.path, x: 1.0, y: 1.55, w: 3.6, h: 3.05 });",
            "  } else {",
            "    slide.addText('Visual', { x: 1.0, y: 2.9, w: 3.5, h: 0.45, fontSize: 18, fontFace: 'Arial', color: theme.primary, bold: true, align: 'center', margin: 0 });",
            "  }",
            "  slide.addText('body text one | body text two', { x: 5.35, y: 1.6, w: 3.75, h: 0.8, fontSize: 14, fontFace: 'Arial', color: theme.secondary, align: 'left', margin: 0, fit: 'shrink' });",
            "  addPageBadge(pres, slide, theme, slideConfig.index);",
            "  return slide;",
            "}",
            "module.exports = { createSlide, slideConfig };",
        ]
    )
    issues = orch._validate_slide_js_contract(js_code, slide_no=4, page_type="content")
    assert not any("body text should not use bold" in item for item in issues)
    assert not any("body text missing fit:'shrink'" in item for item in issues)
    assert not any("body text must be left-aligned" in item for item in issues)

def test_validate_contract_should_accept_inline_badge_equivalent(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    js_code = "\n".join(
        [
            "const pptxgen = require('pptxgenjs');",
            "const slideConfig = { type: 'toc', index: 2, total: 8, title: 'TOC', layoutHint: 'toc-sidebar', bullets: ['a','b'] };",
            "function createSlide(pres, theme) {",
            "  const slide = pres.addSlide();",
            "  slide.addText(slideConfig.title, { x: 0.8, y: 0.5, w: 7.0, h: 0.8, fontSize: 40, fontFace: 'Arial', color: theme.primary, bold: true, fit: 'shrink' });",
            "  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.accent }, line: { color: theme.accent } });",
            "  slide.addText(String(slideConfig.index || 1), { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 10, color: 'FFFFFF', bold: true, align: 'center', valign: 'mid', margin: 0 });",
            "  return slide;",
            "}",
            "module.exports = { createSlide, slideConfig };",
        ]
    )
    issues = orch._validate_slide_js_contract(js_code, slide_no=2, page_type='toc')
    assert not any('missing required page badge position' in item for item in issues)

def test_validate_contract_should_flag_addtext_array_options_signature(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    js_code = "\n".join(
        [
            "const slideConfig = { type: 'content', index: 2, title: 'Bad AddText', bullets: ['a', 'b'] };",
            "function createSlide(pres, theme) {",
            "  const slide = pres.addSlide();",
            "  const titleStyle = { fontSize: 38, fontFace: 'Arial', color: theme.primary, bold: true };",
            "  const titleOpts = { x: 0.5, y: 0.4, w: 9.0, h: 0.8, fit: 'shrink' };",
            "  slide.addText(slideConfig.title, [titleStyle, titleOpts]);",
            "  slide.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 1.5, w: 8.4, h: 2.9, fill: { color: theme.light }, line: { color: theme.secondary } });",
            "  slide.addText(slideConfig.bullets.join(' | '), { x: 1.1, y: 1.8, w: 7.6, h: 1.8, fontSize: 16, fontFace: 'Arial', color: theme.secondary, align: 'left', margin: 0, fit: 'shrink' });",
            "  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.accent }, line: { color: theme.accent } });",
            "  slide.addText(String(slideConfig.index), { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 10, color: 'FFFFFF', bold: true, align: 'center', valign: 'mid', margin: 0 });",
            "  return slide;",
            "}",
            "module.exports = { createSlide, slideConfig };",
        ]
    )
    issues = orch._validate_slide_js_contract(js_code, slide_no=2, page_type='content')
    assert any('addText call signature invalid' in item for item in issues)

def test_validate_contract_should_flag_addshape_positional_signature(tmp_path: Path) -> None:
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
            "  slide.addText(slideConfig.title, { x: 0.5, y: 0.3, w: 9.0, h: 0.8, fontSize: 40, fontFace: 'Arial', color: theme.primary, bold: true, fit: 'shrink' });",
            "  slide.addShape(pres.shapes.RECTANGLE, 0.8, 1.5, 8.4, 2.9);",
            "  slide.addText(slideConfig.bullets.join(' | '), { x: 1.1, y: 1.8, w: 7.6, h: 1.8, fontSize: 16, fontFace: 'Arial', color: theme.secondary, align: 'left', margin: 0, fit: 'shrink' });",
            "  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.accent }, line: { color: theme.accent } });",
            "  slide.addText(String(slideConfig.index), { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 10, color: 'FFFFFF', bold: true, align: 'center', valign: 'mid', margin: 0 });",
            "  return slide;",
            "}",
            "module.exports = { createSlide, slideConfig };",
        ]
    )
    issues = orch._validate_slide_js_contract(js_code, slide_no=2, page_type='content')
    assert any('addShape call signature invalid' in item for item in issues)

def test_persist_qa_failure_artifacts_should_write_report_and_failed_js(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    run_id = "qa-fail-run"
    artifact_dir = orch.artifacts_base / run_id
    slides_dir = artifact_dir / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)
    (slides_dir / "slide-02.js").write_text("function createSlide(pres, theme){ const slide = pres.addSlide(); return slide; }\nconst slideConfig={index:2};\nmodule.exports = { createSlide, slideConfig };\n", encoding="utf-8")
    (slides_dir / "slide-03.js").write_text("function createSlide(pres, theme){ const slide = pres.addSlide(); return slide; }\nconst slideConfig={index:3};\nmodule.exports = { createSlide, slideConfig };\n", encoding="utf-8")

    req = CreateRunRequest(
        topic="qa-fail",
        project_id="qa-proj",
        rag_source_ids=[],
        template_style="default",
        target_slide_count=3,
        generation_mode=GenerationMode.SCRATCH,
    )
    run = RunRecord(
        run_id=run_id,
        trace_id="trace-qa-fail",
        status=RunStatus.COMPILING,
        input=req,
        artifact_dir=str(artifact_dir),
        qa_report={
            "passed": False,
            "issues": [
                "slide-02.js: missing required page badge position",
                "slide-03.js: createSlide signature invalid",
                "markitdown qa failed",
            ],
        },
    )
    asyncio.run(orch.store.add_run(run))
    details = asyncio.run(orch._persist_qa_failure_artifacts(run_id=run_id, mode=GenerationMode.SCRATCH))

    report_path = artifact_dir / "qa_failed_issues.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["issue_count"] == 3
    assert report["issues_by_slide"]["2"][0].startswith("missing required page badge position")
    assert report["issues_by_slide"]["3"][0].startswith("createSlide signature invalid")
    assert len(details.get("failed_slide_js", [])) >= 2
    assert (slides_dir / "failed" / "slide-02-last.js").exists()
    assert (slides_dir / "failed" / "slide-03-last.js").exists()

def test_agentic_should_continue_when_single_candidate_fails(tmp_path: Path) -> None:
    settings = make_settings()
    settings = Settings(
        **{
            **settings.__dict__,
            "generation_engine": "agentic_v2",
            "debug_keep_previews": False,
            "max_slide_repair_rounds": 2,
        }
    )
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=CandidateOneFailsAgenticLLM(),
        settings=settings,
    )
    client = TestClient(create_app(base_dir=tmp_path, orchestrator=orch))

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Candidate Fault Tolerance",
            "project_id": "p-agentic-candidate-fail",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 3,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED"}, timeout=20.0)
    assert final["status"] == "SUCCEEDED"
    assert any(item["event"] == "slide.candidate.generated" and item["payload"].get("error") for item in final["events"])

def test_agentic_should_emit_candidate_failures_when_llm_candidates_fail(tmp_path: Path) -> None:
    settings = make_settings()
    settings = Settings(
        **{
            **settings.__dict__,
            "generation_engine": "agentic_v2",
            "debug_keep_previews": False,
            "max_slide_repair_rounds": 2,
        }
    )
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=AllCandidatesFailAgenticLLM(),
        settings=settings,
    )
    client = TestClient(create_app(base_dir=tmp_path, orchestrator=orch))

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "All Candidates Fail",
            "project_id": "p-agentic-fail",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 1,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED", "FAILED"}, timeout=20.0)
    candidate_errors = [
        item for item in final["events"]
        if item["event"] == "slide.candidate.generated" and item["payload"].get("candidate") == 1 and item["payload"].get("error")
    ]
    assert candidate_errors

def test_repair_cycle_uses_latest_slide_candidate_not_outline_fallback(tmp_path: Path) -> None:
    llm = CaptureRepairCandidateLLM()
    client = make_client(tmp_path, llm_client=llm)
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Repair Candidate",
            "project_id": "p-repair",
            "rag_source_ids": ["a", "b"],
            "template_style": "default",
            "target_slide_count": 2,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED"})
    assert final["qa_report"]["passed"] is True
    assert llm.review_candidate_titles
    assert all(title.startswith("GEN-") for title in llm.review_candidate_titles)

def test_agentic_should_pass_slide_brief_and_asset_plan_to_llm(tmp_path: Path) -> None:
    class CaptureBriefAgenticLLM(AgenticMockLLM):
        def __init__(self) -> None:
            self.captured: list[dict] = []

        async def generate_slide_js(self, **kwargs):
            self.captured.append(
                {
                    "slide_no": kwargs.get("slide_no"),
                    "slide_plan": kwargs.get("slide_plan"),
                    "slide_brief": kwargs.get("slide_brief"),
                    "phase": "build",
                }
            )
            return await super().generate_slide_js(**kwargs)

        async def critique_slide_js(self, **kwargs):
            self.captured.append(
                {
                    "slide_no": kwargs.get("slide_no"),
                    "slide_plan": kwargs.get("slide_plan"),
                    "slide_brief": kwargs.get("slide_brief"),
                    "phase": "repair",
                }
            )
            return await super().critique_slide_js(**kwargs)
    settings = make_settings()
    settings = Settings(
        **{
            **settings.__dict__,
            "generation_engine": "agentic_v2",
            "asset_provider": "mock",
            "max_slide_repair_rounds": 2,
            "debug_keep_previews": False,
        }
    )
    llm = CaptureBriefAgenticLLM()
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=llm,
        settings=settings,
    )
    client = TestClient(create_app(base_dir=tmp_path, orchestrator=orch))

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Asset Plan Check",
            "project_id": "p-asset-brief",
            "rag_source_ids": ["r1"],
            "template_style": "default",
            "target_slide_count": 4,
            "generation_mode": "scratch",
            "visual_policy": "auto",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED"}, timeout=20.0)

    assert final["status"] == "SUCCEEDED"
    assert llm.captured
    content_calls = [item for item in llm.captured if int(item.get("slide_no", 0)) == 3]
    assert content_calls
    plan = content_calls[0]["slide_plan"] or {}
    brief = content_calls[0]["slide_brief"] or {}
    visual_plan = plan.get("visual_plan", {})
    assets = visual_plan.get("assets", []) if isinstance(visual_plan, dict) else []
    assert assets
    slots = {str(item.get("slot", "")).strip().lower() for item in assets}
    assert "main" in slots
    assert any(str(item.get("path", "")).startswith("imgs/slide-03") for item in assets)
    assert brief.get("audience")
    assert brief.get("purpose")
    assert brief.get("style_intent")

def test_llm_extract_json_should_strip_think_and_fence() -> None:
    raw = "<think>hidden reasoning</think>\n```json\n{\"score\": 91, \"issues\": [], \"repair_directives\": []}\n```"
    payload = llm_client_mod._extract_json_object(raw)
    assert payload["score"] == 91
    assert payload["issues"] == []
