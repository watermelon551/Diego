from __future__ import annotations

import asyncio
import json
import posixpath
import re
import subprocess
import time
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient

import service.orchestrator as orchestrator_mod
from service.app import create_app
from service.config import Settings, load_settings
from service.llm_client import GeneratedSlide, MockLLMClient
from service.models import OutlineDocument, OutlineNode
from service.orchestrator import RunOrchestrator
from service.store import RunStore


class SlowMockLLMClient(MockLLMClient):
    async def generate_outline(self, **kwargs):
        await asyncio.sleep(0.05)
        return await super().generate_outline(**kwargs)


class CaptureRepairCandidateLLM(MockLLMClient):
    def __init__(self) -> None:
        self.review_candidate_titles: list[str] = []

    async def generate_slide(self, **kwargs):
        outline_node = kwargs["outline_node"]
        slide_no = kwargs["slide_no"]
        return await super().generate_slide(
            **{
                **kwargs,
                "outline_node": OutlineNode(
                    title=f"GEN-{slide_no}-{outline_node.title}",
                    bullets=[f"GEN bullet {slide_no}.1", f"GEN bullet {slide_no}.2"],
                    page_type=outline_node.page_type,
                    layout_hint=outline_node.layout_hint,
                ),
            }
        )

    async def review_slide(self, **kwargs):
        candidate = kwargs["candidate"]
        self.review_candidate_titles.append(candidate.title)
        return await super().review_slide(**kwargs)


class CaptureTemplateRepairLLM(MockLLMClient):
    def __init__(self) -> None:
        self.review_candidate_titles: list[str] = []

    async def review_slide(self, **kwargs):
        candidate = kwargs["candidate"]
        outline_node = kwargs["outline_node"]
        self.review_candidate_titles.append(candidate.title)
        seq = len(self.review_candidate_titles)
        return GeneratedSlide(
            title=f"TMP-{seq}-{candidate.title}",
            bullets=[f"TMP bullet {seq}.1", f"TMP bullet {seq}.2"],
            citations=list(candidate.citations),
            page_type=outline_node.page_type,
            layout_hint=outline_node.layout_hint,
        )


class AgenticMockLLM(MockLLMClient):
    async def generate_slide_js(self, **kwargs):
        outline_node = kwargs["outline_node"]
        slide_no = kwargs["slide_no"]
        total = kwargs["target_slide_count"]
        theme = kwargs["theme"]
        title = json.dumps(f"AGENTIC-{outline_node.title}", ensure_ascii=False)
        bullets = json.dumps(outline_node.bullets or [f"A{slide_no}.1", f"A{slide_no}.2"], ensure_ascii=False)
        return "\n".join(
            [
                "const pptxgen = require('pptxgenjs');",
                "const slideConfig = {",
                f"  type: {json.dumps(outline_node.page_type.value)},",
                f"  index: {slide_no},",
                f"  total: {total},",
                f"  title: {title},",
                f"  layoutHint: {json.dumps(outline_node.layout_hint or 'content-two-column')},",
                f"  bullets: {bullets},",
                "};",
                "function addPageBadge(pres, slide, theme, n) {",
                "  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.accent }, line: { color: theme.accent } });",
                "  slide.addText(String(n), { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 10, fontFace: 'Arial', color: 'FFFFFF', bold: true, align: 'center', valign: 'mid', margin: 0 });",
                "}",
                "function createSlide(pres, theme) {",
                "  const slide = pres.addSlide();",
                "  slide.background = { color: theme.bg };",
                "  slide.addText(slideConfig.title, { x: 0.5, y: 0.4, w: 9.0, h: 0.8, fontSize: 34, fontFace: 'Arial', color: theme.primary, bold: true, fit: 'shrink' });",
                "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.8, y: 1.5, w: 8.4, h: 3.5, fill: { color: theme.light, transparency: 10 }, line: { color: theme.secondary, pt: 1 } });",
                "  const rows = (slideConfig.bullets || []).map((text, idx) => ({ text, options: { bullet: true, breakLine: idx < (slideConfig.bullets || []).length - 1 } }));",
                "  slide.addText(rows, { x: 1.1, y: 1.9, w: 7.8, h: 2.7, fontSize: 16, fontFace: 'Arial', color: theme.secondary, margin: 0, fit: 'shrink' });",
                "  if (slideConfig.type !== 'cover') addPageBadge(pres, slide, theme, slideConfig.index);",
                "  return slide;",
                "}",
                "if (require.main === module) {",
                "  const pres = new pptxgen();",
                "  pres.layout = 'LAYOUT_16x9';",
                f"  const theme = {json.dumps(theme, ensure_ascii=False)};",
                "  createSlide(pres, theme);",
                f"  pres.writeFile({{ fileName: 'slide-{slide_no:02d}-preview.pptx' }});",
                "}",
                "module.exports = { createSlide, slideConfig };",
            ]
        )


