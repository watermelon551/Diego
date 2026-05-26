from __future__ import annotations

import asyncio
import base64
import json
import re
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
from service.run.engines.pptd_contracts import PptdSlideContent
from service.run.engines.pptd_layout import PptdDeckWriter
from service.run.engines.pptd_preview import PptdProjectPreviewRenderer
from service.run.engines.pptd_semantic_pages import PptdSemanticPageRenderer
from service.run.engines.pptd_source_notes import pptd_source_notes_from_report
from service.run.engines.pptd_skill_template import PptdSkillTemplateDeck
from service.run.flows.scratch_flow import ScratchFlowService
from service.run.slide_scene.pptd_scene import (
    apply_pptd_scene_operations,
    build_pptd_slide_scene,
)

from tests.support.runtime_helpers import make_settings


def test_pptd_template_selection_does_not_treat_single_gbn_or_sr_page_as_comparison() -> None:
    deck = PptdSkillTemplateDeck()

    gbn_pages = deck._preferred_content_pages(
        slide=PptdSlideContent(
            index=5,
            total=8,
            title="Go-Back-N (GBN) 协议详解",
            bullets=[
                "发送窗口大小>1，接收窗口大小=1",
                "累积确认：ACKn表示n及之前所有帧正确接收",
                "优点：实现简单；缺点：带宽浪费",
            ],
            page_type="content",
            layout_hint="content-timeline",
        )
    )
    sr_pages = deck._preferred_content_pages(
        slide=PptdSlideContent(
            index=6,
            total=8,
            title="选择重传 (SR) 协议详解",
            bullets=[
                "发送窗口与接收窗口大小均>1",
                "逐个确认：每个帧需要独立ACK",
                "优点：带宽利用率高；缺点：缓存管理复杂",
            ],
            page_type="content",
            layout_hint="content-timeline",
        )
    )
    comparison_pages = deck._preferred_content_pages(
        slide=PptdSlideContent(
            index=7,
            total=8,
            title="GBN vs SR 协议对比",
            bullets=["GBN：", "批量重传", "SR：", "选择重传"],
            page_type="content",
            layout_hint="content-comparison",
        )
    )

    assert gbn_pages[0] == "content3.page"
    assert sr_pages[0] == "content3.page"
    assert comparison_pages[0] == "content2.page"


def test_pptd_skill_template_replaces_academic_toc_item_placeholders() -> None:
    deck = PptdSkillTemplateDeck()
    template = "\n".join(
        [
            "pageType: toc",
            "elements:",
            "  - elementId: toc-item-1-num",
            "    elementType: text",
            "    content:",
            "      text: |",
            "        <p>Learning Roadmap</p>",
            "  - elementId: toc-item-1-title",
            "    elementType: text",
            "    content:",
            "      text: |",
            "        <p><strong>Old Title</strong></p>",
            "",
        ]
    )
    rendered = deck._render_toc(
        template,
        PptdSlideContent(
            index=1,
            total=10,
            title="课程内容目录",
            bullets=["数据链路层功能与成帧"],
            page_type="toc",
            layout_hint="toc-list",
        ),
    )

    assert '<p><span style="font-size:34px;"><strong>01</strong></span></p>' in rendered
    assert "数据链路层功能与成帧" in rendered
    assert "Learning Roadmap</p>" not in rendered


def test_pptd_template_selection_maps_icon_concept_hint_to_concept_page() -> None:
    deck = PptdSkillTemplateDeck()

    pages = deck._preferred_content_pages(
        slide=PptdSlideContent(
            index=2,
            total=8,
            title="可靠传输的三个基本构件",
            bullets=["成帧：界定边界", "差错检测：发现错误", "确认重传：恢复丢失帧", "后续比较GBN与SR"],
            page_type="content",
            layout_hint="content-icon-rows",
        )
    )

    assert pages[:2] == ["content1.page", "content5.page"]


def test_pptd_template_selection_keeps_core_concept_title_a_concept_page() -> None:
    deck = PptdSkillTemplateDeck()

    pages = deck._preferred_content_pages(
        slide=PptdSlideContent(
            index=1,
            total=8,
            title="可靠传输的三个基本构件",
            bullets=[
                "成帧：界定边界",
                "差错检测：发现错误",
                "确认重传：用ACK和超时恢复丢失帧",
            ],
            page_type="content",
            layout_hint="content-stat-callout",
        )
    )

    assert pages[0] == "content1.page"


def test_pptd_template_selection_allows_second_slide_to_be_content_page(tmp_path: Path) -> None:
    skill_root = tmp_path / "pptx-skill"
    pages_dir = skill_root / "guideline" / "design" / "template" / "education-3" / "pages"
    pages_dir.mkdir(parents=True)
    (pages_dir.parent / "education-3.pptd").write_text(
        "\n".join(['title: "Template"', "size: [1280, 720]", "pages:", "  - pages/cover.page", ""]),
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
            "        Old placeholder",
            "",
        ]
    )
    for page_name in ("cover.page", "toc.page", "content1.page", "final.page"):
        (pages_dir / page_name).write_text(page_template, encoding="utf-8")

    pptd_path = tmp_path / "artifacts" / "r-second-content" / "slides" / "pptd" / "presentation.pptd"
    PptdDeckWriter().write_project(
        pptd_path=pptd_path,
        title="网络课程",
        nodes=[
            OutlineNode(title="封面", bullets=["课程入口"], page_type=SlidePageType.COVER),
            OutlineNode(
                title="可靠传输的三个基本构件",
                bullets=["成帧：界定边界", "差错检测：发现错误", "确认重传：恢复丢失帧"],
                page_type=SlidePageType.CONTENT,
                layout_hint="content-icon-rows",
            ),
            OutlineNode(title="总结", bullets=["迁移应用"], page_type=SlidePageType.SUMMARY),
        ],
        slide_count=3,
        theme={"primary": "#123456"},
        skill_dir=skill_root,
        template_style="education courseware",
    )

    second_page = (pptd_path.parent / "pages" / "slide-02.page").read_text(encoding="utf-8")
    assert "sourceTemplate: content1.page" in second_page
    assert "concept-definition-card" in second_page
    assert "Old placeholder" not in second_page


class _Store:
    def __init__(self, run: RunRecord) -> None:
        self.run = run

    async def get_run(self, run_id: str) -> RunRecord | None:
        return self.run if run_id == self.run.run_id else None

    async def update_run(self, run_id: str, apply) -> None:
        assert run_id == self.run.run_id
        apply(self.run)


class _ScratchOrchestrator:
    def __init__(self, run: RunRecord) -> None:
        self.store = _Store(run)
        self.events: list[tuple[str, EventType, dict[str, object]]] = []

    async def _publish(self, run_id: str, event_type: EventType, payload: dict[str, object]) -> None:
        self.events.append((run_id, event_type, payload))


