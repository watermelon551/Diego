from __future__ import annotations

import asyncio
import json
import re

from service.llm_client import GeneratedSlide, LLMTimeoutError, MockLLMClient, OutlineFormatError, SlideSpec
from service.models import OutlineNode


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
    async def generate_slide_spec(self, **kwargs):
        outline_node = kwargs["outline_node"]
        slide_no = int(kwargs["slide_no"])
        rag_source_ids = list(kwargs.get("rag_source_ids") or [])
        return SlideSpec(
            title=f"AGENTIC-{outline_node.title}",
            subtitle="",
            bullets=list(outline_node.bullets or [f"A{slide_no}.1", f"A{slide_no}.2"]),
            citations=rag_source_ids[:2],
            page_type=outline_node.page_type,
            layout_hint=outline_node.layout_hint,
            visual_kind="shape",
            emphasis="",
        )

    async def generate_slide(self, **kwargs):
        outline_node = kwargs["outline_node"]
        slide_no = int(kwargs["slide_no"])
        rag_source_ids = list(kwargs.get("rag_source_ids") or [])
        return GeneratedSlide(
            title=f"AGENTIC-{outline_node.title}",
            bullets=list(outline_node.bullets or [f"A{slide_no}.1", f"A{slide_no}.2"]),
            citations=rag_source_ids[:2],
            page_type=outline_node.page_type,
            layout_hint=outline_node.layout_hint,
        )

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
                "  slide.addText(slideConfig.title, { x: 0.5, y: 0.4, w: 9.0, h: 0.8, fontSize: 40, fontFace: 'Arial', color: theme.primary, bold: true, align: 'left', fit: 'shrink' });",
                "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.8, y: 1.5, w: 8.4, h: 3.5, fill: { color: theme.light, transparency: 10 }, line: { color: theme.secondary, pt: 1 } });",
                "  const rows = (slideConfig.bullets || []).map((text, idx) => ({ text, options: { bullet: true, breakLine: idx < (slideConfig.bullets || []).length - 1 } }));",
                "  slide.addText(rows, { x: 1.1, y: 1.9, w: 7.8, h: 2.7, fontSize: 16, fontFace: 'Arial', color: theme.secondary, bold: false, align: 'left', margin: 0, fit: 'shrink' });",
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
    async def generate_slide_spec(self, **kwargs):
        spec = await super().generate_slide_spec(**kwargs)
        spec.visual_kind = "image"
        return spec

    async def generate_slide_js(self, **kwargs):
        base = await super().generate_slide_js(**kwargs)
        slide_plan = kwargs.get("slide_plan") if isinstance(kwargs.get("slide_plan"), dict) else {}
        worker = int(slide_plan.get("candidate_worker", 1))
        if worker != 1:
            return base
        return base.replace(
            "  const rows = (slideConfig.bullets || []).map((text, idx) => ({ text, options: { bullet: true, breakLine: idx < (slideConfig.bullets || []).length - 1 } }));",
            "  slide.addImage({ path: 'https://example.com/fake.png', x: 6.8, y: 1.5, w: 2.2, h: 1.6 });\n"
            "  const rows = (slideConfig.bullets || []).map((text, idx) => ({ text, options: { bullet: true, breakLine: idx < (slideConfig.bullets || []).length - 1 } }));",
        )

    async def critique_slide_js(self, **kwargs):
        candidate_js = str(kwargs.get("candidate_js", ""))
        issues = [str(item).lower() for item in (kwargs.get("issues") or [])]
        if any("basic_graphics_only" in item or "forbids addimage" in item for item in issues):
            candidate_js = re.sub(
                r"(?m)^\s*slide\.addImage\(\{[^)]*\}\);\s*$",
                "",
                candidate_js,
            )
        return candidate_js


class CandidateOneFailsAgenticLLM(AgenticMockLLM):
    def __init__(self) -> None:
        self.failed_once = False

    async def generate_slide_js(self, **kwargs):
        if not self.failed_once:
            self.failed_once = True
            raise RuntimeError("simulated candidate worker failure")
        return await super().generate_slide_js(**kwargs)


class EvaluateTimeoutAgenticLLM(AgenticMockLLM):
    async def evaluate_slide_quality(self, **kwargs):
        raise LLMTimeoutError(attempts=1, reason="simulated evaluate timeout", phase="candidate.evaluate")


class AllCandidatesFailAgenticLLM(AgenticMockLLM):
    async def generate_slide(self, **kwargs):
        raise RuntimeError("simulated legacy fallback failure")

    async def generate_slide_js(self, **kwargs):
        raise RuntimeError("simulated all candidate failures")

    async def critique_slide_js(self, **kwargs):
        raise RuntimeError("simulated all candidate failures")


class MalformedOutlineThenRepairLLM(MockLLMClient):
    async def generate_outline(self, **kwargs):
        raise OutlineFormatError(
            category="parse",
            details=["model response does not contain a JSON object"],
            raw_response="```json { bad",
        )

    async def repair_outline(self, **kwargs):
        async def noop(_: str) -> None:
            return

        return await MockLLMClient.generate_outline(
            self,
            topic=kwargs["topic"],
            project_id=kwargs["project_id"],
            rag_source_ids=kwargs["rag_source_ids"],
            rag_context_snippets=kwargs.get("rag_context_snippets", []),
            template_style=kwargs["template_style"],
            target_slide_count=kwargs["target_slide_count"],
            on_token=noop,
        )


class AlwaysMalformedOutlineLLM(MockLLMClient):
    async def generate_outline(self, **kwargs):
        raise OutlineFormatError(
            category="schema",
            details=["version: Input should be a valid integer"],
            raw_response='{"version":"1.0"}',
        )

    async def repair_outline(self, **kwargs):
        raise OutlineFormatError(
            category="schema",
            details=["nodes.0.page_type: Input should be 'cover'|'toc'|'section'|'content'|'summary'"],
            raw_response='{"version":1,"summary":"x","nodes":[{"page_type":"invalid"}]}',
        )


class CritiqueMalformedThenRepairLLM(MockLLMClient):
    async def critique_outline(self, **kwargs):
        raise OutlineFormatError(
            category="parse",
            details=["model response does not contain a JSON object"],
            raw_response="```json { invalid critique",
        )


class CountingCritiqueLLM(MockLLMClient):
    def __init__(self) -> None:
        self.critique_calls = 0

    async def critique_outline(self, **kwargs):
        self.critique_calls += 1
        return await super().critique_outline(**kwargs)


class TimeoutThenSuccessOutlineLLM(MockLLMClient):
    def __init__(self, *, fail_times: int = 1) -> None:
        self.fail_times = fail_times
        self.calls = 0

    async def generate_outline(self, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise LLMTimeoutError(attempts=1, reason="simulated timeout", phase="outline.generate")
        return await super().generate_outline(**kwargs)


class AlwaysTimeoutOutlineLLM(MockLLMClient):
    async def generate_outline(self, **kwargs):
        raise LLMTimeoutError(attempts=1, reason="simulated timeout", phase="outline.generate")