class ImageHeavyAgenticLLM(AgenticMockLLM):
    async def generate_slide_js(self, **kwargs):
        base = await super().generate_slide_js(**kwargs)
        return base.replace(
            "  const rows = (slideConfig.bullets || []).map((text, idx) => ({ text, options: { bullet: true, breakLine: idx < (slideConfig.bullets || []).length - 1 } }));",
            "  slide.addImage({ path: 'https://example.com/fake.png', x: 6.8, y: 1.5, w: 2.2, h: 1.6 });\n"
            "  const rows = (slideConfig.bullets || []).map((text, idx) => ({ text, options: { bullet: true, breakLine: idx < (slideConfig.bullets || []).length - 1 } }));",
        )


def fake_subprocess_run(args, cwd=None, capture_output=False, text=False, check=False, **kwargs):
    cmd = " ".join(args) if isinstance(args, (list, tuple)) else str(args)
    if "node" in cmd and "compile.js" in cmd:
        out = Path(cwd) / "output"
        out.mkdir(parents=True, exist_ok=True)
        (out / "presentation.pptx").write_bytes(b"fake-pptx")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="compiled", stderr="")
    if "node" in cmd and "slide-" in cmd and cmd.strip().endswith(".js"):
        match = re.search(r"slide-(\d+)(?:-cand-\d+)?\.js", cmd)
        if match:
            preview = Path(cwd) / f"slide-{int(match.group(1)):02d}-preview.pptx"
            preview.write_bytes(b"fake-preview-pptx")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="preview", stderr="")
    if "python" in cmd and "markitdown" in cmd:
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="slide content extracted", stderr="")
    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")


def make_settings() -> Settings:
    return Settings(
        llm_api_style="openai_chat",
        llm_base_url="https://api.example.com",
        llm_api_key="test",
        llm_model="test-model",
        llm_timeout_sec=30.0,
        llm_max_retries=2,
        llm_temperature_outline=0.3,
        llm_temperature_slide=0.6,
        slide_concurrency=2,
        slide_retry=2,
        qa_enabled=True,
        repair_rounds=2,
        asset_provider="mock",
        unsplash_access_key="",
        pexels_api_key="",
        asset_timeout_sec=5.0,
        asset_max_retries=1,
        generation_engine="legacy",
        debug_keep_previews=False,
        max_slide_repair_rounds=2,
    )


def make_client(tmp_path: Path, llm_client: MockLLMClient | None = None) -> TestClient:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=llm_client or MockLLMClient(),
        settings=make_settings(),
    )
    return TestClient(create_app(base_dir=tmp_path, orchestrator=orch))


def wait_status(client: TestClient, run_id: str, expected: set[str], timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/v1/ppt/runs/{run_id}").json()
        if data["status"] in expected:
            return data
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} not in {expected} within {timeout}s")


def build_template_pptx(path: Path) -> None:
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<?xml version='1.0' encoding='UTF-8'?><Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'></Types>")
        zf.writestr("ppt/slides/slide1.xml", "<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main' xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><a:t>Template Placeholder</a:t></p:sld>")


def build_structured_template_pptx(path: Path) -> None:
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
  <Override PartName="/ppt/slides/slide2.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
</Types>
"""
    presentation_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldIdLst>
    <p:sldId id="256" r:id="rId1"/>
    <p:sldId id="257" r:id="rId2"/>
  </p:sldIdLst>
  <p:sldSz cx="9144000" cy="5143500" type="screen16x9"/>
  <p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>
"""
    presentation_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide2.xml"/>