def test_pptd_outline_materialization_projects_source_notes_to_citations(tmp_path: Path) -> None:
    run = RunRecord(
        run_id="r-source-citations",
        trace_id="t-source-citations",
        status=RunStatus.SLIDES_GENERATING,
        input=CreateRunRequest(
            topic="数据链路层",
            project_id="p-source-citations",
            target_slide_count=2,
            generation_mode=GenerationMode.SCRATCH,
        ),
        artifact_dir=str(tmp_path / "artifacts" / "r-source-citations"),
        outline=OutlineDocument(
            version=1,
            summary="source citations",
            nodes=[
                OutlineNode(title="封面", bullets=["课程入口"], page_type=SlidePageType.COVER),
                OutlineNode(title="差错检测", bullets=["CRC", "校验和"]),
            ],
        ),
        research_report={
            "page_focus": [
                "ch2_物理层_v2.pdf P121: 比特传输服务",
                "ch3_数据链路层_v2.pdf P6: 差错检测编码",
            ]
        },
    )
    orch = _ScratchOrchestrator(run)

    asyncio.run(
        ScratchFlowService(orch)._materialize_pptd_outline_slides(
            run_id=run.run_id,
            run=run,
        )
    )

    assert [slide.citations for slide in run.slides] == [
        ["ch2_物理层_v2.pdf P121"],
        ["ch3_数据链路层_v2.pdf P6"],
    ]
    assert [event[2]["preview_format"] for event in orch.events] == ["pptd", "pptd"]


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
        research_report={
            "scenario_profile": "education",
            "visual_mode": "template",
            "content_mode": "summary",
            "density_guidance": "courseware medium-high density",
            "font_guidance": "projector-readable body text",
            "risk_prohibitions": ["checker warnings are visual defects"],
            "design_intent": {
                "visual_strategy": "concept diagrams and metric tables",
                "layout_family": "education-5 template rhythm",
                "style_recipe": "university courseware",
            },
        },
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
    provenance_path = slides_dir / "pptd" / "compile_provenance.json"
    assert provenance_path.is_file()
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert provenance["schema_version"] == "diego.pptd_compile_provenance.v1"
    assert provenance["preview_source"] == "checked_pptd_project"
    assert provenance["export_source"] == "converted_pptx"
    assert provenance["check"] == {
        "error_count": 0,
        "warning_count": 0,
        "return_code": 0,
    }
    assert len(provenance["pptd_sha256"]) == 64
    assert len(provenance["pptx_sha256"]) == 64
    assert (slides_dir / "pptd" / "pages" / "slide-01.page").is_file()
    assert "PPTD-first deck" in (slides_dir / "pptd" / "design.md").read_text(
        encoding="utf-8"
    )
    design_doc = (slides_dir / "pptd" / "design.md").read_text(encoding="utf-8")
    assert "- Visual mode: `template`." in design_doc
    assert "- Content mode: `summary`." in design_doc
    assert "courseware medium-high density" in design_doc
    assert "projector-readable body text" in design_doc
    assert "checker warnings are visual defects" in design_doc
    assert "concept diagrams and metric tables" in design_doc
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


