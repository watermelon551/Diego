from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from .config import Settings, load_settings
from .llm_client import GeneratedSlide, LLMClient, OpenAICompatibleLLMClient
from .models import (
    ConfirmOutlineRequest,
    CreateRunRequest,
    EventType,
    GenerationMode,
    OutlineNode,
    RunDetailResponse,
    RunEvent,
    RunRecord,
    RunStatus,
    RunSummaryResponse,
    SlideArtifact,
    SlidePageType,
    TemplateDetailResponse,
    TemplateRecord,
    TemplateUploadResponse,
)
from .skill_profile import DesignProfile, StyleRecipe, allowed_layouts_for, choose_design_profile, enforce_layout_variety
from .store import RunStore, now_iso


class RunOrchestrator:
    def __init__(
        self,
        *,
        store: RunStore,
        artifacts_base: Path,
        templates_base: Path,
        llm_client: LLMClient,
        settings: Settings,
    ) -> None:
        self.store = store
        self.artifacts_base = artifacts_base
        self.templates_base = templates_base
        self.llm_client = llm_client
        self.settings = settings
        self.slide_concurrency = max(1, settings.slide_concurrency)
        self.slide_retry = max(1, settings.slide_retry)
        self.llm_max_retries = max(1, settings.llm_max_retries)
        self.repair_rounds = max(1, settings.repair_rounds)

    def _spawn(self, coro: Any) -> None:
        def runner() -> None:
            asyncio.run(coro)

        threading.Thread(target=runner, daemon=True).start()

    async def upload_template(self, *, filename: str, content: bytes) -> TemplateUploadResponse:
        template_id = str(uuid4())
        target_dir = self.templates_base / template_id
        target_dir.mkdir(parents=True, exist_ok=True)
        sanitized_name = Path(filename).name or "template.pptx"
        template_path = target_dir / sanitized_name
        template_path.write_bytes(content)
        record = TemplateRecord(
            template_id=template_id,
            filename=sanitized_name,
            path=str(template_path),
            created_at=now_iso(),
        )
        await self.store.add_template(record)
        return TemplateUploadResponse(template_id=template_id, filename=sanitized_name)

    async def get_template_detail(self, template_id: str) -> TemplateDetailResponse | None:
        record = await self.store.get_template(template_id)
        if record is None:
            return None
        return TemplateDetailResponse(
            template_id=record.template_id,
            filename=record.filename,
            path=record.path,
            created_at=record.created_at,
        )

    async def create_run(self, req: CreateRunRequest) -> RunSummaryResponse:
        run_id = str(uuid4())
        trace_id = str(uuid4())
        artifact_dir = self.artifacts_base / run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        run = RunRecord(
            run_id=run_id,
            trace_id=trace_id,
            status=RunStatus.OUTLINE_DRAFTING,
            input=req,
            artifact_dir=str(artifact_dir),
        )
        await self.store.add_run(run)
        self._spawn(self._generate_outline(run_id))
        return RunSummaryResponse(run_id=run_id, trace_id=trace_id, status=run.status)

    async def get_run_detail(self, run_id: str) -> RunDetailResponse | None:
        run = await self.store.get_run(run_id)
        if run is None:
            return None
        return RunDetailResponse(
            run_id=run.run_id,
            trace_id=run.trace_id,
            status=run.status,
            outline=run.outline,
            slides=run.slides,
            citation_map=run.citation_map,
            stage_timings=run.stage_timings,
            error_code=run.error_code,
            failed_stage=run.failed_stage,
            retryable=run.retryable,
            compile_js_path=run.compile_js_path,
            pptx_path=run.pptx_path,
            qa_report=run.qa_report,
            events=run.events,
        )

    async def confirm_outline(self, run_id: str, req: ConfirmOutlineRequest) -> RunSummaryResponse | None:
        run = await self.store.get_run(run_id)
        if run is None:
            return None
        if run.status != RunStatus.AWAITING_OUTLINE_CONFIRM:
            raise ValueError("run is not awaiting outline confirmation")

        def apply_confirm(r: RunRecord) -> None:
            if req.outline is not None:
                r.outline = req.outline
            r.status = RunStatus.SLIDES_GENERATING

        await self.store.update_run(run_id, apply_confirm)
        self._spawn(self._execute_generation_pipeline(run_id))
        updated = await self.store.get_run(run_id)
        assert updated is not None
        return RunSummaryResponse(run_id=updated.run_id, trace_id=updated.trace_id, status=updated.status)

    async def _publish(self, run_id: str, event_type: EventType, payload: dict[str, Any]) -> None:
        run = await self.store.get_run(run_id)
        if run is None:
            return
        event = RunEvent(seq=len(run.events) + 1, event=event_type, ts=now_iso(), payload=payload)
        await self.store.append_event(run_id, event)

    async def _generate_outline(self, run_id: str) -> None:
        started = time.perf_counter()
        run = await self.store.get_run(run_id)
        if run is None:
            return
        try:
            async def on_token(token: str) -> None:
                await self._publish(run_id, EventType.OUTLINE_TOKEN, {"token": token})

            outline = await self.llm_client.generate_outline(
                topic=run.input.topic,
                project_id=run.input.project_id,
                rag_source_ids=run.input.rag_source_ids,
                template_style=run.input.template_style,
                target_slide_count=run.input.target_slide_count,
                on_token=on_token,
            )
            outline = await self.llm_client.critique_outline(
                topic=run.input.topic,
                template_style=run.input.template_style,
                target_slide_count=run.input.target_slide_count,
                outline=outline,
            )
            enforce_layout_variety(nodes=outline.nodes, seed=f"{run.input.topic}|{run.input.template_style}|{run_id}")
            design = choose_design_profile(topic=run.input.topic, template_style=run.input.template_style)

            def apply_outline(r: RunRecord) -> None:
                r.outline = outline
                r.status = RunStatus.AWAITING_OUTLINE_CONFIRM
                r.stage_timings.outline_ms = int((time.perf_counter() - started) * 1000)

            await self.store.update_run(run_id, apply_outline)
            await self._publish(run_id, EventType.OUTLINE_COMPLETED, {"version": outline.version, "sections": len(outline.nodes)})
            await self._publish(
                run_id,
                EventType.PLAN_COMPLETED,
                {
                    "sections": len(outline.nodes),
                    "palette": design.palette_name,
                    "style": design.style.name,
                    "fonts": {"title": design.title_font, "body": design.body_font},
                    "theme": design.theme,
                },
            )
        except Exception:
            await self._fail_run(run_id, "OUTLINE_DRAFTING", "OUTLINE_LLM_ERROR", retryable=True)

    async def _execute_generation_pipeline(self, run_id: str) -> None:
        run = await self.store.get_run(run_id)
        if run is None or run.outline is None:
            await self._fail_run(run_id, "SLIDES_GENERATING", "OUTLINE_MISSING", retryable=False)
            return
        try:
            if run.input.generation_mode == GenerationMode.TEMPLATE:
                await self._generate_from_template(run_id)
            else:
                await self._generate_from_scratch(run_id)
        except Exception:
            await self._fail_run(run_id, "SLIDES_GENERATING", "GENERATION_PIPELINE_ERROR", retryable=True)

    async def _generate_from_scratch(self, run_id: str) -> None:
        run = await self.store.get_run(run_id)
        assert run is not None and run.outline is not None
        design = choose_design_profile(topic=run.input.topic, template_style=run.input.template_style)

        artifact_dir = Path(run.artifact_dir)
        slides_dir = artifact_dir / "slides"
        output_dir = slides_dir / "output"
        imgs_dir = slides_dir / "imgs"
        slides_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        imgs_dir.mkdir(parents=True, exist_ok=True)

        slide_start = time.perf_counter()
        sem = asyncio.Semaphore(min(5, self.slide_concurrency))

        async def generate_one(slide_no: int, node: OutlineNode) -> None:
            async with sem:
                await self._publish(run_id, EventType.SLIDE_STARTED, {"slide_no": slide_no, "page_type": node.page_type.value})
                artifact = await self._generate_skill_slide(run_id=run_id, slide_no=slide_no, node=node, design=design)

                def apply_slide(r: RunRecord) -> None:
                    r.slides.append(artifact)
                    r.citation_map[slide_no] = artifact.citations

                await self.store.update_run(run_id, apply_slide)
                await self._publish(run_id, EventType.SLIDE_GENERATED, {"slide_no": slide_no, "status": artifact.status})

        results = await asyncio.gather(
            *(generate_one(i, node) for i, node in enumerate(run.outline.nodes, start=1)),
            return_exceptions=True,
        )
        if any(isinstance(item, Exception) for item in results):
            await self._fail_run(run_id, "SLIDES_GENERATING", "SLIDE_LLM_ERROR", retryable=True)
            return

        await self.store.update_run(
            run_id,
            lambda r: setattr(r.stage_timings, "slide_ms", int((time.perf_counter() - slide_start) * 1000)),
        )
        await self.store.update_run(run_id, lambda r: setattr(r, "status", RunStatus.COMPILING))
        await self._publish(run_id, EventType.COMPILE_STARTED, {})

        compile_start = time.perf_counter()
        run = await self.store.get_run(run_id)
        assert run is not None
        sorted_slides = sorted(run.slides, key=lambda x: x.slide_no)
        compile_js = slides_dir / "compile.js"
        compile_js.write_text(self._build_compile_script(total=len(sorted_slides), theme=design.theme), encoding="utf-8")

        compile_cmd = ["node", "compile.js"]
        result = await asyncio.to_thread(
            subprocess.run,
            compile_cmd,
            cwd=slides_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            await self._fail_run(run_id, "COMPILING", "COMPILE_SCRIPT_FAILED", retryable=True)
            return

        pptx_path = output_dir / "presentation.pptx"

        def apply_compile(r: RunRecord) -> None:
            r.compile_js_path = str(compile_js)
            r.pptx_path = str(pptx_path)
            r.stage_timings.compile_ms = int((time.perf_counter() - compile_start) * 1000)

        await self.store.update_run(run_id, apply_compile)
        await self._publish(run_id, EventType.COMPILE_COMPLETED, {"file": str(pptx_path)})

        if self.settings.qa_enabled:
            qa_ok = await self._run_skill_qa(run_id, mode=GenerationMode.SCRATCH)
            polished = await self._mandatory_polish_cycle(run_id, mode=GenerationMode.SCRATCH, design=design)
            if not polished:
                await self._fail_run(run_id, "COMPILING", "POLISH_FAILED", retryable=True)
                return
            if not qa_ok:
                repaired = await self._repair_loop(run_id, mode=GenerationMode.SCRATCH, design=design)
                if not repaired:
                    await self._fail_run(run_id, "COMPILING", "QA_FAILED", retryable=False)
                    return
            else:
                qa_ok_after_polish = await self._run_skill_qa(run_id, mode=GenerationMode.SCRATCH)
                if not qa_ok_after_polish:
                    repaired = await self._repair_loop(run_id, mode=GenerationMode.SCRATCH, design=design)
                    if not repaired:
                        await self._fail_run(run_id, "COMPILING", "QA_FAILED", retryable=False)
                        return
        await self.store.update_run(run_id, lambda r: setattr(r, "status", RunStatus.SUCCEEDED))

    async def _generate_from_template(self, run_id: str) -> None:
        run = await self.store.get_run(run_id)
        assert run is not None and run.outline is not None
        design = choose_design_profile(topic=run.input.topic, template_style=run.input.template_style)
        if not run.input.template_id:
            await self._fail_run(run_id, "SLIDES_GENERATING", "TEMPLATE_ID_MISSING", retryable=False)
            return

        template_record = await self.store.get_template(run.input.template_id)
        if template_record is None:
            await self._fail_run(run_id, "SLIDES_GENERATING", "TEMPLATE_NOT_FOUND", retryable=False)
            return

        await self.store.update_run(run_id, lambda r: setattr(r, "status", RunStatus.COMPILING))
        await self._publish(run_id, EventType.COMPILE_STARTED, {"mode": "template"})

        artifact_dir = Path(run.artifact_dir)
        template_dir = artifact_dir / "template_edit"
        unpacked = template_dir / "unpacked"
        template_dir.mkdir(parents=True, exist_ok=True)
        unpacked.mkdir(parents=True, exist_ok=True)
        src_template = Path(template_record.path)
        work_template = template_dir / "template.pptx"
        shutil.copy2(src_template, work_template)
        template_md = template_dir / "template.md"
        markitdown_template = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "markitdown", str(work_template)],
            capture_output=True,
            text=True,
            check=False,
        )
        if markitdown_template.returncode != 0:
            await self._fail_run(run_id, "SLIDES_GENERATING", "TEMPLATE_MARKITDOWN_FAILED", retryable=False)
            return
        if markitdown_template.returncode == 0 and markitdown_template.stdout:
            template_md.write_text(markitdown_template.stdout, encoding="utf-8")

        with ZipFile(work_template, "r") as zin:
            zin.extractall(unpacked)

        slide_files = self._rebuild_template_structure(unpacked=unpacked, target_count=len(run.outline.nodes))
        outline_nodes = run.outline.nodes
        for i, slide_xml in enumerate(slide_files):
            if i >= len(outline_nodes):
                break
            node = outline_nodes[i]
            self._rewrite_template_slide_text(slide_xml=slide_xml, node=node)

        edited = template_dir / "edited.pptx"
        with ZipFile(edited, "w", compression=ZIP_DEFLATED) as zout:
            for file in unpacked.rglob("*"):
                if file.is_file():
                    arc = file.relative_to(unpacked).as_posix()
                    zout.write(file, arc)

        def apply_compile(r: RunRecord) -> None:
            r.compile_js_path = None
            r.pptx_path = str(edited)
            r.stage_timings.compile_ms = 1

        await self.store.update_run(run_id, apply_compile)
        await self._publish(run_id, EventType.COMPILE_COMPLETED, {"file": str(edited), "mode": "template"})

        if self.settings.qa_enabled:
            qa_ok = await self._run_skill_qa(run_id, mode=GenerationMode.TEMPLATE)
            polished = await self._mandatory_polish_cycle(run_id, mode=GenerationMode.TEMPLATE, design=design)
            if not polished:
                await self._fail_run(run_id, "COMPILING", "POLISH_FAILED", retryable=True)
                return
            if not qa_ok:
                repaired = await self._repair_loop(run_id, mode=GenerationMode.TEMPLATE, design=design)
                if not repaired:
                    await self._fail_run(run_id, "COMPILING", "QA_FAILED", retryable=False)
                    return
        await self.store.update_run(run_id, lambda r: setattr(r, "status", RunStatus.SUCCEEDED))

    async def _generate_skill_slide(self, *, run_id: str, slide_no: int, node: OutlineNode, design: DesignProfile) -> SlideArtifact:
        run = await self.store.get_run(run_id)
        assert run is not None
        artifact_dir = Path(run.artifact_dir)
        slides_dir = artifact_dir / "slides"
        retries = 0
        while True:
            try:
                generated = await self.llm_client.generate_slide(
                    topic=run.input.topic,
                    project_id=run.input.project_id,
                    template_style=run.input.template_style,
                    slide_no=slide_no,
                    target_slide_count=run.input.target_slide_count,
                    outline_node=node,
                    rag_source_ids=run.input.rag_source_ids,
                )
                candidate = generated
                rule_violations = self._check_slide_content_rules(candidate, node)
                reviewed = await self.llm_client.review_slide(
                    topic=run.input.topic,
                    template_style=run.input.template_style,
                    slide_no=slide_no,
                    target_slide_count=run.input.target_slide_count,
                    outline_node=node,
                    candidate=candidate,
                    rule_violations=rule_violations,
                )
                await self._publish(run_id, EventType.SLIDE_REVIEWED, {"slide_no": slide_no, "violations": rule_violations})
                js_code = self._render_skill_slide_js(
                    slide_no=slide_no,
                    total=run.input.target_slide_count,
                    node=node,
                    generated=reviewed,
                    design=design,
                )
                slide_path = slides_dir / f"slide-{slide_no:02d}.js"
                slide_path.write_text(js_code, encoding="utf-8")
                citations = self._normalize_citations(reviewed.citations, run.input.rag_source_ids, slide_no)
                status = "ok" if retries == 0 else f"ok_after_retry_{retries}"
                return SlideArtifact(slide_no=slide_no, js_code=js_code, status=status, citations=citations)
            except Exception:
                retries += 1
                if retries >= self.slide_retry:
                    raise
                await asyncio.sleep(0.05 * retries)

    def _render_skill_slide_js(
        self,
        *,
        slide_no: int,
        total: int,
        node: OutlineNode,
        generated: GeneratedSlide,
        design: DesignProfile,
    ) -> str:
        page_type = node.page_type
        title = json.dumps(generated.title, ensure_ascii=False)
        bullets_literal = json.dumps(generated.bullets, ensure_ascii=False)
        selected_layout = generated.layout_hint or node.layout_hint or "content-two-column"
        layout_hint = json.dumps(selected_layout, ensure_ascii=False)
        badge = self._build_page_badge_js(slide_no=slide_no, style=design.style) if page_type != SlidePageType.COVER else ""
        content_block = self._slide_content_block(
            page_type=page_type,
            layout_hint=selected_layout,
            style=design.style,
        )
        preview_theme = self._theme_js_literal(design.theme)
        return "\n".join(
            [
                "const pptxgen = require('pptxgenjs');",
                "",
                "const slideConfig = {",
                f"  type: {json.dumps(page_type.value)},",
                f"  index: {slide_no},",
                f"  total: {total},",
                f"  title: {title},",
                f"  layoutHint: {layout_hint},",
                f"  bullets: {bullets_literal},",
                "};",
                "",
                f"const fonts = {{ title: {json.dumps(design.title_font)}, body: {json.dumps(design.body_font)} }};",
                f"const style = {{ cornerSmall: {design.style.corner_small}, cornerMedium: {design.style.corner_medium}, cornerLarge: {design.style.corner_large}, pageMargin: {design.style.page_margin}, blockGap: {design.style.block_gap}, elementGap: {design.style.element_gap}, badgePill: {str(design.style.badge_pill).lower()} }};",
                "",
                "function addBulletList(slide, items, opts, theme) {",
                "  const maxItems = opts.maxItems || 6;",
                "  const prepared = (items || []).map((x) => String(x || '').trim()).filter(Boolean).slice(0, maxItems);",
                "  const payload = prepared.length ? prepared : ['Key point'];",
                "  const rows = payload.map((item, idx) => ({ text: item, options: { bullet: true, breakLine: idx < payload.length - 1 } }));",
                "  slide.addText(rows, { x: opts.x, y: opts.y, w: opts.w, h: opts.h, fontSize: opts.fontSize || 15, fontFace: fonts.body, color: opts.color || theme.secondary, bold: false, align: 'left', margin: 0, paraSpaceAfterPt: 7, fit: 'shrink' });",
                "}",
                "",
                "function addPageBadge(pres, slide, theme, n) {",
                "  if (style.badgePill) {",
                "    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 9.3, y: 5.1, w: 0.45, h: 0.32, fill: { color: theme.accent }, line: { color: theme.accent }, rectRadius: 0.15 });",
                "    slide.addText(String(n).padStart(2, '0'), { x: 9.3, y: 5.1, w: 0.45, h: 0.32, fontSize: 10, fontFace: fonts.body, color: 'FFFFFF', bold: true, align: 'center', valign: 'mid', margin: 0 });",
                "    return;",
                "  }",
                "  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.accent }, line: { color: theme.accent } });",
                "  slide.addText(String(n), { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 10, fontFace: fonts.body, color: 'FFFFFF', bold: true, align: 'center', valign: 'mid', margin: 0 });",
                "}",
                "",
                "function createSlide(pres, theme) {",
                "  const slide = pres.addSlide();",
                "  const bullets = Array.isArray(slideConfig.bullets) ? slideConfig.bullets : [];",
                "  slide.background = { color: theme.bg };",
                "  const titleSize = slideConfig.type === 'cover' ? 56 : (slideConfig.type === 'section' ? 46 : (slideConfig.type === 'summary' ? 42 : 38));",
                "  const titleAlign = slideConfig.type === 'cover' && slideConfig.layoutHint === 'cover-center' ? 'center' : 'left';",
                "  slide.addText(slideConfig.title, { x: style.pageMargin, y: 0.28, w: 10 - style.pageMargin * 2, h: 0.82, fontSize: titleSize, fontFace: fonts.title, color: theme.primary, bold: true, margin: 0, align: titleAlign, fit: 'shrink' });",
                content_block,
                badge,
                "  return slide;",
                "}",
                "",
                "if (require.main === module) {",
                "  const pres = new pptxgen();",
                "  pres.layout = 'LAYOUT_16x9';",
                f"  const theme = {preview_theme};",
                "  createSlide(pres, theme);",
                f"  pres.writeFile({{ fileName: 'slide-{slide_no:02d}-preview.pptx' }});",
                "}",
                "",
                "module.exports = { createSlide, slideConfig };",
            ]
        )

    def _slide_content_block(self, *, page_type: SlidePageType, layout_hint: str, style: StyleRecipe) -> str:
        if page_type == SlidePageType.COVER:
            return self._slide_block_cover(layout_hint)
        if page_type == SlidePageType.TOC:
            return self._slide_block_toc(layout_hint)
        if page_type == SlidePageType.SECTION:
            return self._slide_block_section(layout_hint)
        if page_type == SlidePageType.SUMMARY:
            return self._slide_block_summary(layout_hint)
        return self._slide_block_content(layout_hint)

    def _build_page_badge_js(self, *, slide_no: int, style: StyleRecipe) -> str:
        return f"  addPageBadge(pres, slide, theme, {slide_no});"

    def _build_compile_script(self, *, total: int, theme: dict[str, str]) -> str:
        return "\n".join(
            [
                "const pptxgen = require('pptxgenjs');",
                "const pres = new pptxgen();",
                "pres.layout = 'LAYOUT_16x9';",
                f"const theme = {self._theme_js_literal(theme)};",
                "",
                f"for (let i = 1; i <= {total}; i++) {{",
                "  const num = String(i).padStart(2, '0');",
                "  const mod = require(`./slide-${num}.js`);",
                "  mod.createSlide(pres, theme);",
                "}",
                "",
                "pres.writeFile({ fileName: './output/presentation.pptx' });",
            ]
        )

    def _theme_js_literal(self, theme: dict[str, str]) -> str:
        safe = {k: v.replace("#", "") for k, v in theme.items()}
        return "{ " + ", ".join(f"{k}: '{safe[k]}'" for k in ("primary", "secondary", "accent", "light", "bg")) + " }"

    def _slide_block_cover(self, layout_hint: str) -> str:
        if layout_hint == "cover-center":
            return "\n".join(
                [
                    "  slide.addShape(pres.shapes.RECTANGLE, { x: 0.0, y: 1.35, w: 10.0, h: 2.95, fill: { color: theme.light, transparency: 18 }, line: { color: theme.light } });",
                    "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 2.1, y: 1.75, w: 5.8, h: 1.9, fill: { color: theme.bg, transparency: 8 }, line: { color: theme.secondary }, rectRadius: style.cornerLarge });",
                    "  slide.addText((bullets[0] || 'Presentation opening statement').slice(0, 120), { x: 2.4, y: 2.4, w: 5.2, h: 0.7, fontSize: 22, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'center', margin: 0, fit: 'shrink' });",
                ]
            )
        return "\n".join(
            [
                "  slide.addShape(pres.shapes.RECTANGLE, { x: 5.3, y: 0.0, w: 4.7, h: 5.625, fill: { color: theme.light, transparency: 14 }, line: { color: theme.light } });",
                "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.7, y: 1.4, w: 4.5, h: 2.5, fill: { color: theme.primary, transparency: 10 }, line: { color: theme.primary }, rectRadius: style.cornerLarge });",
                "  slide.addText((bullets[0] || 'Audience, objective, and context').slice(0, 120), { x: 0.95, y: 3.15, w: 4.05, h: 0.75, fontSize: 20, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'left', margin: 0, fit: 'shrink' });",
            ]
        )

    def _slide_block_toc(self, layout_hint: str) -> str:
        if layout_hint == "toc-grid":
            return "\n".join(
                [
                    "  const items = bullets.slice(0, 6);",
                    "  items.forEach((item, idx) => {",
                    "    const col = idx % 2;",
                    "    const row = Math.floor(idx / 2);",
                    "    const x = 0.8 + col * 4.5;",
                    "    const y = 1.3 + row * 1.2;",
                    "    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 4.0, h: 0.95, fill: { color: theme.light, transparency: 12 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                    "    slide.addText(String(idx + 1).padStart(2, '0'), { x: x + 0.2, y: y + 0.2, w: 0.7, h: 0.5, fontSize: 20, fontFace: fonts.title, color: theme.accent, bold: true, margin: 0 });",
                    "    slide.addText(item, { x: x + 1.0, y: y + 0.24, w: 2.8, h: 0.48, fontSize: 16, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'left', margin: 0, fit: 'shrink' });",
                    "  });",
                ]
            )
        if layout_hint == "toc-sidebar":
            return "\n".join(
                [
                    "  const items = bullets.slice(0, 5);",
                    "  slide.addShape(pres.shapes.RECTANGLE, { x: 0.55, y: 1.2, w: 1.0, h: 3.8, fill: { color: theme.primary, transparency: 8 }, line: { color: theme.primary } });",
                    "  items.forEach((item, idx) => {",
                    "    const y = 1.4 + idx * 0.72;",
                    "    slide.addShape(pres.shapes.OVAL, { x: 0.85, y: y + 0.1, w: 0.3, h: 0.3, fill: { color: theme.accent }, line: { color: theme.accent } });",
                    "    slide.addText(String(idx + 1), { x: 0.85, y: y + 0.1, w: 0.3, h: 0.3, fontSize: 11, fontFace: fonts.body, color: 'FFFFFF', bold: true, align: 'center', valign: 'mid', margin: 0 });",
                    "    slide.addText(item, { x: 1.8, y, w: 7.7, h: 0.44, fontSize: 18, fontFace: fonts.body, color: theme.secondary, bold: false, margin: 0, fit: 'shrink' });",
                    "  });",
                ]
            )
        if layout_hint == "toc-cards":
            return "\n".join(
                [
                    "  const items = bullets.slice(0, 4);",
                    "  items.forEach((item, idx) => {",
                    "    const x = 0.8 + idx * 2.25;",
                    "    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 2.0, w: 2.0, h: 1.7, fill: { color: theme.light, transparency: 10 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerLarge });",
                    "    slide.addText(String(idx + 1).padStart(2, '0'), { x: x + 0.1, y: 2.18, w: 1.8, h: 0.48, fontSize: 28, fontFace: fonts.title, color: theme.accent, bold: true, align: 'center', margin: 0 });",
                    "    slide.addText(item, { x: x + 0.15, y: 2.72, w: 1.7, h: 0.8, fontSize: 13, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'center', margin: 0, fit: 'shrink' });",
                    "  });",
                ]
            )
        return "\n".join(
            [
                "  const items = bullets.slice(0, 6);",
                "  items.forEach((item, idx) => {",
                "    const y = 1.35 + idx * 0.6;",
                "    slide.addText(String(idx + 1).padStart(2, '0'), { x: 0.9, y, w: 0.8, h: 0.45, fontSize: 24, fontFace: fonts.title, color: theme.accent, bold: true, margin: 0 });",
                "    slide.addText(item, { x: 1.9, y: y + 0.03, w: 7.6, h: 0.42, fontSize: 17, fontFace: fonts.body, color: theme.secondary, bold: false, margin: 0, fit: 'shrink' });",
                "  });",
            ]
        )

    def _slide_block_section(self, layout_hint: str) -> str:
        if layout_hint == "section-accent-block":
            return "\n".join(
                [
                    "  slide.addShape(pres.shapes.RECTANGLE, { x: 0.0, y: 1.1, w: 1.4, h: 3.8, fill: { color: theme.primary }, line: { color: theme.primary } });",
                    "  slide.addText(String(slideConfig.index).padStart(2, '0'), { x: 1.75, y: 1.8, w: 2.4, h: 1.1, fontSize: 86, fontFace: fonts.title, color: theme.accent, bold: true, margin: 0 });",
                    "  slide.addText((bullets[0] || 'Section transition').slice(0, 100), { x: 1.9, y: 3.25, w: 6.8, h: 0.55, fontSize: 18, fontFace: fonts.body, color: theme.secondary, bold: false, margin: 0, fit: 'shrink' });",
                ]
            )
        if layout_hint == "section-split":
            return "\n".join(
                [
                    "  slide.addShape(pres.shapes.RECTANGLE, { x: 0.0, y: 1.2, w: 4.8, h: 3.6, fill: { color: theme.primary, transparency: 10 }, line: { color: theme.primary } });",
                    "  slide.addShape(pres.shapes.RECTANGLE, { x: 4.8, y: 1.2, w: 5.2, h: 3.6, fill: { color: theme.light, transparency: 12 }, line: { color: theme.light } });",
                    "  slide.addText(String(slideConfig.index).padStart(2, '0'), { x: 1.25, y: 2.05, w: 2.6, h: 1.2, fontSize: 96, fontFace: fonts.title, color: theme.bg, bold: true, align: 'center', margin: 0 });",
                    "  slide.addText((bullets[0] || 'Context and objective').slice(0, 120), { x: 5.2, y: 2.35, w: 4.2, h: 0.9, fontSize: 20, fontFace: fonts.body, color: theme.secondary, bold: false, margin: 0, fit: 'shrink' });",
                ]
            )
        return "\n".join(
            [
                "  slide.addText(String(slideConfig.index).padStart(2, '0'), { x: 3.8, y: 1.3, w: 2.4, h: 1.4, fontSize: 96, fontFace: fonts.title, color: theme.accent, bold: true, align: 'center', margin: 0 });",
                "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 2.2, y: 2.95, w: 5.6, h: 1.3, fill: { color: theme.light, transparency: 10 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerLarge });",
                "  slide.addText((bullets[0] || 'Transition summary').slice(0, 120), { x: 2.5, y: 3.28, w: 5.0, h: 0.66, fontSize: 19, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'center', margin: 0, fit: 'shrink' });",
            ]
        )

    def _slide_block_content(self, layout_hint: str) -> str:
        if layout_hint == "content-icon-rows":
            return "\n".join(
                [
                    "  bullets.slice(0, 5).forEach((item, idx) => {",
                    "    const y = 1.35 + idx * 0.72;",
                    "    slide.addShape(pres.shapes.OVAL, { x: 0.85, y: y + 0.08, w: 0.32, h: 0.32, fill: { color: theme.accent }, line: { color: theme.accent } });",
                    "    slide.addText(String(idx + 1), { x: 0.85, y: y + 0.08, w: 0.32, h: 0.32, fontSize: 11, fontFace: fonts.body, color: 'FFFFFF', bold: true, align: 'center', valign: 'mid', margin: 0 });",
                    "    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 1.35, y, w: 8.0, h: 0.52, fill: { color: theme.light, transparency: 11 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerSmall });",
                    "    slide.addText(item, { x: 1.58, y: y + 0.11, w: 7.5, h: 0.35, fontSize: 15, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'left', margin: 0, fit: 'shrink' });",
                    "  });",
                ]
            )
        if layout_hint == "content-comparison":
            return "\n".join(
                [
                    "  const left = bullets.filter((_, idx) => idx % 2 === 0).slice(0, 3);",
                    "  const right = bullets.filter((_, idx) => idx % 2 === 1).slice(0, 3);",
                    "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.8, y: 1.25, w: 4.1, h: 3.7, fill: { color: theme.light, transparency: 12 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                    "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 5.1, y: 1.25, w: 4.1, h: 3.7, fill: { color: theme.bg }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                    "  slide.addText('Track A', { x: 1.1, y: 1.53, w: 3.3, h: 0.45, fontSize: 20, fontFace: fonts.title, color: theme.primary, bold: true, margin: 0 });",
                    "  slide.addText('Track B', { x: 5.4, y: 1.53, w: 3.3, h: 0.45, fontSize: 20, fontFace: fonts.title, color: theme.primary, bold: true, margin: 0 });",
                    "  addBulletList(slide, left, { x: 1.1, y: 2.05, w: 3.5, h: 2.7, maxItems: 3, fontSize: 14 }, theme);",
                    "  addBulletList(slide, right, { x: 5.4, y: 2.05, w: 3.5, h: 2.7, maxItems: 3, fontSize: 14 }, theme);",
                ]
            )
        if layout_hint == "content-timeline":
            return "\n".join(
                [
                    "  const steps = bullets.slice(0, 5);",
                    "  slide.addShape(pres.shapes.LINE, { x: 1.0, y: 2.45, w: 8.0, h: 0, line: { color: theme.secondary, pt: 1 } });",
                    "  steps.forEach((item, idx) => {",
                    "    const x = 1.0 + idx * (8.0 / Math.max(steps.length - 1, 1));",
                    "    slide.addShape(pres.shapes.OVAL, { x: x - 0.16, y: 2.27, w: 0.32, h: 0.32, fill: { color: theme.accent }, line: { color: theme.accent } });",
                    "    slide.addText(String(idx + 1), { x: x - 0.16, y: 2.27, w: 0.32, h: 0.32, fontSize: 10, fontFace: fonts.body, color: 'FFFFFF', bold: true, align: 'center', valign: 'mid', margin: 0 });",
                    "    slide.addText(item, { x: x - 0.7, y: 2.7, w: 1.4, h: 0.8, fontSize: 12, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'center', margin: 0, fit: 'shrink' });",
                    "  });",
                ]
            )
        if layout_hint == "content-stat-callout":
            return "\n".join(
                [
                    "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.8, y: 1.25, w: 3.6, h: 3.75, fill: { color: theme.primary, transparency: 6 }, line: { color: theme.primary }, rectRadius: style.cornerLarge });",
                    "  slide.addText(String((slideConfig.index * 7) % 89 + 11), { x: 1.2, y: 2.08, w: 2.8, h: 1.2, fontSize: 76, fontFace: fonts.title, color: theme.bg, bold: true, align: 'center', margin: 0 });",
                    "  slide.addText('Key Metric', { x: 1.3, y: 3.35, w: 2.6, h: 0.45, fontSize: 16, fontFace: fonts.body, color: theme.bg, bold: false, align: 'center', margin: 0 });",
                    "  addBulletList(slide, bullets.slice(0, 5), { x: 4.9, y: 1.45, w: 4.2, h: 3.4, maxItems: 5, fontSize: 14 }, theme);",
                ]
            )
        if layout_hint == "content-showcase":
            return "\n".join(
                [
                    "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.8, y: 1.25, w: 8.4, h: 2.55, fill: { color: theme.light, transparency: 6 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                    "  slide.addText('Visual showcase area', { x: 1.1, y: 2.35, w: 7.8, h: 0.4, fontSize: 14, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'center', margin: 0 });",
                    "  addBulletList(slide, bullets.slice(0, 3), { x: 1.1, y: 4.02, w: 7.8, h: 0.95, maxItems: 3, fontSize: 13 }, theme);",
                ]
            )
        return "\n".join(
            [
                "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.7, y: 1.25, w: 4.2, h: 3.75, fill: { color: theme.light, transparency: 12 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 5.1, y: 1.25, w: 4.2, h: 3.75, fill: { color: theme.bg }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                "  slide.addText('Visual', { x: 1.0, y: 2.9, w: 3.5, h: 0.45, fontSize: 18, fontFace: fonts.title, color: theme.primary, bold: true, align: 'center', margin: 0 });",
                "  addBulletList(slide, bullets.slice(0, 6), { x: 5.35, y: 1.6, w: 3.75, h: 3.1, maxItems: 6, fontSize: 14 }, theme);",
            ]
        )

    def _slide_block_summary(self, layout_hint: str) -> str:
        if layout_hint == "summary-cta":
            return "\n".join(
                [
                    "  const items = bullets.slice(0, 4);",
                    "  items.forEach((item, idx) => {",
                    "    const y = 1.35 + idx * 0.82;",
                    "    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.9, y, w: 8.2, h: 0.62, fill: { color: theme.light, transparency: 12 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                    "    slide.addText(String(idx + 1), { x: 1.1, y: y + 0.14, w: 0.5, h: 0.32, fontSize: 14, fontFace: fonts.title, color: theme.accent, bold: true, margin: 0 });",
                    "    slide.addText(item, { x: 1.8, y: y + 0.12, w: 6.9, h: 0.38, fontSize: 16, fontFace: fonts.body, color: theme.secondary, bold: false, margin: 0, fit: 'shrink' });",
                    "  });",
                ]
            )
        if layout_hint == "summary-thankyou":
            return "\n".join(
                [
                    "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 1.8, y: 1.6, w: 6.4, h: 2.5, fill: { color: theme.light, transparency: 8 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerLarge });",
                    "  slide.addText((bullets[0] || 'Thank you for your attention').slice(0, 120), { x: 2.2, y: 2.35, w: 5.6, h: 0.65, fontSize: 24, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'center', margin: 0, fit: 'shrink' });",
                    "  slide.addText((bullets[1] || 'Contact details and next steps').slice(0, 120), { x: 2.2, y: 3.08, w: 5.6, h: 0.45, fontSize: 16, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'center', margin: 0, fit: 'shrink' });",
                ]
            )
        if layout_hint == "summary-split":
            return "\n".join(
                [
                    "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.7, y: 1.25, w: 4.2, h: 3.75, fill: { color: theme.light, transparency: 10 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                    "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 5.1, y: 1.25, w: 4.2, h: 3.75, fill: { color: theme.bg }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                    "  slide.addText('Summary', { x: 1.0, y: 1.5, w: 3.6, h: 0.45, fontSize: 22, fontFace: fonts.title, color: theme.primary, bold: true, margin: 0 });",
                    "  slide.addText('Next Steps', { x: 5.4, y: 1.5, w: 3.6, h: 0.45, fontSize: 22, fontFace: fonts.title, color: theme.primary, bold: true, margin: 0 });",
                    "  addBulletList(slide, bullets.slice(0, 3), { x: 1.0, y: 2.05, w: 3.3, h: 2.6, maxItems: 3, fontSize: 14 }, theme);",
                    "  addBulletList(slide, bullets.slice(3, 6), { x: 5.4, y: 2.05, w: 3.3, h: 2.6, maxItems: 3, fontSize: 14 }, theme);",
                ]
            )
        return "\n".join(
            [
                "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.7, y: 1.25, w: 8.6, h: 3.8, fill: { color: theme.light, transparency: 9 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                "  addBulletList(slide, bullets.slice(0, 5), { x: 1.0, y: 1.68, w: 8.0, h: 2.95, maxItems: 5, fontSize: 17 }, theme);",
            ]
        )

    async def _run_skill_qa(self, run_id: str, *, mode: GenerationMode) -> bool:
        run = await self.store.get_run(run_id)
        assert run is not None
        artifact_dir = Path(run.artifact_dir)
        issues: list[str] = []
        verification_cycles = int(run.qa_report.get("verification_cycles", 0))
        if mode == GenerationMode.SCRATCH:
            slides_dir = artifact_dir / "slides"
            slide_files = sorted(slides_dir.glob("slide-*.js"))
            if not slide_files:
                issues.append("no slide js files generated")
            observed_layouts: list[str] = []
            for idx, path in enumerate(slide_files, start=1):
                text = path.read_text(encoding="utf-8")
                if "module.exports = { createSlide, slideConfig };" not in text:
                    issues.append(f"{path.name}: missing export contract")
                if "function createSlide(pres, theme)" not in text:
                    issues.append(f"{path.name}: createSlide signature invalid")
                if "async function createSlide" in text:
                    issues.append(f"{path.name}: createSlide must be synchronous")
                if re.search(r"['\"]#[0-9a-fA-F]{3,8}['\"]", text):
                    issues.append(f"{path.name}: hex color with # is forbidden")
                if re.search(r"['\"][0-9a-fA-F]{8}['\"]", text):
                    issues.append(f"{path.name}: 8-char hex color is forbidden")
                if idx > 1 and ("addPageBadge(pres, slide, theme" not in text or "x: 9.3, y: 5.1" not in text):
                    issues.append(f"{path.name}: missing required page badge position")
                theme_hits = sum(1 for key in ("theme.primary", "theme.secondary", "theme.accent", "theme.light", "theme.bg") if key in text)
                if "theme.primary" not in text or "theme.bg" not in text or theme_hits < 4:
                    issues.append(f"{path.name}: theme key usage incomplete")
                if any(char in text for char in ("•", "✓", "▪", "◦")):
                    issues.append(f"{path.name}: unicode bullet symbol detected")
                if re.search(r"addShape\(pres\.shapes\.LINE,[^\n]*y:\s*1\.[0-3]", text):
                    issues.append(f"{path.name}: title accent line pattern detected")
                type_match = re.search(r"type:\s*['\"]([^'\"]+)['\"]", text)
                page_type = type_match.group(1) if type_match else ""
                if page_type == "content" and all(token not in text for token in ("addShape(", "addImage(", "addChart(")):
                    issues.append(f"{path.name}: content slide missing non-text visual element")
                layout_match = re.search(r"layoutHint:\s*['\"]([^'\"]+)['\"]", text)
                if layout_match:
                    observed_layouts.append(layout_match.group(1))
            for i in range(1, len(observed_layouts)):
                if observed_layouts[i] == observed_layouts[i - 1]:
                    issues.append(f"adjacent layout repetition: {observed_layouts[i]}")
                    break
            if run.pptx_path:
                markitdown_ok, extract_issue = await self._markitdown_check(Path(run.pptx_path))
                if not markitdown_ok and extract_issue:
                    issues.append(extract_issue)
            else:
                issues.append("scratch mode output pptx missing")
        else:
            if not run.pptx_path or not Path(run.pptx_path).exists():
                issues.append("template mode output pptx missing")
            else:
                markitdown_ok, extract_issue = await self._markitdown_check(Path(run.pptx_path))
                if not markitdown_ok and extract_issue:
                    issues.append(extract_issue)

        report = {"passed": not issues, "issues": issues, "verification_cycles": verification_cycles}
        await self.store.update_run(run_id, lambda r: setattr(r, "qa_report", report))
        await self._publish(run_id, EventType.QA_COMPLETED, report)
        return not issues

    async def _markitdown_check(self, pptx_path: Path) -> tuple[bool, str | None]:
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "markitdown", str(pptx_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False, "markitdown qa failed"
        text = (result.stdout or "").strip()
        lowered = text.lower()
        if re.search(r"(xxxx|lorem|ipsum|placeholder|todo|this.*(page|slide).*layout)", lowered):
            return False, "markitdown detected placeholder text"
        if len(text) < 20:
            return False, "markitdown extracted too little content"
        return True, None

    async def _mandatory_polish_cycle(self, run_id: str, *, mode: GenerationMode, design: DesignProfile) -> bool:
        await self._publish(run_id, EventType.REPAIR_STARTED, {"round": 0, "mode": mode.value, "reason": "mandatory_verify_cycle"})
        run = await self.store.get_run(run_id)
        if run is None:
            return False
        if mode == GenerationMode.SCRATCH:
            revised = await self._revise_scratch_slides(
                run_id=run_id,
                design=design,
                forced_issues=["mandatory polish cycle"],
            )
            if not revised:
                return False
            compiled = await self._compile_scratch_slides(run_id)
            if not compiled:
                return False
        qa_ok = await self._run_skill_qa(run_id, mode=mode)

        def apply_cycle(r: RunRecord) -> None:
            cycles = int(r.qa_report.get("verification_cycles", 0))
            r.qa_report["verification_cycles"] = cycles + 1

        await self.store.update_run(run_id, apply_cycle)
        return qa_ok

    async def _repair_loop(self, run_id: str, *, mode: GenerationMode, design: DesignProfile) -> bool:
        for repair_round in range(1, self.repair_rounds + 1):
            await self._publish(run_id, EventType.REPAIR_STARTED, {"round": repair_round, "mode": mode.value})
            if mode == GenerationMode.SCRATCH:
                revised = await self._revise_scratch_slides(
                    run_id=run_id,
                    design=design,
                    forced_issues=None,
                )
                if not revised:
                    continue
                compiled = await self._compile_scratch_slides(run_id)
                if not compiled:
                    continue
            qa_ok = await self._run_skill_qa(run_id, mode=mode)
            if qa_ok:
                return True
        return False

    async def _compile_scratch_slides(self, run_id: str) -> bool:
        run = await self.store.get_run(run_id)
        if run is None:
            return False
        compile_res = await asyncio.to_thread(
            subprocess.run,
            ["node", "compile.js"],
            cwd=Path(run.artifact_dir) / "slides",
            capture_output=True,
            text=True,
            check=False,
        )
        return compile_res.returncode == 0

    async def _revise_scratch_slides(
        self,
        *,
        run_id: str,
        design: DesignProfile,
        forced_issues: list[str] | None,
    ) -> bool:
        run = await self.store.get_run(run_id)
        if run is None or run.outline is None:
            return False
        for slide in sorted(run.slides, key=lambda x: x.slide_no):
            node = run.outline.nodes[slide.slide_no - 1]
            reviewed = await self.llm_client.review_slide(
                topic=run.input.topic,
                template_style=run.input.template_style,
                slide_no=slide.slide_no,
                target_slide_count=run.input.target_slide_count,
                outline_node=node,
                candidate=GeneratedSlide(
                    title=node.title,
                    bullets=node.bullets,
                    citations=slide.citations,
                    page_type=node.page_type,
                    layout_hint=node.layout_hint,
                ),
                rule_violations=forced_issues or run.qa_report.get("issues", []),
            )
            fixed_js = self._render_skill_slide_js(
                slide_no=slide.slide_no,
                total=run.input.target_slide_count,
                node=node,
                generated=reviewed,
                design=design,
            )
            slide_path = Path(run.artifact_dir) / "slides" / f"slide-{slide.slide_no:02d}.js"
            slide_path.write_text(fixed_js, encoding="utf-8")
            slide.js_code = fixed_js
        return True

    async def _fail_run(self, run_id: str, stage: str, error_code: str, retryable: bool) -> None:
        def apply_fail(r: RunRecord) -> None:
            r.status = RunStatus.FAILED
            r.error_code = error_code
            r.failed_stage = stage
            r.retryable = retryable

        await self.store.update_run(run_id, apply_fail)
        await self._publish(
            run_id,
            EventType.RUN_FAILED,
            {"error_code": error_code, "failed_stage": stage, "retryable": retryable},
        )

    def _check_slide_content_rules(self, candidate: GeneratedSlide, node: OutlineNode) -> list[str]:
        issues: list[str] = []
        if not candidate.title.strip():
            issues.append("title is empty")
        if len(candidate.bullets) < 2 and node.page_type in {SlidePageType.CONTENT, SlidePageType.SUMMARY, SlidePageType.TOC}:
            issues.append("not enough bullet points")
        if candidate.page_type != node.page_type:
            issues.append(f"page_type mismatch expected={node.page_type.value} got={candidate.page_type.value}")
        allowed_layouts = allowed_layouts_for(node.page_type)
        if candidate.layout_hint and candidate.layout_hint not in allowed_layouts:
            issues.append(
                f"layout_hint invalid for {node.page_type.value}: {candidate.layout_hint}"
            )
        return issues

    def _normalize_citations(self, citations: list[str], rag_source_ids: list[str], slide_no: int) -> list[str]:
        normalized = [item for item in citations if item]
        if normalized:
            return list(dict.fromkeys(normalized))
        if not rag_source_ids:
            return []
        first = rag_source_ids[(slide_no - 1) % len(rag_source_ids)]
        second = rag_source_ids[slide_no % len(rag_source_ids)] if len(rag_source_ids) > 1 else first
        return list(dict.fromkeys([first, second]))

    def _rebuild_template_structure(self, *, unpacked: Path, target_count: int) -> list[Path]:
        self._ensure_template_structure_files(unpacked=unpacked)
        slides_dir = unpacked / "ppt" / "slides"
        slide_rels_dir = slides_dir / "_rels"
        presentation_path = unpacked / "ppt" / "presentation.xml"
        presentation_rels_path = unpacked / "ppt" / "_rels" / "presentation.xml.rels"
        content_types_path = unpacked / "[Content_Types].xml"

        presentation_text = presentation_path.read_text(encoding="utf-8", errors="ignore")
        presentation_rels_text = presentation_rels_path.read_text(encoding="utf-8", errors="ignore")
        content_types_text = content_types_path.read_text(encoding="utf-8", errors="ignore")

        existing_order = self._resolve_slide_targets_from_relationships(
            presentation_text=presentation_text,
            presentation_rels_text=presentation_rels_text,
        )
        if not existing_order:
            existing_order = sorted(
                [p.relative_to(unpacked / "ppt").as_posix() for p in slides_dir.glob("slide*.xml")],
                key=self._slide_target_sort_key,
            )
        if not existing_order:
            existing_order = ["slides/slide1.xml"]
            self._write_default_slide_xml(slides_dir / "slide1.xml")

        target_count = max(1, target_count)
        mapped_sources = [existing_order[i % len(existing_order)] for i in range(target_count)]
        final_targets = [f"slides/slide{i}.xml" for i in range(1, target_count + 1)]

        used_source_files: set[str] = set()
        for i, src_target in enumerate(mapped_sources, start=1):
            src_path = unpacked / "ppt" / src_target
            if not src_path.exists():
                self._write_default_slide_xml(src_path)
            dst_rel = f"slides/slide{i}.xml"
            dst_path = unpacked / "ppt" / dst_rel
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            if src_path.resolve() == dst_path.resolve() and src_target not in used_source_files:
                used_source_files.add(src_target)
            else:
                shutil.copy2(src_path, dst_path)
                used_source_files.add(src_target)

            src_rel = slide_rels_dir / f"{Path(src_target).stem}.xml.rels"
            dst_rel_file = slide_rels_dir / f"slide{i}.xml.rels"
            if src_rel.exists():
                shutil.copy2(src_rel, dst_rel_file)
            else:
                dst_rel_file.unlink(missing_ok=True)

        self._cleanup_orphan_slide_files(slides_dir=slides_dir, keep_targets=set(final_targets))
        self._cleanup_orphan_slide_rels(slide_rels_dir=slide_rels_dir, keep_slide_numbers=set(range(1, target_count + 1)))

        updated_rels, rid_sequence = self._rebuild_presentation_relationships(
            rels_text=presentation_rels_text,
            final_targets=final_targets,
        )
        updated_presentation = self._rebuild_presentation_slide_list(
            presentation_text=presentation_text,
            rid_sequence=rid_sequence,
        )
        updated_content_types = self._rebuild_content_types_overrides(
            content_types_text=content_types_text,
            final_targets=final_targets,
        )

        presentation_rels_path.write_text(updated_rels, encoding="utf-8")
        presentation_path.write_text(updated_presentation, encoding="utf-8")
        content_types_path.write_text(updated_content_types, encoding="utf-8")
        return [unpacked / "ppt" / target for target in final_targets]

    def _resolve_slide_targets_from_relationships(self, *, presentation_text: str, presentation_rels_text: str) -> list[str]:
        rid_to_target: dict[str, str] = {}
        for tag in re.findall(r"<Relationship\b[^>]*/>", presentation_rels_text):
            attrs = self._parse_xml_attrs(tag)
            rel_type = attrs.get("Type", "")
            target = attrs.get("Target", "").replace("\\", "/")
            if rel_type.endswith("/slide") and target.startswith("slides/"):
                rid_to_target[attrs.get("Id", "")] = target
        ordered: list[str] = []
        for rid in re.findall(r'r:id="([^"]+)"', presentation_text):
            target = rid_to_target.get(rid)
            if target:
                ordered.append(target)
        return ordered

    def _rebuild_presentation_relationships(self, *, rels_text: str, final_targets: list[str]) -> tuple[str, list[str]]:
        relationship_tags = re.findall(r"<Relationship\b[^>]*/>", rels_text)
        non_slide_tags: list[str] = []
        used_ids: set[str] = set()
        for tag in relationship_tags:
            attrs = self._parse_xml_attrs(tag)
            rel_type = attrs.get("Type", "")
            rel_id = attrs.get("Id", "")
            if rel_id:
                used_ids.add(rel_id)
            if rel_type.endswith("/slide"):
                continue
            non_slide_tags.append(tag)

        rid_sequence: list[str] = []
        slide_tags: list[str] = []
        for target in final_targets:
            rid = self._next_rid(used_ids)
            rid_sequence.append(rid)
            slide_tags.append(
                f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="{target}"/>'
            )
            used_ids.add(rid)

        body = "\n".join(non_slide_tags + slide_tags)
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            f"{body}\n"
            "</Relationships>\n",
            rid_sequence,
        )

    def _rebuild_presentation_slide_list(self, *, presentation_text: str, rid_sequence: list[str]) -> str:
        max_slide_id = 255
        for value in re.findall(r"<p:sldId\b[^>]*\bid=\"(\d+)\"", presentation_text):
            try:
                max_slide_id = max(max_slide_id, int(value))
            except ValueError:
                pass
        next_id = max_slide_id + 1
        sld_entries: list[str] = []
        for rid in rid_sequence:
            sld_entries.append(f'    <p:sldId id="{next_id}" r:id="{rid}"/>')
            next_id += 1
        block = "<p:sldIdLst>\n" + "\n".join(sld_entries) + "\n  </p:sldIdLst>"
        if "<p:sldIdLst>" in presentation_text and "</p:sldIdLst>" in presentation_text:
            return re.sub(
                r"<p:sldIdLst>.*?</p:sldIdLst>",
                block,
                presentation_text,
                flags=re.DOTALL,
            )
        insert_at = presentation_text.find(">", presentation_text.find("<p:presentation"))
        if insert_at == -1:
            return presentation_text
        return presentation_text[: insert_at + 1] + "\n  " + block + presentation_text[insert_at + 1 :]

    def _rebuild_content_types_overrides(self, *, content_types_text: str, final_targets: list[str]) -> str:
        override_tags = re.findall(r"<Override\b[^>]*/>", content_types_text)
        kept: list[str] = []
        for tag in override_tags:
            attrs = self._parse_xml_attrs(tag)
            part_name = attrs.get("PartName", "")
            if part_name.startswith("/ppt/slides/slide") and part_name.endswith(".xml"):
                continue
            kept.append(tag)
        slide_overrides = [
            f'<Override PartName="/ppt/{target}" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            for target in final_targets
        ]
        body = "\n".join(kept + slide_overrides)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
            f"{body}\n"
            "</Types>\n"
        )

    def _ensure_template_structure_files(self, *, unpacked: Path) -> None:
        ppt_dir = unpacked / "ppt"
        slides_dir = ppt_dir / "slides"
        slide_rels_dir = slides_dir / "_rels"
        pres_rels_dir = ppt_dir / "_rels"
        slides_dir.mkdir(parents=True, exist_ok=True)
        slide_rels_dir.mkdir(parents=True, exist_ok=True)
        pres_rels_dir.mkdir(parents=True, exist_ok=True)

        existing_slides = sorted(slides_dir.glob("slide*.xml"), key=lambda p: self._slide_target_sort_key(f"slides/{p.name}"))
        if not existing_slides:
            self._write_default_slide_xml(slides_dir / "slide1.xml")
            existing_slides = [slides_dir / "slide1.xml"]

        presentation_path = ppt_dir / "presentation.xml"
        if not presentation_path.exists():
            presentation_path.write_text(
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
                'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">\n'
                "  <p:sldIdLst>\n"
                '    <p:sldId id="256" r:id="rId1"/>\n'
                "  </p:sldIdLst>\n"
                '  <p:sldSz cx="9144000" cy="5143500" type="screen16x9"/>\n'
                '  <p:notesSz cx="6858000" cy="9144000"/>\n'
                "</p:presentation>\n",
                encoding="utf-8",
            )

        presentation_rels_path = pres_rels_dir / "presentation.xml.rels"
        if not presentation_rels_path.exists():
            first_slide = existing_slides[0].name
            presentation_rels_path.write_text(
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
                f'  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/{first_slide}"/>\n'
                "</Relationships>\n",
                encoding="utf-8",
            )

        content_types_path = unpacked / "[Content_Types].xml"
        if not content_types_path.exists():
            content_types_path.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
                '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
                '  <Default Extension="xml" ContentType="application/xml"/>\n'
                '  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>\n'
                "</Types>\n",
                encoding="utf-8",
            )

    def _cleanup_orphan_slide_files(self, *, slides_dir: Path, keep_targets: set[str]) -> None:
        keep_names = {Path(target).name for target in keep_targets}
        for slide_file in slides_dir.glob("slide*.xml"):
            if slide_file.name not in keep_names:
                slide_file.unlink(missing_ok=True)

    def _cleanup_orphan_slide_rels(self, *, slide_rels_dir: Path, keep_slide_numbers: set[int]) -> None:
        for rel_file in slide_rels_dir.glob("slide*.xml.rels"):
            match = re.search(r"slide(\d+)\.xml\.rels$", rel_file.name)
            if not match:
                continue
            number = int(match.group(1))
            if number not in keep_slide_numbers:
                rel_file.unlink(missing_ok=True)

    def _slide_target_sort_key(self, target: str) -> tuple[int, str]:
        match = re.search(r"slide(\d+)\.xml$", target)
        if match:
            return (int(match.group(1)), target)
        return (10_000, target)

    def _write_default_slide_xml(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "<?xml version='1.0' encoding='UTF-8'?>"
            "<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main' "
            "xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'>"
            "<p:cSld><p:spTree><p:sp><p:txBody><a:bodyPr/><a:lstStyle/>"
            "<a:p><a:r><a:t>Template Slide</a:t></a:r></a:p>"
            "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>",
            encoding="utf-8",
        )

    def _parse_xml_attrs(self, tag: str) -> dict[str, str]:
        attrs: dict[str, str] = {}
        for key, value in re.findall(r'([A-Za-z_:][A-Za-z0-9_.:-]*)="([^"]*)"', tag):
            attrs[key] = value
        return attrs

    def _next_rid(self, used_ids: set[str]) -> str:
        numbers = []
        for rel_id in used_ids:
            match = re.fullmatch(r"rId(\d+)", rel_id)
            if match:
                numbers.append(int(match.group(1)))
        candidate = (max(numbers) + 1) if numbers else 1
        while f"rId{candidate}" in used_ids:
            candidate += 1
        return f"rId{candidate}"

    def _rewrite_template_slide_text(self, *, slide_xml: Path, node: OutlineNode) -> None:
        content = slide_xml.read_text(encoding="utf-8", errors="ignore")
        replacements = [node.title] + node.bullets
        matches = list(re.finditer(r"<a:t>.*?</a:t>", content, flags=re.DOTALL))
        if not matches:
            return

        out: list[str] = []
        cursor = 0
        for idx, match in enumerate(matches):
            out.append(content[cursor:match.start()])
            replacement = replacements[idx] if idx < len(replacements) else ""
            out.append(f"<a:t>{self._xml_escape(replacement)}</a:t>")
            cursor = match.end()
        out.append(content[cursor:])
        slide_xml.write_text("".join(out), encoding="utf-8")

    def _xml_escape(self, text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )


def build_orchestrator(base_dir: Path) -> RunOrchestrator:
    settings = load_settings()
    artifacts_dir = base_dir / "artifacts"
    templates_dir = base_dir / "templates"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    templates_dir.mkdir(parents=True, exist_ok=True)
    llm_client = OpenAICompatibleLLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        api_style=settings.llm_api_style,
        timeout_sec=settings.llm_timeout_sec,
        outline_temperature=settings.llm_temperature_outline,
        slide_temperature=settings.llm_temperature_slide,
    )
    return RunOrchestrator(
        store=RunStore(base_dir=base_dir),
        artifacts_base=artifacts_dir,
        templates_base=templates_dir,
        llm_client=llm_client,
        settings=settings,
    )