</Relationships>
"""
    slide_tpl = "<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main' xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><p:cSld><p:spTree><p:sp><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>{text}</a:t></a:r></a:p><a:p><a:r><a:t>old bullet</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("ppt/presentation.xml", presentation_xml)
        zf.writestr("ppt/_rels/presentation.xml.rels", presentation_rels)
        zf.writestr("ppt/slides/slide1.xml", slide_tpl.format(text="Template Slide 1"))
        zf.writestr("ppt/slides/slide2.xml", slide_tpl.format(text="Template Slide 2"))


def build_semantic_template_pptx(path: Path) -> None:
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
  <Override PartName="/ppt/slides/slide2.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
  <Override PartName="/ppt/charts/chart1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>
</Types>
"""
    presentation_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldIdLst>
    <p:sldId id="256" r:id="rId1"/>
    <p:sldId id="257" r:id="rId2"/>
  </p:sldIdLst>
  <p:sldSz cx="9144000" cy="5143500" type="screen16x9"/>
  <p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>
"""
    presentation_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide2.xml"/>
</Relationships>
"""
    slide_xml = """<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<p:cSld><p:spTree>
  <p:sp><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Template Placeholder Title</a:t></a:r></a:p><a:p><a:r><a:t>caption placeholder</a:t></a:r></a:p></p:txBody></p:sp>
  <p:graphicFrame><a:graphic><a:graphicData><a:tbl><a:tr><a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>placeholder cell</a:t></a:r></a:p></a:txBody></a:tc></a:tr></a:tbl></a:graphicData></a:graphic></p:graphicFrame>
  <p:pic>
    <p:nvPicPr><p:cNvPr id="11" name="Image Placeholder" descr="placeholder image"/></p:nvPicPr>
    <p:blipFill><a:blip r:embed="rId2"/></p:blipFill>
  </p:pic>
  <p:pic>
    <p:nvPicPr><p:cNvPr id="12" name="Icon Placeholder" descr="placeholder icon"/></p:nvPicPr>
    <p:blipFill><a:blip r:embed="rId3"/></p:blipFill>
  </p:pic>
</p:spTree></p:cSld>
</p:sld>"""
    slide_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="../charts/chart1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/icon1.png"/>
</Relationships>
"""
    chart_xml = """<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
<c:chart><c:title><c:tx><c:rich><a:p><a:r><a:t>Chart Placeholder</a:t></a:r></a:p></c:rich></c:tx></c:title>
<c:plotArea><c:barChart><c:ser>
<c:cat><c:strRef><c:strCache><c:ptCount val="2"/><c:pt idx="0"><c:v>A</c:v></c:pt><c:pt idx="1"><c:v>B</c:v></c:pt></c:strCache></c:strRef></c:cat>
<c:val><c:numRef><c:numCache><c:ptCount val="2"/><c:pt idx="0"><c:v>1</c:v></c:pt><c:pt idx="1"><c:v>2</c:v></c:pt></c:numCache></c:numRef></c:val>
</c:ser></c:barChart></c:plotArea></c:chart></c:chartSpace>"""
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("ppt/presentation.xml", presentation_xml)
        zf.writestr("ppt/_rels/presentation.xml.rels", presentation_rels)
        zf.writestr("ppt/slides/slide1.xml", slide_xml)
        zf.writestr("ppt/slides/slide2.xml", slide_xml.replace("Template Placeholder Title", "Second Slide Placeholder"))
        zf.writestr("ppt/slides/_rels/slide1.xml.rels", slide_rels)
        zf.writestr("ppt/slides/_rels/slide2.xml.rels", slide_rels)
        zf.writestr("ppt/charts/chart1.xml", chart_xml)
        zf.writestr("ppt/media/image1.png", b"placeholder-image")
        zf.writestr("ppt/media/icon1.png", b"placeholder-icon")


def build_excess_slot_template_pptx(path: Path) -> None:
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
</Types>
"""
    presentation_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldIdLst>
    <p:sldId id="256" r:id="rId1"/>
  </p:sldIdLst>