def test_compile_provider_pptd_records_optional_screenshot_provenance(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        command = " ".join(args)
        if "convert.sh" in command:
            output = (
                tmp_path
                / "artifacts"
                / "r-pptd-shot"
                / "slides"
                / "output"
                / "presentation.pptx"
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"pptx")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="Created", stderr="")
        if "screenshot.sh" in command:
            output_dir = (
                tmp_path
                / "artifacts"
                / "r-pptd-shot"
                / "slides"
                / "output"
                / "screenshots"
            )
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "slide-001.png").write_bytes(b"png-1")
            (output_dir / "slide-002.png").write_bytes(b"png-2")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="Rendered", stderr="")
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="Checking presentation.pptd\nSummary: 0 errors, 0 warnings",
            stderr="",
        )

    run = RunRecord(
        run_id="r-pptd-shot",
        trace_id="t-pptd-shot",
        status=RunStatus.COMPILING,
        input=CreateRunRequest(
            topic="Data Link Layer",
            project_id="p-pptd-shot",
            target_slide_count=2,
            generation_mode=GenerationMode.SCRATCH,
        ),
        artifact_dir=str(tmp_path / "artifacts" / "r-pptd-shot"),
        outline=OutlineDocument(
            version=1,
            summary="network courseware",
            nodes=[
                OutlineNode(title="Data Link Layer", bullets=["Framing"]),
                OutlineNode(title="Sliding Window", bullets=["ACK"]),
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
            pptd_runner_timeout_sec=30.0,
            pptd_screenshot_enabled=True,
            pptd_screenshot_dpi=180,
        ),
        store=_Store(run),
        subprocess=SimpleNamespace(run=fake_run),
    )
    engine = CompileEngine(runtime)
    slides_dir = tmp_path / "artifacts" / "r-pptd-shot" / "slides"

    result = asyncio.run(
        engine.compile_scratch_run(
            run_id="r-pptd-shot",
            slides_dir=slides_dir,
            slide_count=2,
            theme={"primary": "#2563eb"},
        )
    )
    bundle = asyncio.run(engine.build_compile_bundle("r-pptd-shot"))

    assert result.ok is True
    assert ["check.sh" in " ".join(call) for call in calls].count(True) == 1
    assert ["convert.sh" in " ".join(call) for call in calls].count(True) == 1
    screenshot_calls = [call for call in calls if "screenshot.sh" in " ".join(call)]
    assert len(screenshot_calls) == 1
    assert "--dpi 180" in " ".join(screenshot_calls[0])
    provenance = json.loads(
        (slides_dir / "pptd" / "compile_provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["screenshot"]["enabled"] is True
    assert provenance["screenshot"]["status"] == "completed"
    assert provenance["screenshot"]["source"] == "converted_pptx"
    assert [item["path"] for item in provenance["screenshot"]["files"]] == [
        "slides/output/screenshots/slide-001.png",
        "slides/output/screenshots/slide-002.png",
    ]
    assert all(len(item["sha256"]) == 64 for item in provenance["screenshot"]["files"])
    paths = {item["path"] for item in bundle["files"] + bundle["assets"]}
    assert "slides/output/screenshots/slide-001.png" in paths
    assert "slides/output/screenshots/slide-002.png" in paths
    preview_seed = next(
        item
        for item in bundle["files"]
        if item["path"] == "slides/preview_seed.json"
    )
    preview = json.loads(base64.b64decode(preview_seed["content_base64"]))
    assert preview["source"] == "converted_pptx_screenshot"
    assert preview["pages"][0]["format"] == "png"
    assert preview["pages"][0]["status"] == "rendered_from_pptx"
    assert preview["metadata"]["preview_truth"]["screenshot"]["status"] == "completed"


def test_compile_provider_pptd_fails_when_warning_repair_does_not_clear_check(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="Checking presentation.pptd\nTextOverflowWarning\nSummary: 0 errors, 1 warning",
            stderr="",
        )

    run = RunRecord(
        run_id="r-pptd-warn",
        trace_id="t-pptd-warn",
        status=RunStatus.COMPILING,
        input=CreateRunRequest(
            topic="Data Link Layer",
            project_id="p-pptd-warn",
            target_slide_count=1,
            generation_mode=GenerationMode.SCRATCH,
        ),
        artifact_dir=str(tmp_path / "artifacts" / "r-pptd-warn"),
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
            pptd_runner_image="debian:bookworm-slim",
            pptd_runner_timeout_sec=30.0,
        ),
        store=_Store(run),
        subprocess=SimpleNamespace(run=fake_run),
    )
    engine = CompileEngine(runtime)

    result = asyncio.run(
        engine.compile_scratch_run(
            run_id=run.run_id,
            slides_dir=tmp_path / "artifacts" / "r-pptd-warn" / "slides",
            slide_count=1,
            theme={"primary": "#2563eb"},
        )
    )

    assert result.ok is False
    assert result.reason == "pptd_check_warnings"
    assert result.error_details["stdout"] == (
        "Checking presentation.pptd\nTextOverflowWarning\nSummary: 0 errors, 1 warning"
    )
    assert result.error_details["error_count"] == 0
    assert result.error_details["warning_count"] == 1
    assert result.error_details["repair"]["attempted"] is True
    assert result.error_details["repair"]["changed"] is True
    assert result.error_details["repair"]["initial_warning_count"] == 1
    assert result.error_details["repair"]["final_warning_count"] == 1
    assert ["check.sh" in " ".join(call) for call in calls].count(True) == 2
    assert "check.sh" in " ".join(calls[0])
    assert all("convert.sh" not in " ".join(call) for call in calls)


def test_compile_provider_pptd_repairs_check_warnings_once_before_convert(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        command = " ".join(args)
        if "convert.sh" in command:
            output = tmp_path / "artifacts" / "r-pptd-repair" / "slides" / "output" / "presentation.pptx"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"pptx")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="Created", stderr="")
        if len([call for call in calls if "check.sh" in " ".join(call)]) == 1:
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout=(
                    "Checking presentation.pptd\n"
                    "TextOverflowWarning: text box overflow\n"
                    "Summary: 0 errors, 1 warning"
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="Checking presentation.pptd\nSummary: 0 errors, 0 warnings",
            stderr="",
        )

    run = RunRecord(
        run_id="r-pptd-repair",
        trace_id="t-pptd-repair",
        status=RunStatus.COMPILING,
        input=CreateRunRequest(
            topic="Data Link Layer",
            project_id="p-pptd-repair",
            target_slide_count=2,
            generation_mode=GenerationMode.SCRATCH,
        ),
        artifact_dir=str(tmp_path / "artifacts" / "r-pptd-repair"),
        outline=OutlineDocument(
            version=1,
            summary="network courseware",
            nodes=[
                OutlineNode(title="Data Link Layer", bullets=["Framing"]),
                OutlineNode(
                    title="Sliding Window",
                    bullets=[
                        "这是一个很长很长很长的课堂说明，用来触发自动修复时对正文文本框启用换行和扩展空间",
                    ],
                ),
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
    slides_dir = tmp_path / "artifacts" / "r-pptd-repair" / "slides"

    result = asyncio.run(
        engine.compile_scratch_run(
            run_id=run.run_id,
            slides_dir=slides_dir,
            slide_count=2,
            theme={"primary": "#2563eb"},
        )
    )

    assert result.ok is True
    assert result.error_details == {
            "repair": {
                "attempted": True,
                "changed": True,
                "restored": False,
                "initial_stdout": (
                    "Checking presentation.pptd\n"
                    "TextOverflowWarning: text box overflow\n"
                "Summary: 0 errors, 1 warning"
            ),
            "initial_stderr": "",
            "initial_error_count": 0,
            "initial_warning_count": 1,
            "final_error_count": 0,
            "final_warning_count": 0,
        }
    }
    assert ["check.sh" in " ".join(call) for call in calls].count(True) == 2
    assert "convert.sh" in " ".join(calls[-1])


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
    assert "slides/pptd/compile_provenance.json" in paths
    assert "slides/pptd/pages/slide-01.page" in paths
    assert "slides/input/presentation.pptx" in paths
    compile_script = next(
        item
        for item in bundle["files"]
        if item["path"] == "slides/compile_pptd_bundle.js"
    )
    script = base64.b64decode(compile_script["content_base64"]).decode("utf-8")
    assert "preview_truth" in script
    preview_seed = next(
        item
        for item in bundle["files"]
        if item["path"] == "slides/preview_seed.json"
    )
    preview = json.loads(base64.b64decode(preview_seed["content_base64"]))
    assert preview["source"] == "pptd_project"
    assert preview["metadata"]["preview_truth"]["preview_source"] == "checked_pptd_project"
    assert preview["metadata"]["preview_truth"]["export_source"] == "converted_pptx"
    assert preview["metadata"]["preview_truth"]["check"] == {
        "error_count": 0,
        "warning_count": 0,
        "return_code": 0,
    }
    assert len(preview["metadata"]["preview_truth"]["pptd_sha256"]) == 64
    assert len(preview["metadata"]["preview_truth"]["pptx_sha256"]) == 64
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
    assert "Prof. Presenter Name" not in cover_text
    assert "Department, University" not in cover_text
    assert "March 2026" not in cover_text


def test_pptd_source_notes_from_research_report_are_written_to_pages(tmp_path: Path) -> None:
    nodes = [
        OutlineNode(title="封面", bullets=["课程入口"], page_type=SlidePageType.COVER),
        OutlineNode(
            title="差错检测用于发现链路传输错误",
            bullets=["CRC把比特串映射为校验余数", "接收端用同一规则复算并判断帧是否损坏"],
            page_type=SlidePageType.CONTENT,
        ),
    ]
    notes = pptd_source_notes_from_report(
        {
            "page_focus": [
                "ch2_物理层_v2.pdf P121: 物理层提供比特传输服务",
                "ch3_数据链路层_v2.pdf P6: CRC 与校验和用于差错检测",
            ]
        },
        slide_count=2,
    )
    pptd_path = tmp_path / "artifacts" / "r-source-notes" / "slides" / "pptd" / "presentation.pptd"

    PptdDeckWriter().write_project(
        pptd_path=pptd_path,
        title="数据链路层",
        nodes=nodes,
        slide_count=2,
        theme={"primary": "#123456"},
        source_notes=notes,
    )

    content_page = (pptd_path.parent / "pages" / "slide-02.page").read_text(encoding="utf-8")
    preview = PptdProjectPreviewRenderer().preview_manifest(pptd_path=pptd_path)
    content_svg = base64.b64decode(preview["pages"][1]["svg_data_url"].split(",", 1)[1]).decode("utf-8")

    assert notes == ["ch2_物理层_v2.pdf P121", "ch3_数据链路层_v2.pdf P6"]
    assert "资料依据：ch3_数据链路层_v2.pdf P6" in content_page
    assert "资料依据：ch3_数据链路层_v2.pdf P6" in content_svg


def test_pptd_skill_content_pages_use_semantic_renderer_to_avoid_template_placeholders(tmp_path: Path) -> None:
    skill_root = tmp_path / "pptx-skill"
    pages_dir = skill_root / "guideline" / "design" / "template" / "education-1" / "pages"
    pages_dir.mkdir(parents=True)
    (pages_dir.parent / "education-1.pptd").write_text(
        "\n".join(['title: "Template"', "size: [1280, 720]", "pages:", "  - pages/cover.page", ""]),
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
            "        Old methodology title",
            "  - elementId: arch-placeholder",
            "    elementType: text",
            "    content:",
            "      text: |",
            "        [Figure 2: MolGNN模型架构图]",
            "",
        ]
    )
    for page_name in ("cover.page", "methodology.page", "final.page"):
        (pages_dir / page_name).write_text(page_template, encoding="utf-8")
    pptd_path = tmp_path / "artifacts" / "r-semantic-methodology" / "slides" / "pptd" / "presentation.pptd"

    PptdDeckWriter().write_project(
        pptd_path=pptd_path,
        title="数据链路层",
        nodes=[
            OutlineNode(title="封面", bullets=["课程入口"], page_type=SlidePageType.COVER),
            OutlineNode(title="成帧机制", bullets=["帧边界", "差错影响", "同步恢复"]),
            OutlineNode(title="总结", bullets=["迁移应用"], page_type=SlidePageType.SUMMARY),
        ],
        slide_count=3,
        theme={"primary": "#123456"},
        skill_dir=skill_root,
        source_notes=["", "ch3_数据链路层_v2.pdf P9", ""],
    )

    content_page = (pptd_path.parent / "pages" / "slide-02.page").read_text(encoding="utf-8")
    assert "Old methodology title" not in content_page
    assert "MolGNN" not in content_page
    assert "sourceTemplate: methodology.page" in content_page
    assert "资料依据：ch3_数据链路层_v2.pdf P9" in content_page


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
    assert "sourceTemplate: content1.page" in content_text
    assert "concept-definition-card" in content_text
    assert "Old formula" not in content_text
    assert "第一章" in content_text
    assert "成帧边界" in content_text
    assert "Keep logo text" not in content_text


def test_pptd_writer_routes_academic_curation_courses_to_university_education_template(tmp_path: Path) -> None:
    template_root = tmp_path / "pptx-skill" / "guideline" / "design" / "template"
    for template_name in ("academic-1", "education-3", "education-5"):
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
                    '    primary: "#2B6777"',
                    "pages:",
                    "  - pages/cover.page",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        for page_name in ("cover.page", "toc.page", "content1.page", "final.page"):
            if page_name == "cover.page":
                page_text = "\n".join(
                    [
                        "pageType: cover",
                        "elements:",
                        "  - elementId: institution-label",
                        "    elementType: text",
                        "    content:",
                        "      text: |",
                        "        <p>UNIVERSITY LECTURE · 学术讲座</p>",
                        "  - elementId: cover-title",
                        "    elementType: text",
                        "    content:",
                        "      text: |",
                        "        <p>学术讲座主标题</p>",
                        "  - elementId: cover-subtitle",
                        "    elementType: text",
                        "    content:",
                        "      text: |",
                        "        <p>副标题 / 研究方向 · Research Direction</p>",
                        "  - elementId: speaker-info",
                        "    elementType: text",
                        "    content:",
                        "      text: |",
                        "        <p>演讲者姓名 · Prof. Presenter Name</p>",
                        "        <p>所属院系 / 研究机构 · Department, University</p>",
                        "  - elementId: cover-date",
                        "    elementType: text",
                        "    content:",
                        "      text: |",
                        "        <p>2026年3月 · March 2026</p>",
                        "",
                    ]
                )
            else:
                page_text = "\n".join(
                    [
                        "pageType: content",
                        "elements:",
                        "  - elementId: page-title",
                        "    elementType: text",
                        "    content:",
                        "      text: |",
                        "        Old title",
                        "",
                    ]
                )
            (pages_dir / page_name).write_text(
                page_text,
                encoding="utf-8",
            )

    pptd_path = tmp_path / "artifacts" / "r-university-template" / "slides" / "pptd" / "presentation.pptd"

    PptdDeckWriter().write_project(
        pptd_path=pptd_path,
        title="本科数据链路层课程",
        nodes=[
            OutlineNode(title="封面", page_type=SlidePageType.COVER),
            OutlineNode(title="目录", bullets=["成帧", "CRC"], page_type=SlidePageType.TOC),
            OutlineNode(title="成帧方法", bullets=["边界识别"], page_type=SlidePageType.CONTENT),
            OutlineNode(title="总结", page_type=SlidePageType.SUMMARY),
        ],
        slide_count=4,
        theme={"primary": "#123456"},
        skill_dir=tmp_path / "pptx-skill",
        template_style="preset:academic-curation education",
    )

    assert "template_marker: education-5" in pptd_path.read_text(encoding="utf-8")
    design_doc = (pptd_path.parent / "design.md").read_text(encoding="utf-8")
    cover_text = (pptd_path.parent / "pages" / "slide-01.page").read_text(encoding="utf-8")
    assert "Profile Baseline Declaration" in design_doc
    assert "`profiles/education.md`" in design_doc
    assert "COURSEWARE" in cover_text
    assert "NeoSpectra 生成课件" in cover_text
    assert "color:#FFFFFF" in cover_text
    assert "Prof. Presenter Name" not in cover_text
    assert "Department, University" not in cover_text
    assert "March 2026" not in cover_text


def test_pptd_skill_template_replaces_university_toc_placeholders() -> None:
    deck = PptdSkillTemplateDeck()
    template = "\n".join(
        [
            "pageType: table_of_contents",
            "elements:",
            "  - elementId: header-label",
            "    elementType: text",
            "    content:",
            "      text: |",
            "        <p>目录 · TABLE OF CONTENTS</p>",
            "  - elementId: toc-num-1",
            "    elementType: text",
            "    content:",
            "      text: |",
            "        <p>01</p>",
            "  - elementId: toc-title-1",
            "    elementType: text",
            "    content:",
            "      text: |",
            "        <p>研究背景与问题提出</p>",
            "  - elementId: toc-time-1",
            "    elementType: text",
            "    content:",
            "      text: |",
            "        <p>~15 min</p>",
            "",
        ]
    )

    rendered = deck._render_toc(
        template,
        PptdSlideContent(
            index=1,
            total=10,
            title="课程内容导览",
            bullets=["数据链路层功能与成帧"],
            page_type="toc",
            layout_hint="toc-list",
        ),
    )

    assert "数据链路层功能与成帧" in rendered
    assert "Course Module" in rendered
    assert "研究背景与问题提出" not in rendered
    assert "~15 min" not in rendered


def test_pptd_skill_template_replaces_university_final_placeholders() -> None:
    deck = PptdSkillTemplateDeck()
    template = "\n".join(
        [
            "pageType: final",
            "elements:",
            "  - elementId: qa-tag-text",
            "    elementType: text",
            "    content:",
            "      text: |",
            "        <p>Questions &amp; Discussion</p>",
            "  - elementId: thankyou-text",
            "    elementType: text",
            "    content:",
            "      text: |",
            "        <p>Thank You · 谢谢</p>",
            "  - elementId: takeaway-label",
            "    elementType: text",
            "    content:",
            "      text: |",
            "        <p>CORE TAKEAWAYS · 核心收获</p>",
            "  - elementId: takeaway-1",
            "    elementType: text",
            "    content:",
            "      text: |",
            "        <p>Old takeaway</p>",
            "  - elementId: contact-info",
            "    elementType: text",
            "    content:",
            "      text: |",
            "        <p>presenter@university.edu.cn</p>",
            "",
        ]
    )

    rendered = deck._render_final(
        template,
        PptdSlideContent(
            index=9,
            total=10,
            title="课堂总结与关键要点",
            bullets=["成帧是数据链路层基础，CRC提供高效差错检测"],
            page_type="summary",
            layout_hint="summary-takeaways",
        ),
    )

    assert "Questions &amp; Discussion" in rendered
    assert "课堂总结与关键要点" in rendered
    assert "成帧是数据链路层基础" in rendered
    assert "color:#FFFFFF" in rendered
    assert "color:#FFFFFFcc" in rendered
    assert "Old takeaway" not in rendered
    assert "presenter@university.edu.cn" not in rendered


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
    assert "content3.page" in (pptd_path.parent / "pages" / "slide-05.page").read_text(encoding="utf-8")
    assert "content3.page" in (pptd_path.parent / "pages" / "slide-06.page").read_text(encoding="utf-8")
    assert "content4.page" in (pptd_path.parent / "pages" / "slide-07.page").read_text(encoding="utf-8")
    assert "content5.page" in (pptd_path.parent / "pages" / "slide-08.page").read_text(encoding="utf-8")


def test_pptd_writer_prefers_content_semantics_over_broad_layout_hints(tmp_path: Path) -> None:
    skill_root = tmp_path / "pptx-skill"
    pages_dir = skill_root / "guideline" / "design" / "template" / "education-3" / "pages"
    pages_dir.mkdir(parents=True)
    (pages_dir.parent / "education-3.pptd").write_text(
        "\n".join(['title: "Template"', "pages:", "  - pages/cover.page", ""]),
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
            "  - elementId: left-title-label",
            "    elementType: text",
            "    content:",
            "      text: |",
            "        Old left",
            "  - elementId: right-title-label",
            "    elementType: text",
            "    content:",
            "      text: |",
            "        Old right",
            "",
        ]
    )
    for page_name in (
        "cover.page",
        "toc.page",
        "content1.page",
        "content2.page",
        "content3.page",
        "content4.page",
        "final.page",
    ):
        (pages_dir / page_name).write_text(page_template.format(kind=page_name), encoding="utf-8")

    nodes = [
        OutlineNode(title="封面", bullets=["课程入口"], page_type=SlidePageType.COVER),
        OutlineNode(title="目录", bullets=["流程", "指标"], page_type=SlidePageType.TOC),
        OutlineNode(
            title="流程解析：成帧与差错检测技术",
            bullets=["成帧方法：", "字节计数法", "字节填充法", "差错检测技术：", "CRC", "校验和"],
            layout_hint="content-comparison",
        ),
        OutlineNode(
            title="关键指标与协议性能对比",
            bullets=["评估指标：", "信道利用率", "吞吐量", "性能对比表：", "| 特性 | GBN | SR |"],
            layout_hint="content-comparison",
        ),
        OutlineNode(
            title="对比分析：GBN vs SR",
            bullets=[
                "GBN：",
                "接收窗口为 1",
                "重传所有未确认帧",
                "SR：",
                "缓存乱序帧",
                "仅重传出错帧",
            ],
            layout_hint="content-comparison",
        ),
        OutlineNode(title="总结", bullets=["迁移应用"], page_type=SlidePageType.SUMMARY),
    ]
    pptd_path = tmp_path / "artifacts" / "r-quality" / "slides" / "pptd" / "presentation.pptd"

    PptdDeckWriter().write_project(
        pptd_path=pptd_path,
        title="网络课程",
        nodes=nodes,
        slide_count=len(nodes),
        theme={"primary": "#123456"},
        skill_dir=skill_root,
        template_style="education courseware",
    )

    assert "content3.page" in (pptd_path.parent / "pages" / "slide-03.page").read_text(encoding="utf-8")
    assert "content4.page" in (pptd_path.parent / "pages" / "slide-04.page").read_text(encoding="utf-8")
    comparison_page = (pptd_path.parent / "pages" / "slide-05.page").read_text(encoding="utf-8")
    assert "content2.page" in comparison_page
    assert "comparison-left-title" in comparison_page
    assert "comparison-right-title" in comparison_page
    assert "GBN" in comparison_page
    assert "SR" in comparison_page


def test_pptd_semantic_comparison_splits_inline_gbn_sr_bullets(tmp_path: Path) -> None:
    skill_root = tmp_path / "pptx-skill"
    pages_dir = skill_root / "guideline" / "design" / "template" / "education-3" / "pages"
    pages_dir.mkdir(parents=True)
    (pages_dir.parent / "education-3.pptd").write_text(
        "\n".join(['title: "Template"', "size: [1280, 720]", "pages:", "  - pages/cover.page", ""]),
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
            "        Old placeholder",
            "",
        ]
    )
    for page_name in ("cover.page", "toc.page", "content2.page", "final.page"):
        (pages_dir / page_name).write_text(page_template, encoding="utf-8")
    nodes = [
        OutlineNode(title="封面", bullets=["课程入口"], page_type=SlidePageType.COVER),
        OutlineNode(title="目录", bullets=["对比"], page_type=SlidePageType.TOC),
        OutlineNode(
            title="GBN与SR协议：机制与对比",
            bullets=[
                "GBN(回退N帧)：发送窗口与累积确认机制",
                "SR(选择重传)：接收窗口与独立确认机制",
                "性能对比：吞吐量、信道利用率、缓冲区需求",
            ],
            layout_hint="content-comparison",
        ),
        OutlineNode(title="总结", bullets=["迁移应用"], page_type=SlidePageType.SUMMARY),
    ]
    pptd_path = tmp_path / "artifacts" / "r-inline-compare" / "slides" / "pptd" / "presentation.pptd"

    PptdDeckWriter().write_project(
        pptd_path=pptd_path,
        title="网络课程",
        nodes=nodes,
        slide_count=len(nodes),
        theme={"primary": "#123456"},
        skill_dir=skill_root,
        template_style="education courseware",
    )

    comparison_page = (pptd_path.parent / "pages" / "slide-03.page").read_text(encoding="utf-8")
    assert "comparison-left-title" in comparison_page
    assert "comparison-right-title" in comparison_page
    assert "<strong>GBN</strong>" in comparison_page
    assert "<strong>SR</strong>" in comparison_page
    assert "接收窗口与独立确认机制" in comparison_page
    assert comparison_page.count("高误码率与高带宽延迟积网络") == 0


def test_pptd_semantic_comparison_keeps_cross_protocol_notes_in_summary(
    tmp_path: Path,
) -> None:
    skill_root = tmp_path / "pptx-skill"
    pages_dir = skill_root / "guideline" / "design" / "template" / "education-3" / "pages"
    pages_dir.mkdir(parents=True)
    (pages_dir.parent / "education-3.pptd").write_text(
        "\n".join(['title: "Template"', "size: [1280, 720]", "pages:", "  - pages/cover.page", ""]),
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
            "        Old placeholder",
            "",
        ]
    )
    for page_name in ("cover.page", "toc.page", "content2.page", "final.page"):
        (pages_dir / page_name).write_text(page_template, encoding="utf-8")
    nodes = [
        OutlineNode(title="封面", bullets=["课程入口"], page_type=SlidePageType.COVER),
        OutlineNode(title="目录", bullets=["对比"], page_type=SlidePageType.TOC),
        OutlineNode(
            title="GBN与SR协议对比：错误恢复策略的根本差异",
            bullets=[
                "GBN：",
                "发送窗口>1，接收窗口=1；出错时重传所有后续帧",
                "SR：",
                "发送窗口>1，接收窗口>1；仅重传出错的帧",
                "确认方式：GBN用累计确认；SR用单独确认",
                "实现复杂度：GBN接收方简单，发送方缓冲少；SR接收方复杂，需缓存乱序帧",
            ],
            layout_hint="content-comparison",
        ),
        OutlineNode(title="总结", bullets=["迁移应用"], page_type=SlidePageType.SUMMARY),
    ]
    pptd_path = tmp_path / "artifacts" / "r-grouped-compare" / "slides" / "pptd" / "presentation.pptd"

    PptdDeckWriter().write_project(
        pptd_path=pptd_path,
        title="网络课程",
        nodes=nodes,
        slide_count=len(nodes),
        theme={"primary": "#123456"},
        skill_dir=skill_root,
        template_style="education courseware",
    )

    comparison_page = (pptd_path.parent / "pages" / "slide-03.page").read_text(encoding="utf-8")
    right_bullets = "\n".join(
        re.findall(
            r"elementId: comparison-right-bullet-[123].*?(?=\n  - elementId:|\Z)",
            comparison_page,
            flags=re.S,
        )
    )
    summary_block = re.search(
        r"elementId: comparison-summary-text.*?(?=\n  - elementId:|\Z)",
        comparison_page,
        flags=re.S,
    )
    assert summary_block is not None
    assert "确认方式" in summary_block.group(0)
    assert "实现复杂度" in summary_block.group(0)
    assert "课堂判断：课堂判断" not in summary_block.group(0)
    assert "、；" not in summary_block.group(0)
    assert "确认方式" not in right_bullets
    assert "实现复杂度" not in right_bullets


