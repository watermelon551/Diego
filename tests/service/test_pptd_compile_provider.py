from __future__ import annotations

import asyncio
import base64
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from service.models import (
    CreateRunRequest,
    GenerationMode,
    OutlineDocument,
    OutlineNode,
    RunRecord,
    RunStatus,
    SlideArtifact,
    SlidePageType,
)
from service.run.engines import CompileEngine
from service.run.engines.pptd_layout import PptdDeckWriter
from service.run.engines.pptd_preview import PptdProjectPreviewRenderer
from service.run.slide_scene.pptd_scene import (
    apply_pptd_scene_operations,
    build_pptd_slide_scene,
)

from tests.support.runtime_helpers import make_settings


class _Store:
    def __init__(self, run: RunRecord) -> None:
        self.run = run

    async def get_run(self, run_id: str) -> RunRecord | None:
        return self.run if run_id == self.run.run_id else None


def test_compile_provider_pptd_builds_checked_project_and_pptx(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        command = " ".join(args)
        if "convert.sh" in command:
            output = tmp_path / "artifacts" / "r-pptd" / "slides" / "output" / "presentation.pptx"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"pptx")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="Created", stderr="")
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="Checking presentation.pptd\nSummary: 0 errors, 0 warnings",
            stderr="",
        )

    run = RunRecord(
        run_id="r-pptd",
        trace_id="t-pptd",
        status=RunStatus.COMPILING,
        input=CreateRunRequest(
            topic="Data Link Layer",
            project_id="p-pptd",
            target_slide_count=2,
            generation_mode=GenerationMode.SCRATCH,
        ),
        artifact_dir=str(tmp_path / "artifacts" / "r-pptd"),
        outline=OutlineDocument(
            version=1,
            summary="network courseware",
            nodes=[
                OutlineNode(title="Data Link Layer", bullets=["Framing", "Error control"]),
                OutlineNode(title="Sliding Window", bullets=["ACK", "Retransmission"]),
            ],
        ),
        slides=[
            SlideArtifact(slide_no=1, js_code="", status="ready"),
            SlideArtifact(slide_no=2, js_code="", status="ready"),
        ],
    )
    runtime = SimpleNamespace(
        settings=make_settings(
            compile_provider="pptd",
            pptd_skill_dir=str(tmp_path / "pptx-skill"),
            pptd_runner_image="debian:bookworm-slim",
            pptd_runner_timeout_sec=30.0,
        ),
        store=_Store(run),
        subprocess=SimpleNamespace(run=fake_run),
    )
    engine = CompileEngine(runtime)
    slides_dir = tmp_path / "artifacts" / "r-pptd" / "slides"

    result = asyncio.run(
        engine.compile_scratch_run(
            run_id="r-pptd",
            slides_dir=slides_dir,
            slide_count=2,
            theme={"primary": "#2563eb"},
        )
    )

    assert result.ok is True
    assert result.provider == "pptd"
    assert result.requested_provider == "pptd"
    assert result.pptx_path == slides_dir / "output" / "presentation.pptx"
    assert (slides_dir / "pptd" / "presentation.pptd").is_file()
    assert (slides_dir / "pptd" / "design.md").is_file()
    assert (slides_dir / "pptd" / "outline.md").is_file()
    assert (slides_dir / "pptd" / "pages" / "slide-01.page").is_file()
    assert "PPTD-first deck" in (slides_dir / "pptd" / "design.md").read_text(
        encoding="utf-8"
    )
    assert "## Page 2" in (slides_dir / "pptd" / "outline.md").read_text(
        encoding="utf-8"
    )
    cover_text = (slides_dir / "pptd" / "pages" / "slide-01.page").read_text(
        encoding="utf-8"
    )
    content_text = (slides_dir / "pptd" / "pages" / "slide-02.page").read_text(
        encoding="utf-8"
    )
    assert "Data Link Layer" in cover_text
    assert "elementType: shape" in content_text
    assert "shapeName: roundRect" in content_text
    assert "point-1-card" in content_text
    assert "ACK" in content_text
    assert len(calls) == 2
    assert "check.sh" in " ".join(calls[0])
    assert "convert.sh" in " ".join(calls[1])