</p:presentation>
"""
    presentation_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>
</Relationships>
"""
    slide_xml = """<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<p:cSld><p:spTree>
  <p:sp><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Template Placeholder Title</a:t></a:r></a:p></p:txBody></p:sp>
  <p:pic><p:nvPicPr><p:cNvPr id="11" name="Image Placeholder 1" descr="placeholder image"/></p:nvPicPr><p:blipFill><a:blip r:embed="rId2"/></p:blipFill></p:pic>
  <p:pic><p:nvPicPr><p:cNvPr id="12" name="Image Placeholder 2" descr="placeholder image"/></p:nvPicPr><p:blipFill><a:blip r:embed="rId3"/></p:blipFill></p:pic>
  <p:pic><p:nvPicPr><p:cNvPr id="13" name="Image Placeholder 3" descr="placeholder image"/></p:nvPicPr><p:blipFill><a:blip r:embed="rId4"/></p:blipFill></p:pic>
</p:spTree></p:cSld>
</p:sld>"""
    slide_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image2.png"/>
  <Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image3.png"/>
</Relationships>
"""
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("ppt/presentation.xml", presentation_xml)
        zf.writestr("ppt/_rels/presentation.xml.rels", presentation_rels)
        zf.writestr("ppt/slides/slide1.xml", slide_xml)
        zf.writestr("ppt/slides/_rels/slide1.xml.rels", slide_rels)
        zf.writestr("ppt/media/image1.png", b"img1")
        zf.writestr("ppt/media/image2.png", b"img2")
        zf.writestr("ppt/media/image3.png", b"img3")


def build_unknown_slot_template_pptx(path: Path) -> None:
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
</Types>
"""
    presentation_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldIdLst>
    <p:sldId id="256" r:id="rId1"/>
  </p:sldIdLst>
</p:presentation>
"""
    presentation_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>
</Relationships>
"""
    slide_xml = """<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
<p:cSld><p:spTree>
  <p:sp>
    <p:nvSpPr><p:cNvPr id="21" name="SmartArt Placeholder" descr="placeholder smart-art"/></p:nvSpPr>
    <p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Template Placeholder Title</a:t></a:r></a:p></p:txBody>
  </p:sp>
</p:spTree></p:cSld>
</p:sld>"""
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("ppt/presentation.xml", presentation_xml)
        zf.writestr("ppt/_rels/presentation.xml.rels", presentation_rels)
        zf.writestr("ppt/slides/slide1.xml", slide_xml)


def build_layout_conflict_template_pptx(path: Path) -> None:
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
</Types>
"""
    presentation_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldIdLst>
    <p:sldId id="256" r:id="rId1"/>
  </p:sldIdLst>
</p:presentation>
"""
    presentation_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>
</Relationships>
"""
    slide_xml = """<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
<p:cSld><p:spTree>
  <p:sp>
    <p:nvSpPr><p:cNvPr id="31" name="Text Placeholder"/></p:nvSpPr>
    <p:spPr>
      <a:xfrm><a:off x="0" y="0"/><a:ext cx="10000000" cy="6000000"/></a:xfrm>
    </p:spPr>
    <p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Template Placeholder Title</a:t></a:r></a:p></p:txBody>
  </p:sp>