def test_pptd_writer_uses_direct_semantic_pages_for_core_content(tmp_path: Path) -> None:
    skill_root = tmp_path / "pptx-skill"
    pages_dir = skill_root / "guideline" / "design" / "template" / "education-3" / "pages"
    pages_dir.mkdir(parents=True)
    (pages_dir.parent / "education-3.pptd").write_text(
        "\n".join(['title: "Template"', "size: [1280, 720]", "pages:", "  - pages/cover.page", ""]),
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
            "        Old placeholder",
            "",
        ]
    )
    for page_name in (
        "cover.page",
        "toc.page",
        "content1.page",
        "content2.page",
        "content3.page",
        "content4.page",
        "final.page",
    ):
        (pages_dir / page_name).write_text(page_template, encoding="utf-8")

    nodes = [
        OutlineNode(title="封面", bullets=["课程入口"], page_type=SlidePageType.COVER),
        OutlineNode(title="目录", bullets=["流程", "指标"], page_type=SlidePageType.TOC),
        OutlineNode(
            title="滑动窗口流程",
            bullets=["发送窗口推进", "ACK 确认", "超时重传", "U = (F/R) / (F/R + 2τ)"],
        ),
        OutlineNode(
            title="GBN vs SR 对比",
            bullets=["GBN：", "重传所有未确认帧", "接收窗口为 1", "SR：", "只重传出错帧", "缓存乱序帧"],
        ),
        OutlineNode(
            title="关键指标与协议性能对比",
            bullets=["信道利用率提升 80%", "吞吐量受窗口大小影响", "| 特性 | GBN | SR |", "| 重传 | 批量 | 选择 |"],
        ),
        OutlineNode(title="总结", bullets=["迁移应用"], page_type=SlidePageType.SUMMARY),
    ]
    pptd_path = tmp_path / "artifacts" / "r-semantic-direct" / "slides" / "pptd" / "presentation.pptd"

    PptdDeckWriter().write_project(
        pptd_path=pptd_path,
        title="网络课程",
        nodes=nodes,
        slide_count=len(nodes),
        theme={"primary": "#123456"},
        skill_dir=skill_root,
        template_style="education courseware",
    )

    process_page = (pptd_path.parent / "pages" / "slide-03.page").read_text(encoding="utf-8")
    comparison_page = (pptd_path.parent / "pages" / "slide-04.page").read_text(encoding="utf-8")
    metric_page = (pptd_path.parent / "pages" / "slide-05.page").read_text(encoding="utf-8")
    preview = PptdProjectPreviewRenderer().preview_manifest(pptd_path=pptd_path)
    metric_svg = base64.b64decode(preview["pages"][4]["svg_data_url"].split(",", 1)[1]).decode("utf-8")

    assert "Old placeholder" not in process_page
    assert "process-card-1" in process_page
    assert "用该公式估算效率" in process_page
    assert "sourceTemplate: content3.page" in process_page
    assert "comparison-left-card" in comparison_page
    assert "sourceTemplate: content2.page" in comparison_page
    assert "metric-card-1" in metric_page
    assert "metric-table-1-1" in metric_page
    assert "sourceTemplate: content4.page" in metric_page
    assert "&amp;gt;" not in "\n".join([process_page, comparison_page, metric_page])
    assert "批量" in metric_svg
    assert "选择" in metric_svg