def test_compile_provider_pptd_normalizes_theme_colors_for_runtime_check(
    tmp_path: Path,
) -> None:
    run = RunRecord(
        run_id="r-pptd-color",
        trace_id="t-pptd-color",
        status=RunStatus.COMPILING,
        input=CreateRunRequest(
            topic="Color Check",
            project_id="p-pptd-color",
            target_slide_count=1,
            generation_mode=GenerationMode.SCRATCH,
        ),
        artifact_dir=str(tmp_path / "artifacts" / "r-pptd-color"),
        outline=OutlineDocument(
            version=1,
            summary="color normalization",
            nodes=[OutlineNode(title="Color Check", bullets=["No bare hex"])],
        ),
        slides=[SlideArtifact(slide_no=1, js_code="", status="ready")],
    )
    runtime = SimpleNamespace(
        settings=make_settings(compile_provider="pptd"),
        store=_Store(run),
        subprocess=SimpleNamespace(run=lambda *args, **kwargs: None),
    )
    engine = CompileEngine(runtime)
    pptd_path = tmp_path / "artifacts" / "r-pptd-color" / "slides" / "pptd" / "presentation.pptd"

    engine._write_pptd_project(
        pptd_path=pptd_path,
        run=run,
        slide_count=1,
        theme={"primary": "1A1A1A", "background": "ffffff", "text": "111827"},
    )

    deck_text = pptd_path.read_text(encoding="utf-8")
    assert 'primary: "#1A1A1A"' in deck_text
    assert 'background: "#ffffff"' in deck_text
    assert 'text: "#111827"' in deck_text