</p:spTree></p:cSld>
</p:sld>"""
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("ppt/presentation.xml", presentation_xml)
        zf.writestr("ppt/_rels/presentation.xml.rels", presentation_rels)
        zf.writestr("ppt/slides/slide1.xml", slide_xml)


@pytest.fixture(autouse=True)
def patch_tools(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(orchestrator_mod.subprocess, "run", fake_subprocess_run)
    yield


def test_missing_llm_env_should_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(ValueError):
        load_settings(env_file="tests/.missing.env")


def test_create_run_and_validation(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert client.post("/v1/ppt/runs", json={"project_id": "p1"}).status_code == 422

    resp = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "AI 101",
            "project_id": "p1",
            "rag_source_ids": ["chunk-1", "chunk-2"],
            "template_style": "clean",
            "target_slide_count": 3,
            "generation_mode": "scratch",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "OUTLINE_DRAFTING"


def test_create_run_from_prompt_endpoint(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    resp = client.post(
        "/v1/ppt/runs/prompt",
        json={
            "prompt": "AI Agents for Product Teams",
            "project_id": "p-prompt",
            "rag_source_ids": ["r1", "r2"],
            "template_style": "default",
            "target_slide_count": 3,
            "generation_mode": "scratch",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "OUTLINE_DRAFTING"
    detail = wait_status(client, data["run_id"], {"AWAITING_OUTLINE_CONFIRM"})
    assert len(detail["outline"]["nodes"]) == 3
    assert detail["outline_history"]
    assert detail["research_report"]["audience"]
    assert detail["research_report"]["page_focus"]


def test_confirm_gate_and_scratch_success_flow(tmp_path: Path) -> None:
    client = make_client(tmp_path, llm_client=SlowMockLLMClient())
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Data Platform",
            "project_id": "p2",
            "rag_source_ids": ["a", "b", "c"],
            "template_style": "business",
            "target_slide_count": 4,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]

    assert client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True}).status_code == 409
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    assert client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True}).status_code == 200
    final_data = wait_status(client, run_id, {"SUCCEEDED"})

    assert final_data["pptx_path"] and Path(final_data["pptx_path"]).exists()
    assert final_data["compile_js_path"] and Path(final_data["compile_js_path"]).exists()
    assert len(final_data["slides"]) == 4
    assert all(item.get("js_path") and Path(item["js_path"]).exists() for item in final_data["slides"])
    assert final_data["qa_report"]["passed"] is True


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
    assert final["quality_gate_report"]["threshold"] == 80
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


def test_visual_policy_media_required_should_fail_when_images_missing(tmp_path: Path) -> None:
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
            "topic": "Visual Policy Required",
            "project_id": "p-vp-media",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 5,
            "generation_mode": "scratch",
            "visual_policy": "media_required",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"FAILED"})
    assert final["error_code"] == "VISUAL_POLICY_UNSATISFIED"


def test_visual_policy_basic_graphics_only_should_fail_when_image_present(tmp_path: Path) -> None:
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
        llm_client=ImageHeavyAgenticLLM(),
        settings=settings,
    )
    client = TestClient(create_app(base_dir=tmp_path, orchestrator=orch))

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "No Images Allowed",
            "project_id": "p-vp-basic",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 5,
            "generation_mode": "scratch",
            "visual_policy": "basic_graphics_only",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"FAILED"})
    assert final["error_code"] == "VISUAL_POLICY_UNSATISFIED"


def test_outline_update_then_approve_flow(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Editable Outline",
            "project_id": "p-edit",
            "rag_source_ids": ["c1", "c2"],
            "template_style": "business",
            "target_slide_count": 3,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    drafted = wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    base_version = drafted["outline"]["version"]

    edited_outline = OutlineDocument(
        version=base_version,
        summary="edited summary",
        nodes=[
            OutlineNode(title="封面", bullets=["主题导入"], page_type="cover", layout_hint="cover-asymmetric"),
            OutlineNode(title="目录", bullets=["问题", "方法", "结果"], page_type="toc", layout_hint="toc-list"),
            OutlineNode(title="总结", bullets=["结论", "行动项"], page_type="summary", layout_hint="summary-cta"),
        ],
    ).model_dump(mode="json")

    update_resp = client.post(
        f"/v1/ppt/runs/{run_id}/outline/confirm",
        json={
            "approved": False,
            "outline": edited_outline,
            "base_version": base_version,
            "change_reason": "用户修改结构",
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "AWAITING_OUTLINE_CONFIRM"

    detail_after_update = client.get(f"/v1/ppt/runs/{run_id}").json()
    assert detail_after_update["outline"]["version"] == base_version + 1
    assert detail_after_update["outline_history"][-1]["action"] == "updated"

    approve_resp = client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    assert approve_resp.status_code == 200
    final_data = wait_status(client, run_id, {"SUCCEEDED"})
    assert len(final_data["slides"]) == 3
    assert final_data["qa_report"]["passed"] is True


def test_outline_update_with_wrong_base_version_should_conflict(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Version Check",
            "project_id": "p-version",
            "rag_source_ids": ["s1"],
            "template_style": "default",
            "target_slide_count": 2,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    drafted = wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    outline = drafted["outline"]
    resp = client.post(
        f"/v1/ppt/runs/{run_id}/outline/confirm",
        json={
            "approved": False,
            "outline": outline,
            "base_version": outline["version"] + 10,
            "change_reason": "wrong version",
        },
    )
    assert resp.status_code == 409


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


def test_template_repair_uses_latest_template_candidate_not_outline_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    llm = CaptureTemplateRepairLLM()
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=llm,
        settings=make_settings(),
    )

    call_counter = {"n": 0}

    async def flaky_markitdown_check(_pptx_path: Path):
        call_counter["n"] += 1
        if call_counter["n"] == 1:
            return False, "forced template qa failure"
        return True, None

    monkeypatch.setattr(orch, "_markitdown_check", flaky_markitdown_check)
    client = TestClient(create_app(base_dir=tmp_path, orchestrator=orch))

    template_file = tmp_path / "template_repair.pptx"
    build_structured_template_pptx(template_file)
    with template_file.open("rb") as fp:
        upload = client.post(
            "/v1/ppt/templates",
            files={"file": ("template_repair.pptx", fp, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert upload.status_code == 200
    template_id = upload.json()["template_id"]

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Template Repair Loop",
            "project_id": "p-template-repair",
            "rag_source_ids": ["r1"],
            "template_style": "default",
            "target_slide_count": 1,
            "generation_mode": "template",
            "template_id": template_id,
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED"})
    assert final["qa_report"]["passed"] is True
    assert len(llm.review_candidate_titles) >= 2
    assert any(title.startswith("TMP-1-") for title in llm.review_candidate_titles[1:])


def test_event_stream_has_required_events(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Observability",
            "project_id": "p3",
            "rag_source_ids": ["s1", "s2"],
            "template_style": "default",
            "target_slide_count": 2,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    wait_status(client, run_id, {"SUCCEEDED"})

    with client.stream("GET", f"/v1/ppt/runs/{run_id}/events") as stream:
        body = "".join(chunk for chunk in stream.iter_text())

    assert "event: outline.token" in body
    assert "event: outline.completed" in body
    assert "event: research.completed" in body
    assert "event: plan.completed" in body
    assert "event: slide.generated" in body
    assert "event: qa.completed" in body
    assert "event: slide.preview.qa" in body
    assert "event: chart.truth.checked" in body


def test_template_upload_and_template_generation(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    template_file = tmp_path / "template.pptx"
    build_template_pptx(template_file)

    with template_file.open("rb") as fp:
        upload = client.post(
            "/v1/ppt/templates",
            files={"file": ("template.pptx", fp, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert upload.status_code == 200
    template_id = upload.json()["template_id"]

    detail = client.get(f"/v1/ppt/templates/{template_id}")
    assert detail.status_code == 200

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Template Run",
            "project_id": "p4",
            "rag_source_ids": ["x"],
            "template_style": "default",
            "target_slide_count": 2,
            "generation_mode": "template",
            "template_id": template_id,
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED"})
    assert final["pptx_path"] and Path(final["pptx_path"]).exists()
    assert final["compile_js_path"] and Path(final["compile_js_path"]).exists()
    assert final["slides"]
    assert all(item.get("js_path") and Path(item["js_path"]).exists() for item in final["slides"])
    assert final["qa_report"]["passed"] is True


def test_template_structural_rebuild_for_target_count(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    template_file = tmp_path / "structured_template.pptx"
    build_structured_template_pptx(template_file)

    with template_file.open("rb") as fp:
        upload = client.post(
            "/v1/ppt/templates",
            files={"file": ("structured_template.pptx", fp, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert upload.status_code == 200
    template_id = upload.json()["template_id"]

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Template Rebuild",
            "project_id": "p5",
            "rag_source_ids": ["r1", "r2"],
            "template_style": "business",
            "target_slide_count": 3,
            "generation_mode": "template",
            "template_id": template_id,
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED"})

    output_pptx = Path(final["pptx_path"])
    assert output_pptx.exists()
    with ZipFile(output_pptx, "r") as zf:
        names = set(zf.namelist())
        assert "ppt/slides/slide1.xml" in names
        assert "ppt/slides/slide2.xml" in names
        assert "ppt/slides/slide3.xml" in names
        presentation_xml = zf.read("ppt/presentation.xml").decode("utf-8", errors="ignore")
        content_types_xml = zf.read("[Content_Types].xml").decode("utf-8", errors="ignore")

    assert presentation_xml.count("<p:sldId ") == 3
    assert "/ppt/slides/slide3.xml" in content_types_xml


def test_template_semantic_placeholder_replacement(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    template_file = tmp_path / "semantic_template.pptx"
    build_semantic_template_pptx(template_file)

    with template_file.open("rb") as fp:
        upload = client.post(
            "/v1/ppt/templates",
            files={"file": ("semantic_template.pptx", fp, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert upload.status_code == 200
    template_id = upload.json()["template_id"]

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Semantic Template",
            "project_id": "p7",
            "rag_source_ids": ["r1", "r2"],
            "template_style": "business",
            "target_slide_count": 2,
            "generation_mode": "template",
            "template_id": template_id,
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED"})

    output_pptx = Path(final["pptx_path"])
    assert output_pptx.exists()
    with ZipFile(output_pptx, "r") as zf:
        slide1_xml = zf.read("ppt/slides/slide1.xml").decode("utf-8", errors="ignore")
        chart_xml = zf.read("ppt/charts/chart1.xml").decode("utf-8", errors="ignore")
        slide1_rels = zf.read("ppt/slides/_rels/slide1.xml.rels").decode("utf-8", errors="ignore")

        rid2 = re.search(r'Id="rId2"[^>]*Target="([^"]+)"', slide1_rels)
        rid3 = re.search(r'Id="rId3"[^>]*Target="([^"]+)"', slide1_rels)
        assert rid2 and rid3
        media_target_1 = posixpath.normpath(f"ppt/slides/{rid2.group(1)}")
        media_target_2 = posixpath.normpath(f"ppt/slides/{rid3.group(1)}")
        media_bytes_1 = zf.read(media_target_1)
        media_bytes_2 = zf.read(media_target_2)

    assert "Template Placeholder" not in slide1_xml
    assert "placeholder cell" not in slide1_xml
    assert "caption placeholder" not in slide1_xml
    assert "Image Placeholder" not in slide1_xml
    assert "Chart Placeholder" not in chart_xml
    assert media_bytes_1.startswith(b"\x89PNG\r\n\x1a\n")
    assert media_bytes_2.startswith(b"\x89PNG\r\n\x1a\n")



def test_template_asset_provider_failure_should_hard_fail(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=Settings(
            llm_api_style="openai_chat",
            llm_base_url="https://api.example.com",
            llm_api_key="test",
            llm_model="test-model",
            llm_timeout_sec=30.0,
            llm_max_retries=2,
            llm_temperature_outline=0.3,
            llm_temperature_slide=0.6,
            slide_concurrency=2,
            slide_retry=2,
            qa_enabled=True,
            repair_rounds=2,
            asset_provider="unsplash",
            unsplash_access_key="",
            pexels_api_key="",
            asset_timeout_sec=3.0,
            asset_max_retries=1,
            generation_engine="legacy",
            debug_keep_previews=False,
            max_slide_repair_rounds=2,
        ),
    )
    client = TestClient(create_app(base_dir=tmp_path, orchestrator=orch))

    template_file = tmp_path / "semantic_template_for_fail.pptx"
    build_semantic_template_pptx(template_file)
    with template_file.open("rb") as fp:
        upload = client.post(
            "/v1/ppt/templates",
            files={"file": ("semantic_template_for_fail.pptx", fp, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    template_id = upload.json()["template_id"]

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Template Asset Fail",
            "project_id": "p-asset-fail",
            "rag_source_ids": ["r1"],
            "template_style": "default",
            "target_slide_count": 1,
            "generation_mode": "template",
            "template_id": template_id,
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"FAILED"})
    assert final["error_code"] == "TEMPLATE_ASSET_FETCH_FAILED"


def test_template_slot_mismatch_should_remove_excess_picture_groups(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    template_file = tmp_path / "excess_slot_template.pptx"
    build_excess_slot_template_pptx(template_file)

    with template_file.open("rb") as fp:
        upload = client.post(
            "/v1/ppt/templates",
            files={"file": ("excess_slot_template.pptx", fp, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    template_id = upload.json()["template_id"]

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Slot Trim",
            "project_id": "p-slot-trim",
            "rag_source_ids": ["r1"],
            "template_style": "default",
            "target_slide_count": 1,
            "generation_mode": "template",
            "template_id": template_id,
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED"})

    with ZipFile(final["pptx_path"], "r") as zf:
        slide1_xml = zf.read("ppt/slides/slide1.xml").decode("utf-8", errors="ignore")
        slide1_rels = zf.read("ppt/slides/_rels/slide1.xml.rels").decode("utf-8", errors="ignore")

    assert slide1_xml.count("<p:pic") == 2
    assert 'Id="rId4"' not in slide1_rels

def test_template_invalid_should_fail_early(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def markitdown_fail_for_template(args, cwd=None, capture_output=False, text=False, check=False, **kwargs):
        cmd = " ".join(args) if isinstance(args, (list, tuple)) else str(args)
        if "markitdown" in cmd and "template.pptx" in cmd:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="template parse error")
        return fake_subprocess_run(args, cwd=cwd, capture_output=capture_output, text=text, check=check, **kwargs)

    monkeypatch.setattr(orchestrator_mod.subprocess, "run", markitdown_fail_for_template)
    client = make_client(tmp_path)
    template_file = tmp_path / "template_invalid.pptx"
    build_template_pptx(template_file)

    with template_file.open("rb") as fp:
        upload = client.post(
            "/v1/ppt/templates",
            files={"file": ("template_invalid.pptx", fp, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert upload.status_code == 200
    template_id = upload.json()["template_id"]

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Invalid Template",
            "project_id": "p6",
            "rag_source_ids": ["r1"],
            "template_style": "default",
            "target_slide_count": 2,
            "generation_mode": "template",
            "template_id": template_id,
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"FAILED"})
    assert final["error_code"] == "TEMPLATE_MARKITDOWN_FAILED"


def test_template_unknown_placeholder_should_fail_fast_with_mapping_report(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    template_file = tmp_path / "unknown_slot_template.pptx"
    build_unknown_slot_template_pptx(template_file)

    with template_file.open("rb") as fp:
        upload = client.post(
            "/v1/ppt/templates",
            files={"file": ("unknown_slot_template.pptx", fp, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert upload.status_code == 200
    template_id = upload.json()["template_id"]

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Unknown Placeholder",
            "project_id": "p-unknown-slot",
            "rag_source_ids": ["r1"],
            "template_style": "default",
            "target_slide_count": 1,
            "generation_mode": "template",
            "template_id": template_id,
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"FAILED"})

    assert final["error_code"] == "TEMPLATE_SLOT_UNMAPPED"
    assert final["template_mapping_report"]["passed"] is False
    assert final["template_mapping_report"]["unmapped_required"]
    assert any(item.get("slot_type") == "unknown" for item in final["template_mapping_report"]["unmapped_required"])


def test_template_layout_conflict_should_fail_fast_with_layout_report(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    template_file = tmp_path / "layout_conflict_template.pptx"
    build_layout_conflict_template_pptx(template_file)

    with template_file.open("rb") as fp:
        upload = client.post(
            "/v1/ppt/templates",
            files={"file": ("layout_conflict_template.pptx", fp, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
    assert upload.status_code == 200
    template_id = upload.json()["template_id"]

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Layout Conflict",
            "project_id": "p-layout-conflict",
            "rag_source_ids": ["r1"],
            "template_style": "default",
            "target_slide_count": 1,
            "generation_mode": "template",
            "template_id": template_id,
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"FAILED"})

    assert final["error_code"] == "TEMPLATE_LAYOUT_CONFLICT"
    assert final["template_layout_report"]["slides"]
    slide_report = final["template_layout_report"]["slides"][0]
    assert slide_report["issues_after_count"] > 0
    assert slide_report["passed"] is False


def test_scratch_chart_truth_report_should_use_qualitative_fallback_without_verified_numbers(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "No Numeric Facts",
            "project_id": "p-chart-fallback",
            "rag_source_ids": ["c1", "c2"],
            "template_style": "default",
            "target_slide_count": 3,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED"})

    chart_report = final["chart_truth_report"]
    assert chart_report["slides"]
    assert all(item["has_verified_data"] is False for item in chart_report["slides"])
    assert all(item["mode"] == "qualitative_fallback" for item in chart_report["slides"])