def test_pptd_writer_renders_default_content_as_concept_diagram(tmp_path: Path) -> None:
    skill_root = tmp_path / "pptx-skill"
    pages_dir = skill_root / "guideline" / "design" / "template" / "education-3" / "pages"
    pages_dir.mkdir(parents=True)
    (pages_dir.parent / "education-3.pptd").write_text(
        "\n".join(['title: "Template"', "size: [1280, 720]", "pages:", "  - pages/cover.page", ""]),
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
            "        Old placeholder",
            "",
        ]
    )
    for page_name in ("cover.page", "toc.page", "content1.page", "final.page"):
        (pages_dir / page_name).write_text(page_template, encoding="utf-8")

    nodes = [
        OutlineNode(title="封面", bullets=["课程入口"], page_type=SlidePageType.COVER),
        OutlineNode(title="目录", bullets=["概念"], page_type=SlidePageType.TOC),
        OutlineNode(
            title="差错控制让链路层交付更可靠",
            bullets=[
                "差错控制：发现或纠正传输中的比特错误",
                "检错码用于判断帧是否损坏",
                "纠错码可在部分场景直接恢复数据",
                "ARQ把检测结果转成重传动作",
            ],
        ),
        OutlineNode(title="总结", bullets=["迁移应用"], page_type=SlidePageType.SUMMARY),
    ]
    pptd_path = tmp_path / "artifacts" / "r-concept-direct" / "slides" / "pptd" / "presentation.pptd"

    PptdDeckWriter().write_project(
        pptd_path=pptd_path,
        title="网络课程",
        nodes=nodes,
        slide_count=len(nodes),
        theme={"primary": "#123456"},
        skill_dir=skill_root,
        template_style="education courseware",
    )

    concept_page = (pptd_path.parent / "pages" / "slide-03.page").read_text(encoding="utf-8")
    preview = PptdProjectPreviewRenderer().preview_manifest(pptd_path=pptd_path)
    concept_svg = base64.b64decode(preview["pages"][2]["svg_data_url"].split(",", 1)[1]).decode("utf-8")

    assert "Old placeholder" not in concept_page
    assert "sourceTemplate: content1.page" in concept_page
    assert "concept-core-node" in concept_page
    assert "concept-definition-card" in concept_page
    assert "概念图解" in concept_svg
    assert "差错控制" in concept_svg