def test_compile_provider_pptd_builds_pagevra_bundle_without_legacy_scene_entrypoint(
    tmp_path: Path,
) -> None:
    def fake_run(args, **_kwargs):
        if "convert.sh" in " ".join(args):
            output = tmp_path / "artifacts" / "r-pptd" / "slides" / "output" / "presentation.pptx"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"pptx")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    run = RunRecord(
        run_id="r-pptd",
        trace_id="t-pptd",
        status=RunStatus.COMPILING,
        input=CreateRunRequest(
            topic="Data Link Layer",
            project_id="p-pptd",
            target_slide_count=1,
            generation_mode=GenerationMode.SCRATCH,
        ),
        artifact_dir=str(tmp_path / "artifacts" / "r-pptd"),
        outline=OutlineDocument(
            version=1,
            summary="network courseware",
            nodes=[OutlineNode(title="Data Link Layer", bullets=["Framing"])],
        ),
        slides=[SlideArtifact(slide_no=1, js_code="", status="ready")],
    )
    runtime = SimpleNamespace(
        settings=make_settings(
            compile_provider="pptd",
            pptd_skill_dir=str(tmp_path / "pptx-skill"),
            pptd_runner_timeout_sec=30.0,
        ),
        store=_Store(run),
        subprocess=SimpleNamespace(run=fake_run),
    )
    engine = CompileEngine(runtime)
    slides_dir = tmp_path / "artifacts" / "r-pptd" / "slides"

    asyncio.run(
        engine.compile_scratch_run(
            run_id="r-pptd",
            slides_dir=slides_dir,
            slide_count=1,
            theme={"primary": "#2563eb"},
        )
    )
    bundle = asyncio.run(engine.build_compile_bundle("r-pptd"))

    assert bundle["provider"] == "diego"
    assert bundle["mode"] == "scratch"
    assert bundle["entrypoint"] == "slides/compile_pptd_bundle.js"
    assert bundle["compile_options"]["command"] == ["node", "compile_pptd_bundle.js"]
    assert bundle["compile_options"]["preview_manifest_path"] == "slides/output/preview.json"
    assert bundle["compile_options"]["result_manifest_path"] == "slides/output/result.json"
    assert bundle["compile_options"]["output_artifacts"] == [
        {
            "kind": "pptx",
            "path": "slides/output/presentation.pptx",
            "media_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
    ]
    paths = {item["path"] for item in bundle["files"] + bundle["assets"]}
    assert "slides/compile.js" not in paths
    assert "slides/compile_pptd_bundle.js" in paths
    assert "slides/pptd/presentation.pptd" in paths
    assert "slides/pptd/design.md" in paths
    assert "slides/pptd/outline.md" in paths
    assert "slides/pptd/pages/slide-01.page" in paths
    assert "slides/input/presentation.pptx" in paths
    preview_seed = next(
        item
        for item in bundle["files"]
        if item["path"] == "slides/preview_seed.json"
    )
    preview = json.loads(base64.b64decode(preview_seed["content_base64"]))
    assert preview["source"] == "pptd_project"
    svg_data_url = preview["pages"][0]["svg_data_url"]
    svg = base64.b64decode(svg_data_url.split(",", 1)[1]).decode("utf-8")
    assert "Data Link Layer" in svg
    assert "Framing" in svg
    assert "01 / 01" in svg


def test_pptd_writer_prefers_external_skill_template_when_available(tmp_path: Path) -> None:
    template_dir = (
        tmp_path
        / "pptx-skill"
        / "guideline"
        / "design"
        / "template"
        / "education-1"
    )
    pages_dir = template_dir / "pages"
    pages_dir.mkdir(parents=True)
    (template_dir / "education-1.pptd").write_text(
        "\n".join(
            [
                "title: Legacy Vendor Template",
                "size: [1280, 720]",
                "theme:",
                "  colors:",
                '    primary: "#1C4D5F"',
                '    accent: "#E07A5F"',
                '    background: "#F5F5F0"',
                "  textStyles:",
                "    accent:",
                "      fontSize: 24",
                '      color: "$accent"',
                "pages:",
                "  - pages/cover.page",
                "",
            ]
        ),
        encoding="utf-8",
    )
    page_template = "\n".join(
        [
            "pageType: cover",
            "elements:",
            "  - elementId: main-title",
            "    elementType: text",
            "    content:",
            "      text: |",
            "        Old title",
            "  - elementId: footer-info",
            "    elementType: text",
            "    content:",
            "      text: |",
            "        Vendor footer",
            "",
        ]
    )
    for name in ("cover.page", "concept.page", "final.page"):
        (pages_dir / name).write_text(page_template, encoding="utf-8")

    run = RunRecord(
        run_id="r-template",
        trace_id="t-template",
        status=RunStatus.COMPILING,
        input=CreateRunRequest(
            topic="Template Based",
            project_id="p-template",
            target_slide_count=3,
            generation_mode=GenerationMode.SCRATCH,
        ),
        artifact_dir=str(tmp_path / "artifacts" / "r-template"),
        outline=OutlineDocument(
            version=1,
            summary="template preference",
            nodes=[OutlineNode(title="Template Based", bullets=["Use external template"])],
        ),
        slides=[SlideArtifact(slide_no=1, js_code="", status="ready")],
    )
    pptd_path = tmp_path / "artifacts" / "r-template" / "slides" / "pptd" / "presentation.pptd"

    PptdDeckWriter().write_project(
        pptd_path=pptd_path,
        title=run.input.topic,
        nodes=list(run.outline.nodes),
        slide_count=3,
        theme={"primary": "#123456"},
        skill_dir=tmp_path / "pptx-skill",
    )

    deck_text = pptd_path.read_text(encoding="utf-8")
    cover_text = (pptd_path.parent / "pages" / "slide-01.page").read_text(encoding="utf-8")
    assert 'title: "Template Based"' in deck_text
    assert 'primary: "#123456"' in deck_text
    assert "    accent:" in deck_text
    assert "      fontSize: 24" in deck_text
    assert "pages/slide-01.page" in deck_text
    assert (pptd_path.parent / "design.md").is_file()
    assert (pptd_path.parent / "outline.md").is_file()
    assert "Old title" not in cover_text
    assert "Vendor footer" not in cover_text
    assert "Template Based" in cover_text
    assert "NeoSpectra" in cover_text


def test_pptd_writer_selects_skill_template_family_from_run_style(tmp_path: Path) -> None:
    template_root = tmp_path / "pptx-skill" / "guideline" / "design" / "template"
    for template_name in ("education-1", "education-3"):
        template_dir = template_root / template_name
        pages_dir = template_dir / "pages"
        pages_dir.mkdir(parents=True)
        (template_dir / f"{template_name}.pptd").write_text(
            "\n".join(
                [
                    f"title: {template_name}",
                    "size: [1280, 720]",
                    f"template_marker: {template_name}",
                    "theme:",
                    "  colors:",
                    '    primary: "#1C4D5F"',
                    "pages:",
                    "  - pages/cover.page",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        for page_name in ("cover.page", "content1.page", "content2.page", "final.page"):
            (pages_dir / page_name).write_text(
                "\n".join(
                    [
                        "pageType: content",
                        "elements:",
                        "  - elementId: cover-title",
                        "    elementType: text",
                        "    content:",
                        "      text: |",
                        "        Old cover title",
                        "  - elementId: page-title",
                        "    elementType: text",
                        "    content:",
                        "      text: |",
                        "        Old page title",
                        "  - elementId: bullet1-text",
                        "    elementType: text",
                        "    wrap: false",
                        "    content:",
                        "      text: |",
                        "        Old bullet one",
                        "  - elementId: formula-text",
                        "    elementType: text",
                        "    bounds:",
                        "      - 180",
                        "      - 582",
                        "      - 900",
                        "      - 52",
                        "    content:",
                        "      text: |",
                        "        Old formula",
                        "  - elementId: decorative-logo",
                        "    elementType: text",
                        "    content:",
                        "      text: |",
                        "        Keep logo text",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

    pptd_path = tmp_path / "artifacts" / "r-template-style" / "slides" / "pptd" / "presentation.pptd"
    nodes = [
        OutlineNode(title="课程封面", bullets=["从真实模板开始"]),
        OutlineNode(title="第一章", bullets=["成帧边界", "差错控制"]),
        OutlineNode(title="第二章", bullets=["滑动窗口", "确认重传"]),
        OutlineNode(title="总结", bullets=["迁移应用"]),
    ]

    PptdDeckWriter().write_project(
        pptd_path=pptd_path,
        title="网络课程",
        nodes=nodes,
        slide_count=4,
        theme={"primary": "#123456"},
        skill_dir=tmp_path / "pptx-skill",
        template_style="education courseware",
    )

    deck_text = pptd_path.read_text(encoding="utf-8")
    content_text = (pptd_path.parent / "pages" / "slide-02.page").read_text(
        encoding="utf-8"
    )
    assert "template_marker: education-3" in deck_text
    assert "pages/slide-02.page" in deck_text
    assert "Old page title" not in content_text
    assert "Old bullet one" not in content_text
    assert "    wrap: false" not in content_text
    assert "      - 230" in content_text
    assert "Old formula" not in content_text
    assert "第一章" in content_text
    assert "成帧边界" in content_text
    assert "Keep logo text" in content_text


def test_pptd_writer_uses_outline_semantics_to_choose_template_pages(tmp_path: Path) -> None:
    template_dir = (
        tmp_path
        / "pptx-skill"
        / "guideline"
        / "design"
        / "template"
        / "education-3"
    )
    pages_dir = template_dir / "pages"
    pages_dir.mkdir(parents=True)
    (template_dir / "education-3.pptd").write_text(
        "\n".join(
            [
                "title: education-3",
                "size: [1280, 720]",
                "theme:",
                "  colors:",
                '    primary: "#1C4D5F"',
                "pages:",
                "  - pages/cover.page",
                "",
            ]
        ),
        encoding="utf-8",
    )
    page_template = "\n".join(
        [
            "pageType: content",
            "elements:",
            "  - elementId: page-title",
            "    elementType: text",
            "    content:",
            "      text: |",
            "        Old page title",
            "  - elementId: template-kind",
            "    elementType: text",
            "    content:",
            "      text: |",
            "        {kind}",
            "  - elementId: bullet1-text",
            "    elementType: text",
            "    content:",
            "      text: |",
            "        Old bullet",
            "",
        ]
    )
    for page_name in (
        "cover.page",
        "toc.page",
        "section.page",
        "content1.page",
        "content2.page",
        "content3.page",
        "content4.page",
        "content5.page",
        "final.page",
    ):
        (pages_dir / page_name).write_text(
            page_template.format(kind=page_name),
            encoding="utf-8",
        )
    nodes = [
        OutlineNode(title="封面", bullets=["课程入口"], page_type=SlidePageType.COVER),
        OutlineNode(title="目录", bullets=["成帧", "差错检测"], page_type=SlidePageType.TOC),
        OutlineNode(title="流量控制章节", bullets=["反馈", "速率"], page_type=SlidePageType.SECTION),
        OutlineNode(title="GBN vs SR 对比", bullets=["GBN 批量重传", "SR 选择重传"]),
        OutlineNode(
            title="流量控制机制",
            bullets=["发送方与接收方速率匹配", "避免缓存溢出"],
            layout_hint="content-two-column",
        ),
        OutlineNode(title="滑动窗口流程", bullets=["发送窗口推进", "ACK 确认", "超时重传"]),
        OutlineNode(title="效率指标", bullets=["利用率提升 80%", "延迟降低 30%"]),
        OutlineNode(title="机制协同框架", bullets=["成帧", "检错", "流控", "重传"]),
        OutlineNode(title="总结", bullets=["迁移应用"], page_type=SlidePageType.SUMMARY),
    ]
    pptd_path = tmp_path / "artifacts" / "r-semantic" / "slides" / "pptd" / "presentation.pptd"

    PptdDeckWriter().write_project(
        pptd_path=pptd_path,
        title="网络课程",
        nodes=nodes,
        slide_count=len(nodes),
        theme={"primary": "#123456"},
        skill_dir=tmp_path / "pptx-skill",
        template_style="education courseware",
    )

    assert "section.page" in (pptd_path.parent / "pages" / "slide-03.page").read_text(encoding="utf-8")
    assert "content2.page" in (pptd_path.parent / "pages" / "slide-04.page").read_text(encoding="utf-8")
    assert "content2.page" in (pptd_path.parent / "pages" / "slide-05.page").read_text(encoding="utf-8")
    assert "content3.page" in (pptd_path.parent / "pages" / "slide-06.page").read_text(encoding="utf-8")
    assert "content4.page" in (pptd_path.parent / "pages" / "slide-07.page").read_text(encoding="utf-8")
    assert "content5.page" in (pptd_path.parent / "pages" / "slide-08.page").read_text(encoding="utf-8")


def test_pptd_project_preview_renders_custom_paths_and_inline_text_styles(tmp_path: Path) -> None:
    pptd_path = tmp_path / "presentation.pptd"
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    pptd_path.write_text(
        "\n".join(
            [
                'title: "Preview"',
                "size: [1280, 720]",
                "theme:",
                "  colors:",
                '    primary: "#123456"',
                "pages:",
                "  - pages/slide-01.page",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (pages_dir / "slide-01.page").write_text(
        "\n".join(
            [
                "pageType: cover",
                "background:",
                "  type: solid",
                '  color: "#ffffff"',
                "elements:",
                "  - elementId: triangle",
                "    elementType: shape",
                "    bounds: [680, 0, 280, 720]",
                "    shapeName: custom",
                "    path: 280,720;M280 0 L0 720 L280 720 Z",
                "    fill:",
                "      type: solid",
                '      color: "#1976D2"',
                "  - elementId: symbol",
                "    elementType: text",
                "    bounds: [980, 180, 120, 80]",
                "    content:",
                "      align: [center, middle]",
                "      text: |",
                '        <p><span style="font-size:72px; color:#FFFFFF18; font-family:MiSans;">π</span></p>',
                "",
            ]
        ),
        encoding="utf-8",
    )

    manifest = PptdProjectPreviewRenderer().preview_manifest(pptd_path=pptd_path)
    svg_data_url = manifest["pages"][0]["svg_data_url"]
    svg = base64.b64decode(svg_data_url.split(",", 1)[1]).decode("utf-8")

    assert '<path d="M280 0 L0 720 L280 720 Z"' in svg
    assert 'transform="translate(680 0)"' in svg
    assert 'font-size="72"' in svg
    assert 'fill="#FFFFFF18"' in svg


def test_pptd_scene_reads_and_patches_text_nodes_without_legacy_js(tmp_path: Path) -> None:
    pptd_path = tmp_path / "presentation.pptd"
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    pptd_path.write_text(
        "\n".join(
            [
                'title: "Editable"',
                "size: [1280, 720]",
                "pages:",
                "  - pages/slide-01.page",
                "",
            ]
        ),
        encoding="utf-8",
    )
    page_path = pages_dir / "slide-01.page"
    page_path.write_text(
        "\n".join(
            [
                "pageType: cover",
                "elements:",
                "  - elementId: cover-title",
                "    elementType: text",
                "    bounds: [60, 160, 600, 160]",
                "    content:",
                "      lineHeight: 1.2",
                "      text: |",
                '        <p><span style="font-size:56px;"><strong>旧标题</strong></span></p>',
                "  - elementId: accent-line",
                "    elementType: shape",
                "    bounds: [60, 330, 120, 0]",
                "    shapeName: straightConnector1",
                "  - elementId: symbol-pi",
                "    elementType: text",
                "    bounds: [980, 180, 120, 80]",
                "    content:",
                "      text: |",
                '        <p><span style="font-size:72px; color:#FFFFFF18;">π</span></p>',
                "",
            ]
        ),
        encoding="utf-8",
    )

    scene = build_pptd_slide_scene(
        pptd_path=pptd_path,
        page_path=page_path,
        run_id="r-pptd-edit",
        slide_no=1,
    )

    assert scene.readonly is False
    assert len(scene.nodes) == 1
    assert scene.nodes[0].node_id == "text:pptd:cover-title"
    assert scene.nodes[0].label == "Title"
    assert scene.nodes[0].text == "旧标题"

    next_scene = apply_pptd_scene_operations(
        pptd_path=pptd_path,
        page_path=page_path,
        scene_version=scene.scene_version,
        operations=[
            {
                "op": "replace_text",
                "node_id": "text:pptd:cover-title",
                "value": "新标题",
            }
        ],
        run_id="r-pptd-edit",
        slide_no=1,
    )

    updated_page = page_path.read_text(encoding="utf-8")
    assert "旧标题" not in updated_page
    assert "新标题" in updated_page
    assert "font-size:56px" in updated_page
    assert next_scene.nodes[0].text == "新标题"
    assert next_scene.scene_version != scene.scene_version