def test_pptd_semantic_renderer_compacts_text_without_visible_ellipsis(
    tmp_path: Path,
) -> None:
    skill_root = tmp_path / "pptx-skill"
    pages_dir = skill_root / "guideline" / "design" / "template" / "education-3" / "pages"
    pages_dir.mkdir(parents=True)
    (pages_dir.parent / "education-3.pptd").write_text(
        "\n".join(['title: "Template"', "size: [1280, 720]", "pages:", "  - pages/cover.page", ""]),
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
            "        Old placeholder",
            "",
        ]
    )
    for page_name in ("cover.page", "toc.page", "content1.page", "final.page"):
        (pages_dir / page_name).write_text(page_template, encoding="utf-8")

    long_bullet = (
        "带比特填充的定界符法：发送端遇到连续五个1后插入0，"
        "接收端据此恢复原始比特流并避免误判帧边界"
    )
    pptd_path = tmp_path / "artifacts" / "r-no-visible-ellipsis" / "slides" / "pptd" / "presentation.pptd"

    PptdDeckWriter().write_project(
        pptd_path=pptd_path,
        title="数据链路层成帧方法与差错检测机制的课堂讲解",
        nodes=[
            OutlineNode(title="封面", bullets=["课程入口"], page_type=SlidePageType.COVER),
            OutlineNode(title="目录", bullets=["成帧"], page_type=SlidePageType.TOC),
            OutlineNode(
                title="数据链路层成帧方法与差错检测机制的课堂讲解",
                bullets=[
                    long_bullet,
                    "字节填充法：FLAG 作为边界，ESC 处理数据中的冲突字符",
                    "CRC：把比特串除以生成多项式，用余数判断传输错误",
                    "ARQ：把检错结果转成确认、超时和重传动作",
                ],
            ),
            OutlineNode(title="总结", bullets=["迁移应用"], page_type=SlidePageType.SUMMARY),
        ],
        slide_count=4,
        theme={"primary": "#123456"},
        skill_dir=skill_root,
        template_style="education courseware",
    )

    concept_page = (pptd_path.parent / "pages" / "slide-03.page").read_text(encoding="utf-8")

    assert "sourceTemplate: content1.page" in concept_page
    assert "..." not in concept_page
    assert "…" not in concept_page
    assert "、；" not in concept_page
    assert "发送端遇到连续五个1后插入0" in concept_page


def test_pptd_semantic_renderer_does_not_split_ascii_acronyms_in_short_labels() -> None:
    renderer = PptdSemanticPageRenderer()

    label = renderer._compact_label("奇偶校验、校验和、CRC", max_len=10)

    assert label == "奇偶校验、校验和"
    assert not label.endswith("、C")


def test_pptd_semantic_renderer_respects_layout_hint_over_template_name() -> None:
    renderer = PptdSemanticPageRenderer()
    page = renderer.page_yaml(
        slide=PptdSlideContent(
            index=6,
            total=10,
            title="协议对比：回退N帧与选择重传",
            bullets=[
                "GBN：",
                "批量重传未确认帧",
                "SR：",
                "只重传出错帧",
            ],
            layout_hint="content-comparison",
        ),
        template_page_name="discussion.page",
    )

    assert "# sourceTemplate: discussion.page" in page
    assert "comparison-left-card" in page
    assert "concept-definition-card" not in page


def test_pptd_semantic_renderer_uses_metric_signal_over_template_name() -> None:
    renderer = PptdSemanticPageRenderer()
    page = renderer.page_yaml(
        slide=PptdSlideContent(
            index=7,
            total=10,
            title="性能指标：窗口大小与信道利用率",
            bullets=[
                "信道利用率 U = 发送时间 / (发送时间 + 往返延迟)",
                "滑动窗口: U = min(1, WT / (1 + 2a))",
                "例：a=2.5时，WT=5可达U≈71%",
            ],
        ),
        template_page_name="content3.page",
    )

    assert "# sourceTemplate: content3.page" in page
    assert "metric-card-1" in page
    assert "process-step-title-1" not in page


def test_pptd_semantic_renderer_does_not_treat_stat_hint_as_metric_without_metric_content() -> None:
    renderer = PptdSemanticPageRenderer()
    page = renderer.page_yaml(
        slide=PptdSlideContent(
            index=3,
            total=10,
            title="数据链路层功能与服务",
            bullets=[
                "核心功能：成帧、差错控制、流量控制",
                "设计目标：将物理层比特流转化为可靠、有序的帧传输",
                "服务类型：无确认无连接、有确认无连接、有确认有连接",
            ],
            layout_hint="content-stat-callout",
        ),
        template_page_name="content3.page",
    )

    assert "metric-card-1" not in page
    assert "process-step-title-1" in page


def test_pptd_semantic_renderer_does_not_promote_formula_only_content_to_metric() -> None:
    renderer = PptdSemanticPageRenderer()
    page = renderer.page_yaml(
        slide=PptdSlideContent(
            index=4,
            total=10,
            title="停止等待ARQ协议",
            bullets=[
                "机制：发送一帧，等待ACK，超时重传",
                "性能瓶颈：信道利用率低，如U≈1/541",
            ],
        ),
        template_page_name="content1.page",
    )

    assert "concept-definition-card" in page
    assert "metric-card-1" not in page


def test_pptd_semantic_renderer_protocol_title_overrides_metric_hint() -> None:
    renderer = PptdSemanticPageRenderer()
    page = renderer.page_yaml(
        slide=PptdSlideContent(
            index=4,
            total=10,
            title="停止等待ARQ协议",
            bullets=[
                "基本思想：发送一帧，等待确认（ACK）",
                "核心缺陷：信道利用率低，如示例中1/541",
            ],
            layout_hint="content-stat-callout",
        ),
        template_page_name="content4.page",
    )

    assert "concept-definition-card" in page
    assert "metric-card-1" not in page


def test_pptd_semantic_renderer_does_not_promote_performance_bottleneck_to_metric() -> None:
    renderer = PptdSemanticPageRenderer()
    page = renderer.page_yaml(
        slide=PptdSlideContent(
            index=5,
            total=10,
            title="性能瓶颈与滑动窗口思想",
            bullets=[
                "停等协议问题：大量时间浪费在等待确认",
                "核心思想：允许发送方连续发送多个帧",
            ],
        ),
        template_page_name="content3.page",
    )

    assert "metric-card-1" not in page
    assert "concept-definition-card" in page


def test_pptd_semantic_renderer_lets_metric_title_override_process_hint() -> None:
    renderer = PptdSemanticPageRenderer()
    page = renderer.page_yaml(
        slide=PptdSlideContent(
            index=7,
            total=10,
            title="性能量化：窗口大小与信道利用率",
            bullets=[
                "信道利用率公式：U = (W_S * T_frame) / (T_frame + 2*T_prop)",
                "W_S=1时退化为停止等待协议",
            ],
            layout_hint="content-process",
        ),
        template_page_name="content3.page",
    )

    assert "metric-card-1" in page
    assert "process-step-title-1" not in page


def test_pptd_semantic_renderer_lets_metric_title_override_comparison_hint() -> None:
    renderer = PptdSemanticPageRenderer()
    page = renderer.page_yaml(
        slide=PptdSlideContent(
            index=7,
            total=10,
            title="窗口大小与信道利用率量化",
            bullets=[
                "信道利用率 U = (帧发送时间 Tf) / (Tf + 往返时间 RTT)",
                "示例：Tf=1ms, RTT=540ms",
            ],
            layout_hint="content-comparison",
        ),
        template_page_name="content2.page",
    )

    assert "metric-card-1" in page
    assert "comparison-left-card" not in page


def test_pptd_semantic_renderer_uses_distinct_metric_bullets() -> None:
    renderer = PptdSemanticPageRenderer()
    slide = PptdSlideContent(
        index=7,
        total=10,
        title="窗口大小与信道利用率",
        bullets=[
            "利用率公式：U = W / (1 + 2a)，a=传播时延/发送时延",
            "停止等待(U=1/541≈0.2%)与滑动窗口对比",
            "窗口大小W的选择：需满足 W ≤ 1+2a",
        ],
    )

    metrics = renderer._metric_items(slide)
    page = renderer.page_yaml(slide=slide, template_page_name="data_analysis.page")

    assert metrics[0] != metrics[1]
    assert "GBN" not in page
    assert "SR" not in page
    assert "metric-table-1-0" in page


def test_pptd_semantic_renderer_preserves_formula_metric_cards() -> None:
    renderer = PptdSemanticPageRenderer()

    number, unit, desc = renderer._metric_parts(
        "利用率公式：U = W / (1 + 2a)，a=传播时延/发送时延",
        fallback="1",
    )

    assert number == "01"
    assert unit == "U"
    assert desc == "U = W / (1 + 2a)，a=传播时延/发送时延"
    assert "U = W / ，" not in desc


def test_pptd_semantic_renderer_preserves_min_formula_metric_cards() -> None:
    renderer = PptdSemanticPageRenderer()

    number, unit, desc = renderer._metric_parts(
        "滑动窗口: U = min(1, WT / (1 + 2a))",
        fallback="2",
    )

    assert number == "02"
    assert unit == "U"
    assert "min(1, WT / (1 + 2a))" in desc


def test_pptd_semantic_renderer_handles_long_formula_symbols() -> None:
    renderer = PptdSemanticPageRenderer()

    number, unit, desc = renderer._metric_parts(
        "发送时长公式：T_frame = frame_bits / link_rate",
        fallback="3",
    )

    assert number == "03"
    assert unit == "Tf"
    assert desc == "T_frame = frame_bits / link_rate"


def test_pptd_semantic_renderer_preserves_formula_metric_table_cells() -> None:
    renderer = PptdSemanticPageRenderer()

    rows = renderer._metric_summary_rows(
        [
            "信道利用率 U = WT / (1 + 2a)，a = 传播时延/发送时延",
            "停等协议 U = 1/(1+2a)，效率极低",
            "增大窗口WT可提高U，直至U≈100%",
            "滑动窗口(WS=10)：利用率显著提升，可近100%",
        ]
    )
    formula = renderer._metric_table_cell(
        "U ≈ 1/(1+2a)，其中 a = 传播时延/发送时延",
        col=1,
        is_header=False,
    )
    compact_formula = renderer._metric_table_cell(
        "U ≈ W / (1 + 2a)，W 为窗口大小",
        col=1,
        is_header=False,
    )
    compact_window_formula = renderer._metric_table_cell(
        "Ws ≥ 1 + 2a (a = Tp/Tt)，满足窗口规模",
        col=1,
        is_header=False,
    )
    page = renderer.page_yaml(
        slide=PptdSlideContent(
            index=8,
            total=10,
            title="窗口大小与信道利用率",
            bullets=[
                "信道利用率 U = (发送时间) / (发送时间 + 传播时延 + 确认时延)",
                "停止等待：U ≈ 1/(1+2a)，其中 a = 传播时延/发送时延",
                "滑动窗口：U = min(1, WT / (1 + 2a))",
            ],
            layout_hint="content-stat-callout",
        ),
        template_page_name="data_analysis.page",
    )

    assert rows[1][0] == "信道利用率"
    assert rows[1][1] == "U = WT/(1+2a)"
    assert "U = WT / ，" not in rows[1][1]
    assert rows[2][:2] == ("停等协议", "U = 1/(1+2a)，效率极低")
    assert "U =" not in rows[2][0]
    assert renderer._formula_metric_row("滑动窗口(WS=10)：利用率显著提升，可近100%") is None
    assert formula == "U ≈ 1/(1+2a)"
    assert compact_formula == "U ≈ W/(1+2a)"
    assert compact_window_formula == "Ws≥1+2a(a=Tp/Tt)"
    assert "a =" not in formula
    assert "W 为" not in compact_formula
    assert compact_window_formula.count("(") == compact_window_formula.count(")")
    assert "U ≈ 1/，" not in formula
    assert "U ≈ 1/，" not in page
    assert "wrap: false" in page


def test_pptd_semantic_renderer_uses_grouped_metric_extras_before_padding() -> None:
    renderer = PptdSemanticPageRenderer()
    slide = PptdSlideContent(
        index=8,
        total=10,
        title="窗口大小与信道利用率指标",
        bullets=[
            "GBN：",
            "GBN窗口限制: Ws ≤ 2^n - 1",
            "SR：",
            "SR窗口限制: Ws ≤ 2^(n-1)",
            "窗口效率公式: U = min(Ws, 1+2a) / (1+2a)",
        ],
        layout_hint="content-stat-callout",
    )

    metrics = renderer._metric_items(slide)

    assert len(metrics) == 3
    assert metrics[0].startswith("GBN：")
    assert metrics[1].startswith("SR：")
    assert metrics[2].startswith("窗口效率公式")


def test_pptd_semantic_renderer_keeps_protocol_case_as_concept() -> None:
    renderer = PptdSemanticPageRenderer()
    page = renderer.page_yaml(
        slide=PptdSlideContent(
            index=8,
            total=10,
            title="协议实例：PPP与PPPoE",
            bullets=[
                "PPP（点对点协议）：拨号上网、专线连接",
                "PPPoE：在以太网上封装PPP，用于宽带接入",
            ],
            layout_hint="content-stat-callout",
        ),
        template_page_name="content4.page",
    )

    assert "concept-definition-card" in page
    assert "metric-card-1" not in page


def test_pptd_semantic_renderer_shortens_metric_units() -> None:
    renderer = PptdSemanticPageRenderer()

    number, unit, desc = renderer._metric_parts(
        "点对点协议 (PPP)：用途：拨号上网、专线连接等点对点链路",
        fallback="1",
    )

    assert number == "01"
    assert unit == "点对点协议"
    assert len(unit) <= 6
    assert "拨号上网" in desc


def test_pptd_semantic_renderer_keeps_numeric_examples_out_of_metric_number_slot() -> None:
    renderer = PptdSemanticPageRenderer()

    number, unit, desc = renderer._metric_parts(
        "性能分析（量化示例）：停等协议：帧长1000b、速率1Mbps",
        fallback="2",
    )

    assert number == "02"
    assert unit == "b"
    assert "100" not in number
    assert "速率1Mbps" in desc


def test_pptd_semantic_renderer_compacts_course_metric_labels_for_template_slots() -> None:
    renderer = PptdSemanticPageRenderer()

    number, unit, desc = renderer._metric_parts(
        "带宽-延迟积(BDP)：衡量链路容量的关键指标",
        fallback="3",
    )
    table_cell = renderer._metric_table_cell(
        "允许发送方连续发送多个帧而不等待确认",
        col=1,
        is_header=False,
    )

    assert number == "03"
    assert unit == "带宽延迟积"
    assert desc == "衡量链路容量"
    assert table_cell == "连续发送多个帧不等ACK"


def test_pptd_semantic_renderer_cleans_nested_bullet_markers() -> None:
    renderer = PptdSemanticPageRenderer()

    items = renderer._display_items(
        PptdSlideContent(
            index=5,
            total=10,
            title="滑动窗口协议",
            bullets=["  • 发送窗口 W_s：允许连续发送的未确认帧数量"],
        ),
        count=1,
    )

    assert items == ["发送窗口 W_s：允许连续发送的未确认帧数量"]


def test_pptd_concept_takeaway_uses_short_complete_judgment(tmp_path: Path) -> None:
    skill_root = tmp_path / "pptx-skill"
    pages_dir = skill_root / "guideline" / "design" / "template" / "education-3" / "pages"
    pages_dir.mkdir(parents=True)
    (pages_dir.parent / "education-3.pptd").write_text(
        "\n".join(['title: "Template"', "size: [1280, 720]", "pages:", "  - pages/cover.page", ""]),
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
            "        Old placeholder",
            "",
        ]
    )
    for page_name in ("cover.page", "toc.page", "content1.page", "final.page"):
        (pages_dir / page_name).write_text(page_template, encoding="utf-8")

    pptd_path = tmp_path / "artifacts" / "r-complete-takeaway" / "slides" / "pptd" / "presentation.pptd"
    PptdDeckWriter().write_project(
        pptd_path=pptd_path,
        title="网络课程",
        nodes=[
            OutlineNode(title="封面", bullets=["课程入口"], page_type=SlidePageType.COVER),
            OutlineNode(title="目录", bullets=["成帧"], page_type=SlidePageType.TOC),
            OutlineNode(
                title="成帧与差错检测技术",
                bullets=[
                    "成帧：将比特流划分为帧，关键问题是标识帧的开始与结束。",
                    "常用方法：字节计数法、字节填充法、比特填充法",
                    "差错检测：通过增加冗余信息（校验码）来检测传输错误。",
                    "典型检错码：循环冗余校验 (CRC)",
                ],
            ),
            OutlineNode(title="总结", bullets=["迁移应用"], page_type=SlidePageType.SUMMARY),
        ],
        slide_count=4,
        theme={"primary": "#123456"},
        skill_dir=skill_root,
        template_style="education courseware",
    )

    concept_page = (pptd_path.parent / "pages" / "slide-03.page").read_text(encoding="utf-8")
    summary_block = re.search(
        r"elementId: concept-takeaway-text.*?(?=\n  - elementId:|\Z)",
        concept_page,
        flags=re.S,
    )

    assert summary_block is not None
    text = summary_block.group(0)
    body_match = re.search(r"<p><strong>(.*?)</strong></p>", text)
    assert body_match is not None
    body = body_match.group(1)
    assert "课堂判断：" in text
    assert "（校验" not in text
    assert "通过增加冗余信" not in body
    assert len(body) <= 42


def test_pptd_concept_takeaway_prefers_labels_over_partial_summaries(tmp_path: Path) -> None:
    skill_root = tmp_path / "pptx-skill"
    pages_dir = skill_root / "guideline" / "design" / "template" / "education-3" / "pages"
    pages_dir.mkdir(parents=True)
    (pages_dir.parent / "education-3.pptd").write_text(
        "\n".join(['title: "Template"', "size: [1280, 720]", "pages:", "  - pages/cover.page", ""]),
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
            "        Old placeholder",
            "",
        ]
    )
    for page_name in ("cover.page", "toc.page", "content1.page", "final.page"):
        (pages_dir / page_name).write_text(page_template, encoding="utf-8")

    pptd_path = tmp_path / "artifacts" / "r-arq-takeaway" / "slides" / "pptd" / "presentation.pptd"
    PptdDeckWriter().write_project(
        pptd_path=pptd_path,
        title="网络课程",
        nodes=[
            OutlineNode(title="封面", bullets=["课程入口"], page_type=SlidePageType.COVER),
            OutlineNode(title="目录", bullets=["ARQ"], page_type=SlidePageType.TOC),
            OutlineNode(
                title="ARQ：自动重传请求机制",
                bullets=[
                    "ARQ：接收方反馈确认(ACK/NAK)，发送方据此重传",
                    "停等ARQ：发送一帧，等待确认后再发下一帧",
                    "回退N帧ARQ：发送方可连续发送",
                    "选择重传ARQ：只重传出错的单个帧，效率更高",
                ],
            ),
            OutlineNode(title="总结", bullets=["迁移应用"], page_type=SlidePageType.SUMMARY),
        ],
        slide_count=4,
        theme={"primary": "#123456"},
        skill_dir=skill_root,
        template_style="education courseware",
    )

    concept_page = (pptd_path.parent / "pages" / "slide-03.page").read_text(encoding="utf-8")
    summary_block = re.search(
        r"elementId: concept-takeaway-text.*?(?=\n  - elementId:|\Z)",
        concept_page,
        flags=re.S,
    )

    assert "<p><strong>回退N帧ARQ</strong></p>" in concept_page
    assert "<p><strong>选择重传ARQ</strong></p>" in concept_page
    assert summary_block is not None
    assert "课堂判断：停等ARQ、回退N帧ARQ、选择重传ARQ" in summary_block.group(0)
    assert "发送方可" not in summary_block.group(0)


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
