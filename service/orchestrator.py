from __future__ import annotations

import asyncio
import html
import httpx
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import zlib
from dataclasses import dataclass, field
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
    OutlineHistoryEntry,
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
    VisualPolicy,
)
from .skill_profile import DesignProfile, StyleRecipe, allowed_layouts_for, choose_design_profile, enforce_layout_variety
from .store import RunStore, now_iso


class TemplateAssetError(RuntimeError):
    pass


class VisualPolicyUnsatisfiedError(RuntimeError):
    pass


class TemplateLayoutConflictError(RuntimeError):
    def __init__(self, *, slide_no: int, issues: list[str]) -> None:
        super().__init__(f"template layout conflict on slide {slide_no}")
        self.slide_no = slide_no
        self.issues = issues


class TemplateSlotMappingError(RuntimeError):
    def __init__(self, *, slide_no: int, missing_slots: list[dict[str, Any]]) -> None:
        super().__init__(f"template slot mapping failed on slide {slide_no}")
        self.slide_no = slide_no
        self.missing_slots = missing_slots


@dataclass
class SlotNode:
    slot_id: str
    slot_type: str
    required: bool
    rel_id: str | None = None
    hint: str = ""
    group_id: str | None = None


@dataclass
class SlotGraph:
    slide_no: int
    slots: list[SlotNode] = field(default_factory=list)


@dataclass
class ChartFact:
    label: str
    value: float
    unit: str
    source_ref: str


@dataclass
class ChartPlan:
    has_verified_data: bool
    mode: str
    labels: list[str]
    values: list[float]
    unit: str
    note: str
    source: str


@dataclass
class LayoutBox:
    element_type: str
    xml_tag: str
    block_start: int
    block_end: int
    x_emu: int
    y_emu: int
    w_emu: int
    h_emu: int
    rel_id: str | None = None
    element_id: str | None = None

    @property
    def x(self) -> float:
        return self.x_emu / 914400.0

    @property
    def y(self) -> float:
        return self.y_emu / 914400.0

    @property
    def w(self) -> float:
        return self.w_emu / 914400.0

    @property
    def h(self) -> float:
        return self.h_emu / 914400.0


SLIDE_WIDTH_EMU = 9_144_000
SLIDE_HEIGHT_EMU = 5_143_500


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
        self.max_slide_repair_rounds = max(1, settings.max_slide_repair_rounds)

    def _use_agentic_engine(self) -> bool:
        return self.settings.generation_engine == "agentic_v2"

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
            outline_history=run.outline_history,
            slides=run.slides,
            citation_map=run.citation_map,
            stage_timings=run.stage_timings,
            error_code=run.error_code,
            failed_stage=run.failed_stage,
            retryable=run.retryable,
            compile_js_path=run.compile_js_path,
            pptx_path=run.pptx_path,
            qa_report=run.qa_report,
            template_mapping_report=run.template_mapping_report,
            chart_truth_report=run.chart_truth_report,
            repair_history=run.repair_history,
            quality_report=run.quality_report,
            quality_gate_report=run.quality_gate_report,
            research_report=run.research_report,
            candidate_selection_report=run.candidate_selection_report,
            template_layout_report=run.template_layout_report,
            artifact_cleanup_report=run.artifact_cleanup_report,
            events=run.events,
        )

    async def confirm_outline(self, run_id: str, req: ConfirmOutlineRequest) -> RunSummaryResponse | None:
        run = await self.store.get_run(run_id)
        if run is None:
            return None
        if run.status != RunStatus.AWAITING_OUTLINE_CONFIRM:
            raise ValueError("run is not awaiting outline confirmation")

        if run.outline is None:
            raise ValueError("run outline is missing")

        if req.outline is not None:
            if req.base_version != run.outline.version:
                raise ValueError(
                    f"base_version mismatch: expected {run.outline.version}, got {req.base_version}"
                )
            enforce_layout_variety(
                nodes=req.outline.nodes,
                seed=f"{run.input.topic}|{run.input.template_style}|{run_id}|confirm",
            )
            if req.outline.version <= run.outline.version:
                req.outline.version = run.outline.version + 1

        def apply_confirm(r: RunRecord) -> None:
            current_version = r.outline.version if r.outline is not None else None
            if req.outline is not None:
                r.outline = req.outline
            if req.approved:
                r.status = RunStatus.SLIDES_GENERATING
            else:
                r.status = RunStatus.AWAITING_OUTLINE_CONFIRM
            new_version = r.outline.version if r.outline is not None else None
            action = "confirmed" if req.approved else ("updated" if req.outline is not None else "rejected")
            r.outline_history.append(
                OutlineHistoryEntry(
                    action=action,
                    approved=req.approved,
                    base_version=current_version,
                    new_version=new_version,
                    change_reason=req.change_reason,
                    at=now_iso(),
                )
            )

        await self.store.update_run(run_id, apply_confirm)
        if req.outline is not None:
            await self._publish(
                run_id,
                EventType.OUTLINE_UPDATED,
                {
                    "approved": req.approved,
                    "base_version": req.base_version,
                    "new_version": req.outline.version,
                    "change_reason": req.change_reason,
                },
            )
        if req.approved:
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
            try:
                research_brief = await self.llm_client.generate_research_brief(
                    topic=run.input.topic,
                    project_id=run.input.project_id,
                    rag_source_ids=run.input.rag_source_ids,
                    template_style=run.input.template_style,
                    target_slide_count=run.input.target_slide_count,
                )
            except Exception:
                research_brief = self._fallback_research_brief(
                    topic=run.input.topic,
                    template_style=run.input.template_style,
                    target_slide_count=run.input.target_slide_count,
                )

            def apply_outline(r: RunRecord) -> None:
                r.outline = outline
                r.research_report = research_brief
                r.status = RunStatus.AWAITING_OUTLINE_CONFIRM
                r.stage_timings.outline_ms = int((time.perf_counter() - started) * 1000)
                r.outline_history.append(
                    OutlineHistoryEntry(
                        action="generated",
                        approved=False,
                        base_version=None,
                        new_version=outline.version,
                        change_reason=None,
                        at=now_iso(),
                    )
                )

            await self.store.update_run(run_id, apply_outline)
            await self._publish(run_id, EventType.OUTLINE_COMPLETED, {"version": outline.version, "sections": len(outline.nodes)})
            await self._publish(
                run_id,
                EventType.RESEARCH_COMPLETED,
                {
                    "audience": research_brief.get("audience", ""),
                    "purpose": research_brief.get("purpose", ""),
                    "tone": research_brief.get("tone", ""),
                },
            )
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
        if run.input.visual_policy == VisualPolicy.MEDIA_REQUIRED and self.settings.asset_provider == "none":
            await self._fail_run(run_id, "SLIDES_GENERATING", "VISUAL_POLICY_UNSATISFIED", retryable=False)
            return
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
        if any(isinstance(item, VisualPolicyUnsatisfiedError) for item in results):
            await self._fail_run(run_id, "SLIDES_GENERATING", "VISUAL_POLICY_UNSATISFIED", retryable=False)
            return
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
                latest = await self.store.get_run(run_id)
                if latest is not None and latest.status == RunStatus.FAILED:
                    return
                await self._fail_run(run_id, "COMPILING", "POLISH_FAILED", retryable=True)
                return
            if not qa_ok:
                repaired = await self._repair_loop(run_id, mode=GenerationMode.SCRATCH, design=design)
                if not repaired:
                    latest = await self.store.get_run(run_id)
                    if latest is not None and latest.status == RunStatus.FAILED:
                        return
                    await self._fail_run(run_id, "COMPILING", "QA_FAILED", retryable=False)
                    return
            else:
                qa_ok_after_polish = await self._run_skill_qa(run_id, mode=GenerationMode.SCRATCH)
                if not qa_ok_after_polish:
                    repaired = await self._repair_loop(run_id, mode=GenerationMode.SCRATCH, design=design)
                    if not repaired:
                        latest = await self.store.get_run(run_id)
                        if latest is not None and latest.status == RunStatus.FAILED:
                            return
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

        template_dir, work_template, template_md, unpacked, edited, template_slides_dir, template_compile_js, _ = self._template_work_paths(Path(run.artifact_dir))
        template_dir.mkdir(parents=True, exist_ok=True)
        unpacked.mkdir(parents=True, exist_ok=True)
        src_template = Path(template_record.path)
        shutil.copy2(src_template, work_template)
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

        if unpacked.exists():
            shutil.rmtree(unpacked)
        unpacked.mkdir(parents=True, exist_ok=True)
        with ZipFile(work_template, "r") as zin:
            zin.extractall(unpacked)

        compile_start = time.perf_counter()
        try:
            artifacts = await self._apply_template_nodes_once(
                run_id=run_id,
                unpacked=unpacked,
                design=design,
                use_review=False,
                forced_issues=None,
            )
        except TemplateAssetError:
            await self._fail_run(run_id, "SLIDES_GENERATING", "TEMPLATE_ASSET_FETCH_FAILED", retryable=False)
            return
        except TemplateSlotMappingError:
            await self._fail_run(run_id, "SLIDES_GENERATING", "TEMPLATE_SLOT_UNMAPPED", retryable=False)
            return
        except TemplateLayoutConflictError:
            await self._fail_run(run_id, "SLIDES_GENERATING", "TEMPLATE_LAYOUT_CONFLICT", retryable=False)
            return
        if not artifacts:
            await self._fail_run(run_id, "SLIDES_GENERATING", "TEMPLATE_APPLY_FAILED", retryable=True)
            return
        self._pack_template_unpacked(unpacked=unpacked, edited=edited)

        compiled = await self._compile_template_js(template_slides_dir=template_slides_dir)
        if not compiled:
            await self._fail_run(run_id, "COMPILING", "TEMPLATE_JS_COMPILE_FAILED", retryable=True)
            return

        def apply_compile(r: RunRecord) -> None:
            r.compile_js_path = str(template_compile_js)
            r.pptx_path = str(edited)
            r.stage_timings.compile_ms = int((time.perf_counter() - compile_start) * 1000)
            r.slides = artifacts
            r.citation_map = {item.slide_no: list(item.citations) for item in artifacts}

        await self.store.update_run(run_id, apply_compile)
        await self._publish(
            run_id,
            EventType.COMPILE_COMPLETED,
            {"file": str(edited), "mode": "template", "compile_js": str(template_compile_js)},
        )

        if self.settings.qa_enabled:
            qa_ok = await self._run_skill_qa(run_id, mode=GenerationMode.TEMPLATE)
            polished = await self._mandatory_polish_cycle(run_id, mode=GenerationMode.TEMPLATE, design=design)
            if not polished:
                latest = await self.store.get_run(run_id)
                if latest is not None and latest.status == RunStatus.FAILED:
                    return
                await self._fail_run(run_id, "COMPILING", "POLISH_FAILED", retryable=True)
                return
            if not qa_ok:
                repaired = await self._repair_loop(run_id, mode=GenerationMode.TEMPLATE, design=design)
                if not repaired:
                    latest = await self.store.get_run(run_id)
                    if latest is not None and latest.status == RunStatus.FAILED:
                        return
                    await self._fail_run(run_id, "COMPILING", "QA_FAILED", retryable=False)
                    return
        await self.store.update_run(run_id, lambda r: setattr(r, "status", RunStatus.SUCCEEDED))

    def _template_work_paths(self, artifact_dir: Path) -> tuple[Path, Path, Path, Path, Path, Path, Path, Path]:
        template_dir = artifact_dir / "template_edit"
        work_template = template_dir / "template.pptx"
        template_md = template_dir / "template.md"
        unpacked = template_dir / "unpacked"
        edited = template_dir / "edited.pptx"
        template_slides_dir = artifact_dir / "template_slides"
        template_compile_js = template_slides_dir / "compile.js"
        template_compiled_pptx = template_slides_dir / "output" / "presentation.pptx"
        return template_dir, work_template, template_md, unpacked, edited, template_slides_dir, template_compile_js, template_compiled_pptx

    def _pack_template_unpacked(self, *, unpacked: Path, edited: Path) -> None:
        with ZipFile(edited, "w", compression=ZIP_DEFLATED) as zout:
            for file in unpacked.rglob("*"):
                if file.is_file():
                    arc = file.relative_to(unpacked).as_posix()
                    zout.write(file, arc)

    async def _compile_template_js(self, *, template_slides_dir: Path) -> bool:
        result = await asyncio.to_thread(
            subprocess.run,
            ["node", "compile.js"],
            cwd=template_slides_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0

    async def _apply_template_nodes_once(
        self,
        *,
        run_id: str,
        unpacked: Path,
        design: DesignProfile,
        use_review: bool,
        forced_issues: list[str] | None,
    ) -> list[SlideArtifact] | None:
        run = await self.store.get_run(run_id)
        if run is None or run.outline is None:
            return None
        slide_files = self._rebuild_template_structure(unpacked=unpacked, target_count=len(run.outline.nodes))
        _, _, _, _, _, template_slides_dir, template_compile_js, _ = self._template_work_paths(Path(run.artifact_dir))
        template_slides_dir.mkdir(parents=True, exist_ok=True)
        (template_slides_dir / "output").mkdir(parents=True, exist_ok=True)

        artifacts: list[SlideArtifact] = []
        mapping_report: dict[str, Any] = {"mode": "template", "slides": [], "unmapped_required": [], "passed": True}
        chart_report: dict[str, Any] = {"slides": [], "passed": True}
        layout_report: dict[str, Any] = {"slides": [], "passed": True}
        for idx, slide_xml in enumerate(slide_files, start=1):
            if idx > len(run.outline.nodes):
                break
            base_node = run.outline.nodes[idx - 1]
            node_for_apply = base_node
            citations = self._normalize_citations([], run.input.rag_source_ids, idx)
            if use_review:
                candidate = self._extract_candidate_from_template_slide(
                    unpacked=unpacked,
                    slide_xml=slide_xml,
                    fallback_node=base_node,
                    citations=citations,
                )
                reviewed = await self.llm_client.review_slide(
                    topic=run.input.topic,
                    template_style=run.input.template_style,
                    slide_no=idx,
                    target_slide_count=run.input.target_slide_count,
                    outline_node=base_node,
                    candidate=candidate,
                    rule_violations=forced_issues or run.qa_report.get("issues", []),
                )
                node_for_apply = OutlineNode(
                    title=reviewed.title,
                    bullets=reviewed.bullets,
                    page_type=base_node.page_type,
                    layout_hint=reviewed.layout_hint or base_node.layout_hint,
                )
                citations = self._normalize_citations(reviewed.citations, run.input.rag_source_ids, idx)

            slot_graph = self._build_slot_graph(slide_xml=slide_xml, slide_no=idx)
            mapping = self._plan_slot_mapping(slot_graph=slot_graph)
            missing = [item for item in mapping["slots"] if item["required"] and not item["mapped"]]
            mapping_entry = {
                "slide_no": idx,
                "slot_count": len(mapping["slots"]),
                "mapped_count": sum(1 for item in mapping["slots"] if item["mapped"]),
                "missing_required": missing,
                "slots": mapping["slots"],
            }
            mapping_report["slides"].append(mapping_entry)
            await self._publish(
                run_id,
                EventType.SLOT_MAPPING_COMPLETED,
                {
                    "slide_no": idx,
                    "mapped_count": mapping_entry["mapped_count"],
                    "slot_count": mapping_entry["slot_count"],
                    "missing_required": missing,
                },
            )
            if missing:
                mapping_report["passed"] = False
                mapping_report["unmapped_required"].extend(
                    [{"slide_no": idx, **item} for item in missing]
                )
                await self.store.update_run(
                    run_id,
                    lambda r: setattr(r, "template_mapping_report", mapping_report),
                )
                raise TemplateSlotMappingError(slide_no=idx, missing_slots=missing)

            chart_plan = self._build_chart_plan_from_bullets(
                node=node_for_apply,
                source_refs=citations,
            )
            semantic_report = self._rewrite_template_slide_semantics(
                unpacked=unpacked,
                slide_xml=slide_xml,
                node=node_for_apply,
                slide_no=idx,
                chart_plan=chart_plan,
            )
            layout_entry = semantic_report.get("layout")
            if isinstance(layout_entry, dict):
                layout_report["slides"].append(layout_entry)
                await self._publish(
                    run_id,
                    EventType.TEMPLATE_LAYOUT_REFLOW_COMPLETED,
                    {
                        "slide_no": idx,
                        "box_count": int(layout_entry.get("box_count", 0)),
                        "moved_count": int(layout_entry.get("moved_count", 0)),
                        "issues_before_count": int(layout_entry.get("issues_before_count", 0)),
                        "issues_after_count": int(layout_entry.get("issues_after_count", 0)),
                        "passed": bool(layout_entry.get("passed", False)),
                    },
                )
                await self._publish(
                    run_id,
                    EventType.TEMPLATE_FIDELITY_CHECKED,
                    {
                        "slide_no": idx,
                        "fidelity_score": int(layout_entry.get("fidelity_score", 0)),
                        "passed": bool(layout_entry.get("passed", False)),
                    },
                )
                if not bool(layout_entry.get("passed", False)):
                    layout_report["passed"] = False
                    await self.store.update_run(
                        run_id,
                        lambda r: setattr(r, "template_layout_report", layout_report),
                    )
                    raise TemplateLayoutConflictError(slide_no=idx, issues=list(layout_entry.get("issues_after", [])))
            if semantic_report.get("chart"):
                chart_report["slides"].append({"slide_no": idx, **semantic_report["chart"]})
                if not semantic_report["chart"].get("has_verified_data"):
                    chart_report["passed"] = False
                await self._publish(
                    run_id,
                    EventType.CHART_TRUTH_CHECKED,
                    {
                        "slide_no": idx,
                        "has_verified_data": semantic_report["chart"].get("has_verified_data", False),
                        "mode": semantic_report["chart"].get("mode", "none"),
                        "source": semantic_report["chart"].get("source", ""),
                    },
                )

            generated = GeneratedSlide(
                title=node_for_apply.title,
                bullets=list(node_for_apply.bullets),
                citations=list(citations),
                page_type=base_node.page_type,
                layout_hint=node_for_apply.layout_hint,
            )
            js_code = self._render_skill_slide_js(
                slide_no=idx,
                total=run.input.target_slide_count,
                node=base_node,
                generated=generated,
                design=design,
                chart_plan=chart_plan,
            )
            slide_path = template_slides_dir / f"slide-{idx:02d}.js"
            slide_path.write_text(js_code, encoding="utf-8")
            artifacts.append(
                SlideArtifact(
                    slide_no=idx,
                    js_path=str(slide_path),
                    js_code=js_code,
                    status="ok",
                    citations=list(citations),
                )
            )

        template_compile_js.write_text(
            self._build_compile_script(total=len(artifacts), theme=design.theme),
            encoding="utf-8",
        )
        def apply_reports(r: RunRecord) -> None:
            r.template_mapping_report = mapping_report
            r.chart_truth_report = chart_report
            r.template_layout_report = layout_report

        await self.store.update_run(run_id, apply_reports)
        self._cleanup_orphan_media(unpacked=unpacked)
        return artifacts

    async def _revise_template_slides(self, *, run_id: str, design: DesignProfile, forced_issues: list[str] | None) -> bool:
        run = await self.store.get_run(run_id)
        if run is None:
            return False
        _, _, _, unpacked, edited, template_slides_dir, template_compile_js, _ = self._template_work_paths(Path(run.artifact_dir))
        if not unpacked.exists():
            return False
        try:
            artifacts = await self._apply_template_nodes_once(
                run_id=run_id,
                unpacked=unpacked,
                design=design,
                use_review=True,
                forced_issues=forced_issues,
            )
        except TemplateAssetError:
            return False
        if not artifacts:
            return False
        self._pack_template_unpacked(unpacked=unpacked, edited=edited)
        compiled = await self._compile_template_js(template_slides_dir=template_slides_dir)
        if not compiled:
            return False

        def apply_compile(r: RunRecord) -> None:
            r.pptx_path = str(edited)
            r.compile_js_path = str(template_compile_js)
            r.stage_timings.compile_ms = max(1, r.stage_timings.compile_ms)
            r.slides = artifacts
            r.citation_map = {item.slide_no: list(item.citations) for item in artifacts}

        await self.store.update_run(run_id, apply_compile)
        await self._publish(run_id, EventType.COMPILE_COMPLETED, {"file": str(edited), "mode": "template-repair"})
        return True

    def _extract_candidate_from_template_slide(
        self,
        *,
        unpacked: Path,
        slide_xml: Path,
        fallback_node: OutlineNode,
        citations: list[str],
    ) -> GeneratedSlide:
        content = slide_xml.read_text(encoding="utf-8", errors="ignore")
        placeholder_re = re.compile(r"(placeholder|lorem|ipsum|xxxx|template|caption|insert)", flags=re.IGNORECASE)
        raw_texts = [self._xml_unescape(item).strip() for item in re.findall(r"<a:t>(.*?)</a:t>", content, flags=re.DOTALL)]
        texts = [item for item in raw_texts if item and not placeholder_re.search(item)]
        chart_texts = self._extract_related_chart_texts(unpacked=unpacked, slide_xml=slide_xml)
        title = texts[0] if texts else fallback_node.title
        bullets = [item for item in texts[1:] if item != title]
        for item in chart_texts:
            if item and item != title and item not in bullets:
                bullets.append(item)
        if not bullets:
            bullets = list(fallback_node.bullets)
        return GeneratedSlide(
            title=title,
            bullets=bullets,
            citations=list(citations),
            page_type=fallback_node.page_type,
            layout_hint=fallback_node.layout_hint,
        )

    def _extract_related_chart_texts(self, *, unpacked: Path, slide_xml: Path) -> list[str]:
        rels_path = slide_xml.parent / "_rels" / f"{slide_xml.name}.rels"
        if not rels_path.exists():
            return []
        rels_text = rels_path.read_text(encoding="utf-8", errors="ignore")
        results: list[str] = []
        for tag in re.findall(r"<Relationship\b[^>]*/>", rels_text):
            attrs = self._parse_xml_attrs(tag)
            rel_type = attrs.get("Type", "")
            target = attrs.get("Target", "")
            if not rel_type.endswith("/chart") or not target:
                continue
            chart_path = (slide_xml.parent / target).resolve()
            try:
                chart_path.relative_to(unpacked.resolve())
            except ValueError:
                continue
            if not chart_path.exists():
                continue
            chart_xml = chart_path.read_text(encoding="utf-8", errors="ignore")
            values = [self._xml_unescape(v).strip() for v in re.findall(r"<c:v>(.*?)</c:v>", chart_xml, flags=re.DOTALL)]
            for value in values[:5]:
                if value and value not in results:
                    results.append(value)
        return results

    def _cleanup_orphan_media(self, *, unpacked: Path) -> None:
        media_dir = unpacked / "ppt" / "media"
        if not media_dir.exists():
            return
        referenced: set[str] = set()
        for rel_file in (unpacked / "ppt" / "slides" / "_rels").glob("*.rels"):
            rels_text = rel_file.read_text(encoding="utf-8", errors="ignore")
            for tag in re.findall(r"<Relationship\b[^>]*/>", rels_text):
                attrs = self._parse_xml_attrs(tag)
                rel_type = attrs.get("Type", "")
                target = attrs.get("Target", "")
                if not rel_type.endswith("/image") or not target:
                    continue
                target_path = (rel_file.parent.parent / target).resolve()
                try:
                    rel = target_path.relative_to(unpacked.resolve()).as_posix()
                except ValueError:
                    continue
                referenced.add(rel)

        for media_file in media_dir.rglob("*"):
            if not media_file.is_file():
                continue
            rel = media_file.relative_to(unpacked).as_posix()
            if rel not in referenced:
                media_file.unlink(missing_ok=True)

    async def _generate_skill_slide(self, *, run_id: str, slide_no: int, node: OutlineNode, design: DesignProfile) -> SlideArtifact:
        run = await self.store.get_run(run_id)
        assert run is not None
        artifact_dir = Path(run.artifact_dir)
        slides_dir = artifact_dir / "slides"
        if self._use_agentic_engine():
            return await self._generate_agentic_slide(
                run_id=run_id,
                slide_no=slide_no,
                node=node,
                design=design,
                slides_dir=slides_dir,
            )
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
                citations = self._normalize_citations(reviewed.citations, run.input.rag_source_ids, slide_no)
                chart_plan = self._build_chart_plan_from_bullets(
                    node=OutlineNode(
                        title=reviewed.title,
                        bullets=list(reviewed.bullets),
                        page_type=node.page_type,
                        layout_hint=reviewed.layout_hint or node.layout_hint,
                    ),
                    source_refs=citations,
                )
                js_code = self._render_skill_slide_js(
                    slide_no=slide_no,
                    total=run.input.target_slide_count,
                    node=node,
                    generated=reviewed,
                    design=design,
                    chart_plan=chart_plan,
                )
                slide_path = slides_dir / f"slide-{slide_no:02d}.js"
                slide_path.write_text(js_code, encoding="utf-8")
                await self._append_chart_truth_report(
                    run_id=run_id,
                    entry={
                        "slide_no": slide_no,
                        "has_verified_data": chart_plan.has_verified_data,
                        "mode": chart_plan.mode,
                        "source": chart_plan.source,
                        "note": chart_plan.note,
                        "labels": chart_plan.labels,
                    },
                )
                await self._publish(
                    run_id,
                    EventType.CHART_TRUTH_CHECKED,
                    {
                        "slide_no": slide_no,
                        "has_verified_data": chart_plan.has_verified_data,
                        "mode": chart_plan.mode,
                        "source": chart_plan.source,
                    },
                )
                status = "ok" if retries == 0 else f"ok_after_retry_{retries}"
                return SlideArtifact(
                    slide_no=slide_no,
                    js_path=str(slide_path),
                    js_code=js_code,
                    status=status,
                    citations=citations,
                )
            except Exception:
                retries += 1
                if retries >= self.slide_retry:
                    raise
                await asyncio.sleep(0.05 * retries)

    async def _generate_agentic_slide(
        self,
        *,
        run_id: str,
        slide_no: int,
        node: OutlineNode,
        design: DesignProfile,
        slides_dir: Path,
    ) -> SlideArtifact:
        run = await self.store.get_run(run_id)
        assert run is not None
        slide_plan = self._build_slide_plan(node=node, design=design, slide_no=slide_no)
        await self._publish(
            run_id,
            EventType.SLIDE_PLAN_COMPLETED,
            {
                "slide_no": slide_no,
                "layout": slide_plan.get("layout"),
                "visual_policy": run.input.visual_policy.value,
                "visual_plan": slide_plan.get("visual_plan", {}),
            },
        )
        await self._publish(
            run_id,
            EventType.SLIDE_CODEGEN_STARTED,
            {"slide_no": slide_no, "engine": self.settings.generation_engine},
        )
        slide_path = slides_dir / f"slide-{slide_no:02d}.js"

        issues: list[str] = []
        round_passed = 0
        llm_score = 0
        selected_preview_text = ""
        selected_repair_directives: list[str] = []
        selected_llm_issues: list[str] = []
        gate_threshold = 80
        candidate_workers = 3
        best_js = ""
        for repair_round in range(1, self.max_slide_repair_rounds + 1):
            if repair_round == 1:
                async def build_candidate(worker_idx: int) -> tuple[int, str]:
                    variant_plan = dict(slide_plan)
                    variant_plan["candidate_worker"] = worker_idx
                    js = await self.llm_client.generate_slide_js(
                        topic=run.input.topic,
                        template_style=run.input.template_style,
                        slide_no=slide_no,
                        target_slide_count=run.input.target_slide_count,
                        outline_node=node,
                        theme=design.theme,
                        title_font=design.title_font,
                        body_font=design.body_font,
                        rag_source_ids=run.input.rag_source_ids,
                        visual_policy=run.input.visual_policy,
                        slide_plan=variant_plan,
                    )
                    return worker_idx, js
            else:
                async def build_candidate(worker_idx: int) -> tuple[int, str]:
                    directives = list(selected_repair_directives) + [f"variant worker {worker_idx}"]
                    js = await self.llm_client.critique_slide_js(
                        topic=run.input.topic,
                        template_style=run.input.template_style,
                        slide_no=slide_no,
                        target_slide_count=run.input.target_slide_count,
                        outline_node=node,
                        candidate_js=best_js,
                        issues=issues,
                        visual_policy=run.input.visual_policy,
                        slide_plan=slide_plan,
                        repair_directives=directives,
                        preview_text=selected_preview_text,
                    )
                    return worker_idx, js

            built = await asyncio.gather(*(build_candidate(worker_idx) for worker_idx in range(1, candidate_workers + 1)))
            candidate_eval_items: list[dict[str, Any]] = []
            candidate_paths: list[Path] = []
            for worker_idx, js in built:
                candidate_path = slides_dir / f"slide-{slide_no:02d}-cand-{worker_idx:02d}.js"
                candidate_path.write_text(js, encoding="utf-8")
                candidate_paths.append(candidate_path)
                hard_issues = self._validate_slide_js_contract(
                    js,
                    slide_no=slide_no,
                    page_type=node.page_type.value,
                    visual_policy=run.input.visual_policy,
                )
                preview_issues, preview_text = await self._run_slide_preview_qa_with_text(
                    run_id=run_id,
                    slide_js=candidate_path,
                    slide_no=slide_no,
                )
                hard_issues.extend(preview_issues)
                llm_gate = await self.llm_client.evaluate_slide_quality(
                    topic=run.input.topic,
                    template_style=run.input.template_style,
                    slide_no=slide_no,
                    target_slide_count=run.input.target_slide_count,
                    outline_node=node,
                    candidate_js=js,
                    preview_text=preview_text,
                    hard_issues=hard_issues,
                    visual_policy=run.input.visual_policy,
                )
                score = int(llm_gate.get("score", 0))
                llm_issues = [str(item) for item in llm_gate.get("issues", [])]
                repair_directives = [str(item) for item in llm_gate.get("repair_directives", [])]
                item_issues = list(hard_issues)
                if score < gate_threshold:
                    item_issues.append(f"quality score below threshold: {score} < {gate_threshold}")
                item_issues.extend(llm_issues)
                candidate_eval = {
                    "candidate": worker_idx,
                    "candidate_js": js,
                    "score": score,
                    "hard_issues": hard_issues,
                    "llm_issues": llm_issues,
                    "repair_directives": repair_directives,
                    "issues": item_issues,
                    "passed": not item_issues,
                    "preview_text": preview_text,
                }
                candidate_eval_items.append(candidate_eval)
                await self._publish(
                    run_id,
                    EventType.SLIDE_CANDIDATE_GENERATED,
                    {
                        "slide_no": slide_no,
                        "round": repair_round,
                        "candidate": worker_idx,
                        "score": score,
                        "passed": not item_issues,
                        "hard_issue_count": len(hard_issues),
                        "llm_issue_count": len(llm_issues),
                    },
                )

            candidate_eval_items.sort(
                key=lambda item: (
                    len(item["hard_issues"]),
                    0 if item["passed"] else 1,
                    -int(item["score"]),
                    len(item["issues"]),
                )
            )
            best = candidate_eval_items[0]
            best_js = str(best["candidate_js"])
            llm_score = int(best["score"])
            selected_preview_text = str(best["preview_text"])
            selected_repair_directives = [str(x) for x in best["repair_directives"]]
            selected_llm_issues = [str(x) for x in best["llm_issues"]]
            issues = [str(x) for x in best["issues"]]

            await self._append_candidate_selection_entry(
                run_id=run_id,
                entry={
                    "slide_no": slide_no,
                    "round": repair_round,
                    "selected_candidate": int(best["candidate"]),
                    "selected_score": llm_score,
                    "selected_passed": bool(best["passed"]),
                    "candidates": [
                        {
                            "candidate": int(item["candidate"]),
                            "score": int(item["score"]),
                            "passed": bool(item["passed"]),
                            "hard_issue_count": len(item["hard_issues"]),
                            "llm_issue_count": len(item["llm_issues"]),
                        }
                        for item in candidate_eval_items
                    ],
                },
            )
            await self._publish(
                run_id,
                EventType.SLIDE_SELECTION_COMPLETED,
                {
                    "slide_no": slide_no,
                    "round": repair_round,
                    "selected_candidate": int(best["candidate"]),
                    "score": llm_score,
                    "passed": bool(best["passed"]),
                },
            )
            await self._append_quality_gate_entry(
                run_id=run_id,
                entry={
                    "slide_no": slide_no,
                    "round": repair_round,
                    "visual_policy": run.input.visual_policy.value,
                    "score": llm_score,
                    "threshold": gate_threshold,
                    "hard_issues": list(best["hard_issues"]),
                    "llm_issues": selected_llm_issues,
                    "repair_directives": selected_repair_directives,
                    "passed": not issues,
                },
            )
            await self._publish(
                run_id,
                EventType.SLIDE_QUALITY_GATE_COMPLETED,
                {
                    "slide_no": slide_no,
                    "round": repair_round,
                    "score": llm_score,
                    "threshold": gate_threshold,
                    "passed": not issues,
                    "hard_issue_count": len(best["hard_issues"]),
                    "llm_issue_count": len(selected_llm_issues),
                },
            )
            for candidate_path in candidate_paths:
                candidate_path.unlink(missing_ok=True)

            if not issues:
                slide_path.write_text(best_js, encoding="utf-8")
                round_passed = repair_round
                break
            await self._publish(
                run_id,
                EventType.SLIDE_CRITIC_COMPLETED,
                {"slide_no": slide_no, "round": repair_round, "issues": issues},
            )
            await self._publish(
                run_id,
                EventType.SLIDE_REPAIR_DIRECTIVES_GENERATED,
                {"slide_no": slide_no, "round": repair_round, "directives": selected_repair_directives},
            )
            await self._publish(
                run_id,
                EventType.SLIDE_REPAIR_COMPLETED,
                {"slide_no": slide_no, "round": repair_round},
            )

        if round_passed == 0:
            if any("visual_policy" in issue for issue in issues):
                raise VisualPolicyUnsatisfiedError(
                    f"slide {slide_no} violated visual policy={run.input.visual_policy.value}: {issues}"
                )
            raise RuntimeError(f"slide {slide_no} failed after {self.max_slide_repair_rounds} rounds: {issues}")

        final_js = slide_path.read_text(encoding="utf-8")
        citations = self._normalize_citations([], run.input.rag_source_ids, slide_no)
        await self._append_quality_entry(
            run_id=run_id,
            entry={
                "slide_no": slide_no,
                "passed_round": round_passed,
                "issues_last_round": issues,
                "engine": self.settings.generation_engine,
                "quality_score": llm_score,
                "visual_policy": run.input.visual_policy.value,
            },
        )
        await self._publish(
            run_id,
            EventType.SLIDE_CODEGEN_COMPLETED,
            {"slide_no": slide_no, "rounds": round_passed},
        )
        return SlideArtifact(
            slide_no=slide_no,
            js_path=str(slide_path),
            js_code=final_js,
            status=f"ok_agentic_round_{round_passed}",
            citations=citations,
        )

    def _validate_slide_js_contract(
        self,
        js_code: str,
        *,
        slide_no: int,
        page_type: str,
        visual_policy: VisualPolicy = VisualPolicy.AUTO,
    ) -> list[str]:
        issues: list[str] = []
        if "module.exports = { createSlide, slideConfig };" not in js_code:
            issues.append("missing export contract")
        if "function createSlide(pres, theme)" not in js_code:
            issues.append("createSlide signature invalid")
        if "async function createSlide" in js_code:
            issues.append("createSlide must be synchronous")
        if re.search(r"['\"]#[0-9a-fA-F]{3,8}['\"]", js_code):
            issues.append("hex color with # is forbidden")
        if re.search(r"['\"][0-9a-fA-F]{8}['\"]", js_code):
            issues.append("8-char hex color is forbidden")
        if slide_no > 1 and ("addPageBadge" not in js_code or "x: 9.3, y: 5.1" not in js_code):
            issues.append("missing required page badge position")
        if any(char in js_code for char in ("•", "✓", "▪", "◦")):
            issues.append("unicode bullet symbol detected")
        if page_type == "content" and all(token not in js_code for token in ("addShape(", "addImage(", "addChart(")):
            issues.append("content slide missing non-text visual element")
        if page_type == "content":
            if visual_policy == VisualPolicy.MEDIA_REQUIRED:
                if "addImage(" not in js_code:
                    issues.append("visual_policy violation: media_required needs addImage()")
                if all(token not in js_code for token in ("addShape(", "addChart(")):
                    issues.append("visual_policy violation: media_required needs addShape()/addChart() complement")
            elif visual_policy == VisualPolicy.BASIC_GRAPHICS_ONLY:
                if "addImage(" in js_code:
                    issues.append("visual_policy violation: basic_graphics_only forbids addImage()")
        return issues

    def _build_slide_plan(
        self,
        *,
        node: OutlineNode,
        design: DesignProfile,
        slide_no: int,
    ) -> dict[str, Any]:
        allowed = allowed_layouts_for(node.page_type)
        layout = node.layout_hint if node.layout_hint in allowed else (allowed[0] if allowed else (node.layout_hint or "content-two-column"))
        visual_kind = "shape_chart"
        if node.page_type == SlidePageType.CONTENT:
            if layout in {"content-showcase", "content-two-column"}:
                visual_kind = "image_or_showcase"
            elif layout == "content-stat-callout":
                visual_kind = "chart_callout"
            elif layout == "content-icon-rows":
                visual_kind = "icon_rows"
            elif layout in {"content-timeline", "content-comparison"}:
                visual_kind = "shape_flow"
        return {
            "slide_no": slide_no,
            "page_type": node.page_type.value,
            "layout": layout,
            "visual_plan": {
                "kind": visual_kind,
                "must_have_badge": node.page_type != SlidePageType.COVER,
            },
            "design_tokens": {
                "palette": design.palette_name,
                "style": design.style.name,
                "title_font": design.title_font,
                "body_font": design.body_font,
            },
            "content_blocks": {
                "title": node.title,
                "bullets_count": len(node.bullets),
            },
        }

    def _fallback_research_brief(self, *, topic: str, template_style: str, target_slide_count: int) -> dict[str, Any]:
        return {
            "audience": "general audience",
            "purpose": f"explain {topic} clearly with actionable insights",
            "tone": "professional and concise",
            "narrative_arc": "background -> key points -> evidence -> practical takeaways",
            "page_focus": [f"Page {idx}: key message and supporting evidence" for idx in range(1, target_slide_count + 1)],
            "design_notes": [
                f"Keep visual language consistent with template_style={template_style}.",
                "Ensure strong title/body hierarchy.",
                "Use visual anchors on content slides.",
            ],
        }

    def _render_skill_slide_js(
        self,
        *,
        slide_no: int,
        total: int,
        node: OutlineNode,
        generated: GeneratedSlide,
        design: DesignProfile,
        chart_plan: ChartPlan,
    ) -> str:
        page_type = node.page_type
        title = json.dumps(generated.title, ensure_ascii=False)
        bullets_literal = json.dumps(generated.bullets, ensure_ascii=False)
        selected_layout = generated.layout_hint or node.layout_hint or "content-two-column"
        layout_hint = json.dumps(selected_layout, ensure_ascii=False)
        chart_plan_literal = json.dumps(
            {
                "hasVerifiedData": chart_plan.has_verified_data,
                "mode": chart_plan.mode,
                "labels": chart_plan.labels,
                "values": chart_plan.values,
                "unit": chart_plan.unit,
                "note": chart_plan.note,
                "source": chart_plan.source,
            },
            ensure_ascii=False,
        )
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
                f"  chartPlan: {chart_plan_literal},",
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
                    "  const cp = slideConfig.chartPlan || { hasVerifiedData: false, labels: [], values: [], unit: '', note: '' };",
                    "  const metricRaw = cp.hasVerifiedData && cp.values.length ? String(cp.values[0]) : 'N/A';",
                    "  const metricValue = cp.hasVerifiedData ? `${metricRaw}${cp.unit || ''}` : 'N/A';",
                    "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.8, y: 1.25, w: 3.6, h: 3.75, fill: { color: theme.primary, transparency: 6 }, line: { color: theme.primary }, rectRadius: style.cornerLarge });",
                    "  slide.addText(metricValue, { x: 1.2, y: 2.08, w: 2.8, h: 1.2, fontSize: 76, fontFace: fonts.title, color: theme.bg, bold: true, align: 'center', margin: 0, fit: 'shrink' });",
                    "  slide.addText('Key Metric', { x: 1.3, y: 3.35, w: 2.6, h: 0.45, fontSize: 16, fontFace: fonts.body, color: theme.bg, bold: false, align: 'center', margin: 0 });",
                    "  if (cp.hasVerifiedData && cp.labels.length > 1 && cp.values.length > 1) {",
                    "    const labels = cp.labels.slice(0, 5);",
                    "    const values = cp.values.slice(0, labels.length);",
                    "    slide.addChart(pres.ChartType.bar, [{ name: 'Verified', labels, values }], { x: 4.9, y: 1.45, w: 4.2, h: 2.1, barDir: 'col', catAxisLabelRotate: 315, showLegend: false, showValue: true, chartColors: [theme.accent] });",
                    "    slide.addText((cp.note || '').slice(0, 120), { x: 4.95, y: 3.7, w: 4.1, h: 0.5, fontSize: 11, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'left', margin: 0, fit: 'shrink' });",
                    "  } else {",
                    "    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 4.9, y: 1.45, w: 4.2, h: 2.1, fill: { color: theme.light, transparency: 12 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                    "    slide.addText((cp.note || 'No verified numeric data; qualitative summary.').slice(0, 160), { x: 5.15, y: 1.92, w: 3.7, h: 1.0, fontSize: 13, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'left', margin: 0, fit: 'shrink' });",
                    "  }",
                    "  addBulletList(slide, bullets.slice(0, 5), { x: 4.9, y: 3.95, w: 4.2, h: 1.2, maxItems: 4, fontSize: 12 }, theme);",
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
            slide_files = sorted(
                [path for path in slides_dir.glob("slide-*.js") if re.fullmatch(r"slide-\d{2}\.js", path.name)]
            )
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
                if page_type == "content" and run.input.visual_policy == VisualPolicy.MEDIA_REQUIRED:
                    if "addImage(" not in text:
                        issues.append(f"{path.name}: visual_policy media_required expects addImage()")
                    if all(token not in text for token in ("addShape(", "addChart(")):
                        issues.append(f"{path.name}: visual_policy media_required expects shape/chart complement")
                if page_type == "content" and run.input.visual_policy == VisualPolicy.BASIC_GRAPHICS_ONLY and "addImage(" in text:
                    issues.append(f"{path.name}: visual_policy basic_graphics_only forbids addImage()")
                layout_match = re.search(r"layoutHint:\s*['\"]([^'\"]+)['\"]", text)
                if layout_match:
                    observed_layouts.append(layout_match.group(1))
                issues.extend(await self._run_slide_preview_qa(run_id=run_id, slide_js=path, slide_no=idx))
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
            template_slides = sorted(run.slides, key=lambda x: x.slide_no)
            if not template_slides:
                issues.append("template mode slide js artifacts missing")
            for artifact in template_slides:
                if not artifact.js_path:
                    issues.append(f"slide-{artifact.slide_no:02d}: js_path missing")
                    continue
                slide_js = Path(artifact.js_path)
                if not slide_js.exists():
                    issues.append(f"slide-{artifact.slide_no:02d}: js file missing")
                    continue
                issues.extend(await self._run_slide_preview_qa(run_id=run_id, slide_js=slide_js, slide_no=artifact.slide_no))

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

    async def _markitdown_extract(self, pptx_path: Path) -> tuple[str, str | None]:
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "markitdown", str(pptx_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return "", "markitdown qa failed"
        text = (result.stdout or "").strip()
        lowered = text.lower()
        if re.search(r"(xxxx|lorem|ipsum|placeholder|todo|this.*(page|slide).*layout)", lowered):
            return text, "markitdown detected placeholder text"
        if len(text) < 20:
            return text, "markitdown extracted too little content"
        return text, None

    async def _run_slide_preview_qa(self, *, run_id: str, slide_js: Path, slide_no: int) -> list[str]:
        issues, _ = await self._run_slide_preview_qa_with_text(run_id=run_id, slide_js=slide_js, slide_no=slide_no)
        return issues

    async def _run_slide_preview_qa_with_text(
        self,
        *,
        run_id: str,
        slide_js: Path,
        slide_no: int,
    ) -> tuple[list[str], str]:
        issues: list[str] = []
        preview_text = ""
        cleanup_note = "skipped"
        result = await asyncio.to_thread(
            subprocess.run,
            ["node", slide_js.name],
            cwd=slide_js.parent,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            issues.append(f"{slide_js.name}: preview compile failed")
            await self._publish(
                run_id,
                EventType.SLIDE_PREVIEW_QA,
                {
                    "slide_no": slide_no,
                    "slide_js": slide_js.name,
                    "passed": False,
                    "issues": issues,
                },
            )
            return issues, preview_text

        preview_file = slide_js.parent / f"slide-{slide_no:02d}-preview.pptx"
        if not preview_file.exists():
            issues.append(f"{slide_js.name}: preview pptx missing")
            await self._publish(
                run_id,
                EventType.SLIDE_PREVIEW_QA,
                {
                    "slide_no": slide_no,
                    "slide_js": slide_js.name,
                    "passed": False,
                    "issues": issues,
                },
            )
            return issues, preview_text

        preview_text, preview_issue = await self._markitdown_extract(preview_file)
        if preview_issue:
            issues.append(f"{slide_js.name}: {preview_issue}")
        if not self.settings.debug_keep_previews and preview_file.exists():
            preview_file.unlink(missing_ok=True)
            cleanup_note = "deleted"
        elif preview_file.exists():
            cleanup_note = "kept_by_debug"
        await self._append_artifact_cleanup_entry(
            run_id=run_id,
            entry={"slide_no": slide_no, "file": str(preview_file), "action": cleanup_note},
        )
        await self._publish(
            run_id,
            EventType.ARTIFACT_CLEANUP_COMPLETED,
            {"slide_no": slide_no, "file": str(preview_file), "action": cleanup_note},
        )
        await self._publish(
            run_id,
            EventType.SLIDE_PREVIEW_QA,
            {
                "slide_no": slide_no,
                "slide_js": slide_js.name,
                "passed": not issues,
                "issues": issues,
            },
        )
        return issues, preview_text

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
        else:
            try:
                revised_template = await self._revise_template_slides(
                    run_id=run_id,
                    design=design,
                    forced_issues=["mandatory polish cycle"],
                )
            except TemplateSlotMappingError:
                await self._fail_run(run_id, "SLIDES_GENERATING", "TEMPLATE_SLOT_UNMAPPED", retryable=False)
                return False
            except TemplateLayoutConflictError:
                await self._fail_run(run_id, "SLIDES_GENERATING", "TEMPLATE_LAYOUT_CONFLICT", retryable=False)
                return False
            if not revised_template:
                return False
        qa_ok = await self._run_skill_qa(run_id, mode=mode)

        def apply_cycle(r: RunRecord) -> None:
            cycles = int(r.qa_report.get("verification_cycles", 0))
            r.qa_report["verification_cycles"] = cycles + 1

        await self.store.update_run(run_id, apply_cycle)
        await self._append_repair_history(
            run_id=run_id,
            entry={
                "round": 0,
                "mode": mode.value,
                "source": "latest_artifacts",
                "qa_passed": qa_ok,
            },
        )
        await self._publish(
            run_id,
            EventType.REPAIR_ROUND_COMPLETED,
            {
                "round": 0,
                "mode": mode.value,
                "qa_passed": qa_ok,
                "source": "latest_artifacts",
            },
        )
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
            else:
                try:
                    revised_template = await self._revise_template_slides(
                        run_id=run_id,
                        design=design,
                        forced_issues=None,
                    )
                except TemplateSlotMappingError:
                    await self._fail_run(run_id, "SLIDES_GENERATING", "TEMPLATE_SLOT_UNMAPPED", retryable=False)
                    return False
                except TemplateLayoutConflictError:
                    await self._fail_run(run_id, "SLIDES_GENERATING", "TEMPLATE_LAYOUT_CONFLICT", retryable=False)
                    return False
                if not revised_template:
                    continue
            qa_ok = await self._run_skill_qa(run_id, mode=mode)
            await self._append_repair_history(
                run_id=run_id,
                entry={
                    "round": repair_round,
                    "mode": mode.value,
                    "source": "latest_artifacts",
                    "qa_passed": qa_ok,
                },
            )
            await self._publish(
                run_id,
                EventType.REPAIR_ROUND_COMPLETED,
                {
                    "round": repair_round,
                    "mode": mode.value,
                    "qa_passed": qa_ok,
                    "source": "latest_artifacts",
                },
            )
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
        if self._use_agentic_engine():
            for slide in sorted(run.slides, key=lambda x: x.slide_no):
                node = run.outline.nodes[slide.slide_no - 1]
                rule_issues = forced_issues or run.qa_report.get("issues", [])
                revised_js = await self.llm_client.critique_slide_js(
                    topic=run.input.topic,
                    template_style=run.input.template_style,
                    slide_no=slide.slide_no,
                    target_slide_count=run.input.target_slide_count,
                    outline_node=node,
                    candidate_js=slide.js_code,
                    issues=[str(item) for item in rule_issues],
                    visual_policy=run.input.visual_policy,
                    slide_plan=self._build_slide_plan(node=node, design=design, slide_no=slide.slide_no),
                    repair_directives=[str(item) for item in rule_issues],
                )
                slide_path = Path(run.artifact_dir) / "slides" / f"slide-{slide.slide_no:02d}.js"
                slide_path.write_text(revised_js, encoding="utf-8")
                slide.js_code = revised_js
                await self._append_quality_entry(
                    run_id=run_id,
                    entry={
                        "slide_no": slide.slide_no,
                        "passed_round": 1,
                        "issues_last_round": [str(item) for item in rule_issues],
                        "engine": self.settings.generation_engine,
                        "repair_mode": "critic_js",
                    },
                )
            return True
        for slide in sorted(run.slides, key=lambda x: x.slide_no):
            node = run.outline.nodes[slide.slide_no - 1]
            candidate = self._extract_candidate_from_js(
                js_code=slide.js_code,
                fallback_node=node,
                citations=slide.citations,
            )
            reviewed = await self.llm_client.review_slide(
                topic=run.input.topic,
                template_style=run.input.template_style,
                slide_no=slide.slide_no,
                target_slide_count=run.input.target_slide_count,
                outline_node=node,
                candidate=candidate,
                rule_violations=forced_issues or run.qa_report.get("issues", []),
            )
            chart_plan = self._build_chart_plan_from_bullets(
                node=OutlineNode(
                    title=reviewed.title,
                    bullets=list(reviewed.bullets),
                    page_type=node.page_type,
                    layout_hint=reviewed.layout_hint or node.layout_hint,
                ),
                source_refs=slide.citations,
            )
            fixed_js = self._render_skill_slide_js(
                slide_no=slide.slide_no,
                total=run.input.target_slide_count,
                node=node,
                generated=reviewed,
                design=design,
                chart_plan=chart_plan,
            )
            slide_path = Path(run.artifact_dir) / "slides" / f"slide-{slide.slide_no:02d}.js"
            slide_path.write_text(fixed_js, encoding="utf-8")
            slide.js_code = fixed_js
            await self._append_chart_truth_report(
                run_id=run_id,
                entry={
                    "slide_no": slide.slide_no,
                    "has_verified_data": chart_plan.has_verified_data,
                    "mode": chart_plan.mode,
                    "source": chart_plan.source,
                    "note": chart_plan.note,
                    "labels": chart_plan.labels,
                },
            )
        return True

    def _extract_candidate_from_js(self, *, js_code: str, fallback_node: OutlineNode, citations: list[str]) -> GeneratedSlide:
        title = self._extract_js_string_field(js_code, "title") or fallback_node.title
        layout_hint = self._extract_js_string_field(js_code, "layoutHint") or fallback_node.layout_hint
        bullets = self._extract_js_array_field(js_code, "bullets")
        if not bullets:
            bullets = list(fallback_node.bullets)
        return GeneratedSlide(
            title=title,
            bullets=bullets,
            citations=list(citations),
            page_type=fallback_node.page_type,
            layout_hint=layout_hint,
        )

    def _extract_js_string_field(self, js_code: str, field_name: str) -> str | None:
        match = re.search(rf"{re.escape(field_name)}\s*:\s*(['\"])(.*?)\1", js_code, flags=re.DOTALL)
        if not match:
            return None
        raw = match.group(2)
        try:
            return json.loads(f'"{raw}"')
        except json.JSONDecodeError:
            return raw

    def _extract_js_array_field(self, js_code: str, field_name: str) -> list[str]:
        match = re.search(rf"{re.escape(field_name)}\s*:\s*(\[[\s\S]*?\])\s*,", js_code)
        if not match:
            return []
        raw = match.group(1)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(item).strip() for item in parsed if str(item).strip()]

    async def _append_chart_truth_report(self, *, run_id: str, entry: dict[str, Any]) -> None:
        def apply(r: RunRecord) -> None:
            report = dict(r.chart_truth_report) if isinstance(r.chart_truth_report, dict) else {}
            slides = list(report.get("slides", []))
            slides = [item for item in slides if int(item.get("slide_no", -1)) != int(entry.get("slide_no", -1))]
            slides.append(entry)
            slides.sort(key=lambda item: int(item.get("slide_no", 0)))
            report["slides"] = slides
            report["passed"] = all(bool(item.get("has_verified_data", False)) for item in slides)
            r.chart_truth_report = report

        await self.store.update_run(run_id, apply)

    async def _append_quality_entry(self, *, run_id: str, entry: dict[str, Any]) -> None:
        def apply(r: RunRecord) -> None:
            report = dict(r.quality_report) if isinstance(r.quality_report, dict) else {}
            slides = list(report.get("slides", []))
            slides = [item for item in slides if int(item.get("slide_no", -1)) != int(entry.get("slide_no", -1))]
            slides.append(entry)
            slides.sort(key=lambda item: int(item.get("slide_no", 0)))
            report["slides"] = slides
            report["engine"] = self.settings.generation_engine
            report["passed"] = all(int(item.get("passed_round", 0)) > 0 for item in slides)
            r.quality_report = report

        await self.store.update_run(run_id, apply)

    async def _append_quality_gate_entry(self, *, run_id: str, entry: dict[str, Any]) -> None:
        def apply(r: RunRecord) -> None:
            report = dict(r.quality_gate_report) if isinstance(r.quality_gate_report, dict) else {}
            rounds = list(report.get("rounds", []))
            rounds.append(entry)
            report["rounds"] = rounds
            threshold = int(entry.get("threshold", 80))
            report["threshold"] = threshold
            latest_by_slide: dict[int, dict[str, Any]] = {}
            for item in rounds:
                slide_no = int(item.get("slide_no", 0))
                prev = latest_by_slide.get(slide_no)
                if prev is None or int(item.get("round", 0)) >= int(prev.get("round", 0)):
                    latest_by_slide[slide_no] = item
            report["passed"] = bool(latest_by_slide) and all(bool(item.get("passed", False)) for item in latest_by_slide.values())
            r.quality_gate_report = report

        await self.store.update_run(run_id, apply)

    async def _append_candidate_selection_entry(self, *, run_id: str, entry: dict[str, Any]) -> None:
        def apply(r: RunRecord) -> None:
            report = dict(r.candidate_selection_report) if isinstance(r.candidate_selection_report, dict) else {}
            rounds = list(report.get("rounds", []))
            rounds.append(entry)
            report["rounds"] = rounds
            by_slide: dict[int, dict[str, Any]] = {}
            for item in rounds:
                slide_no = int(item.get("slide_no", 0))
                prev = by_slide.get(slide_no)
                if prev is None or int(item.get("round", 0)) >= int(prev.get("round", 0)):
                    by_slide[slide_no] = item
            report["final_by_slide"] = [by_slide[key] for key in sorted(by_slide)]
            r.candidate_selection_report = report

        await self.store.update_run(run_id, apply)

    async def _append_artifact_cleanup_entry(self, *, run_id: str, entry: dict[str, Any]) -> None:
        def apply(r: RunRecord) -> None:
            report = dict(r.artifact_cleanup_report) if isinstance(r.artifact_cleanup_report, dict) else {}
            items = list(report.get("items", []))
            items.append(entry)
            report["items"] = items
            report["deleted_count"] = sum(1 for item in items if item.get("action") == "deleted")
            report["kept_count"] = sum(1 for item in items if item.get("action") == "kept_by_debug")
            r.artifact_cleanup_report = report

        await self.store.update_run(run_id, apply)

    async def _append_repair_history(self, *, run_id: str, entry: dict[str, Any]) -> None:
        def apply(r: RunRecord) -> None:
            history = list(r.repair_history)
            history.append(entry)
            r.repair_history = history

        await self.store.update_run(run_id, apply)

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
                if src_rel.resolve() != dst_rel_file.resolve():
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

    def _build_slot_graph(self, *, slide_xml: Path, slide_no: int) -> SlotGraph:
        text = slide_xml.read_text(encoding="utf-8", errors="ignore")
        graph = SlotGraph(slide_no=slide_no, slots=[])
        placeholder_re = re.compile(
            r"(placeholder|lorem|ipsum|xxxx|template|caption|insert|click to add|text here|your text)",
            flags=re.IGNORECASE,
        )
        text_hits = re.findall(r"<a:t>(.*?)</a:t>", text, flags=re.DOTALL)
        for idx, raw in enumerate(text_hits, start=1):
            plain = self._xml_unescape(raw).strip()
            if not plain:
                continue
            if not placeholder_re.search(plain):
                continue
            lowered = plain.lower()
            slot_type = "caption" if "caption" in lowered else "text"
            graph.slots.append(
                SlotNode(
                    slot_id=f"text-{idx}",
                    slot_type=slot_type,
                    required=True,
                    hint=plain,
                    group_id=f"text-{idx}",
                )
            )

        picture_slots = self._extract_picture_slots(text)
        for idx, slot in enumerate(picture_slots, start=1):
            graph.slots.append(
                SlotNode(
                    slot_id=f"pic-{idx}",
                    slot_type=str(slot["slot_type"]),
                    required=True,
                    rel_id=str(slot["rel_id"]),
                    hint=str(slot["slot_type"]),
                    group_id=f"pic-{idx}",
                )
            )

        rels_path = slide_xml.parent / "_rels" / f"{slide_xml.name}.rels"
        if rels_path.exists():
            rels_text = rels_path.read_text(encoding="utf-8", errors="ignore")
            chart_idx = 0
            for tag in re.findall(r"<Relationship\b[^>]*/>", rels_text):
                attrs = self._parse_xml_attrs(tag)
                rel_type = attrs.get("Type", "")
                rel_id = attrs.get("Id", "")
                if rel_type.endswith("/chart") and rel_id:
                    chart_idx += 1
                    graph.slots.append(
                        SlotNode(
                            slot_id=f"chart-{chart_idx}",
                            slot_type="chart",
                            required=True,
                            rel_id=rel_id,
                            hint="chart",
                            group_id=f"chart-{chart_idx}",
                        )
                    )

        known_ids = {slot.rel_id for slot in graph.slots if slot.rel_id}
        for idx, tag in enumerate(re.findall(r"<p:cNvPr\b[^>]*/>", text), start=1):
            attrs = self._parse_xml_attrs(tag)
            name = attrs.get("name", "")
            descr = attrs.get("descr", "")
            hint = f"{name} {descr}".strip()
            hint_lower = hint.lower()
            if not hint or not placeholder_re.search(hint):
                continue
            if any(word in hint_lower for word in ("text", "caption")):
                continue
            if any(word in hint_lower for word in ("image", "icon", "logo", "chart")):
                continue
            slot_id = attrs.get("id", f"unknown-{idx}")
            if slot_id in known_ids:
                continue
            graph.slots.append(
                SlotNode(
                    slot_id=f"unknown-{slot_id}",
                    slot_type="unknown",
                    required=True,
                    hint=hint,
                    group_id=f"unknown-{slot_id}",
                )
            )
        return graph

    def _plan_slot_mapping(self, *, slot_graph: SlotGraph) -> dict[str, Any]:
        slots: list[dict[str, Any]] = []
        for slot in slot_graph.slots:
            mapped = slot.slot_type in {"text", "caption", "image", "icon", "logo", "chart"}
            reason = "" if mapped else "unsupported placeholder type"
            slots.append(
                {
                    "slot_id": slot.slot_id,
                    "slot_type": slot.slot_type,
                    "required": slot.required,
                    "mapped": mapped,
                    "reason": reason,
                    "hint": slot.hint,
                    "rel_id": slot.rel_id,
                    "group_id": slot.group_id,
                }
            )
        return {"slide_no": slot_graph.slide_no, "slots": slots}

    def _build_chart_plan_from_bullets(self, *, node: OutlineNode, source_refs: list[str]) -> ChartPlan:
        facts = self._extract_chart_facts(node=node, source_refs=source_refs)
        if facts:
            labels = [item.label for item in facts[:6]]
            values = [item.value for item in facts[:6]]
            unit = facts[0].unit
            return ChartPlan(
                has_verified_data=True,
                mode="quantitative",
                labels=labels,
                values=values,
                unit=unit,
                note="",
                source="outline_facts",
            )
        labels = [item[:28] for item in (node.bullets[:5] or [node.title])]
        return ChartPlan(
            has_verified_data=False,
            mode="qualitative_fallback",
            labels=labels,
            values=[1.0 for _ in labels],
            unit="",
            note="No verified numeric data; qualitative visual applied.",
            source="qualitative_fallback",
        )

    def _extract_chart_facts(self, *, node: OutlineNode, source_refs: list[str]) -> list[ChartFact]:
        facts: list[ChartFact] = []
        colon_re = re.compile(
            r"(?P<label>[^:：]{1,60})[:：]\s*(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>%|万元|万|亿|k|m|b|人|次|个)?",
            flags=re.IGNORECASE,
        )
        unit_re = re.compile(
            r"(?P<label>[^0-9]{1,60}?)(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>%|万元|万|亿|k|m|b|人|次|个)",
            flags=re.IGNORECASE,
        )
        source = source_refs[0] if source_refs else "user_outline"
        for bullet in node.bullets:
            text = bullet.strip()
            if not text:
                continue
            match = colon_re.search(text)
            if not match:
                match = unit_re.search(text)
            if not match:
                continue
            label = match.group("label").strip(" -:：") or node.title
            raw_value = match.group("value")
            try:
                value = float(raw_value)
            except ValueError:
                continue
            unit = (match.group("unit") or "").strip()
            facts.append(
                ChartFact(
                    label=label[:40],
                    value=value,
                    unit=unit,
                    source_ref=source,
                )
            )
        return facts

    def _rewrite_template_slide_semantics(
        self,
        *,
        unpacked: Path,
        slide_xml: Path,
        node: OutlineNode,
        slide_no: int,
        chart_plan: ChartPlan,
    ) -> dict[str, Any]:
        content = slide_xml.read_text(encoding="utf-8", errors="ignore")
        content = self._rewrite_template_text_runs(content=content, node=node)
        content = self._rewrite_template_table_cells(content=content, node=node)
        content = self._rewrite_template_media_metadata(content=content, node=node, slide_no=slide_no)
        slide_xml.write_text(content, encoding="utf-8")
        self._rewrite_template_image_icon_assets(unpacked=unpacked, slide_xml=slide_xml, node=node, slide_no=slide_no)
        chart_report = self._rewrite_related_chart_xml(
            unpacked=unpacked,
            slide_xml=slide_xml,
            node=node,
            chart_plan=chart_plan,
        )
        layout_report = self._analyze_and_reflow_template_layout(slide_xml=slide_xml, slide_no=slide_no)
        return {"chart": chart_report, "layout": layout_report}

    def _rewrite_template_text_runs(self, *, content: str, node: OutlineNode) -> str:
        replacements = [node.title] + node.bullets
        matches = list(re.finditer(r"<a:t>.*?</a:t>", content, flags=re.DOTALL))
        if not matches:
            return content

        placeholder_re = re.compile(
            r"(placeholder|lorem|ipsum|xxxx|template|caption|insert|click to add|text here|your text)",
            flags=re.IGNORECASE,
        )
        has_explicit_placeholder = False
        for match in matches:
            inner = re.sub(r"^<a:t>|</a:t>$", "", match.group(0), flags=re.DOTALL)
            inner_plain = re.sub(r"<[^>]+>", "", inner).strip()
            if placeholder_re.search(inner_plain):
                has_explicit_placeholder = True
                break
        out: list[str] = []
        cursor = 0
        replacement_idx = 0
        for match in matches:
            out.append(content[cursor:match.start()])
            segment = match.group(0)
            inner = re.sub(r"^<a:t>|</a:t>$", "", segment, flags=re.DOTALL)
            inner_plain = re.sub(r"<[^>]+>", "", inner).strip()

            use_replacement = replacement_idx < len(replacements)
            if has_explicit_placeholder:
                use_replacement = use_replacement and bool(placeholder_re.search(inner_plain))
            if use_replacement:
                replacement = replacements[replacement_idx]
                out.append(f"<a:t>{self._xml_escape(replacement)}</a:t>")
                replacement_idx += 1
            else:
                out.append(segment)
            cursor = match.end()
        out.append(content[cursor:])
        return "".join(out)

    def _rewrite_template_table_cells(self, *, content: str, node: OutlineNode) -> str:
        bullets = node.bullets or [node.title]
        bullet_iter = iter(bullets)

        def replace_table(match: re.Match[str]) -> str:
            block = match.group(0)

            def repl_text(text_match: re.Match[str]) -> str:
                current = text_match.group(1)
                if re.search(r"(placeholder|lorem|ipsum|xxxx|template|caption|insert)", current, flags=re.IGNORECASE):
                    value = next(bullet_iter, node.title)
                    return f"<a:t>{self._xml_escape(value)}</a:t>"
                return text_match.group(0)

            return re.sub(r"<a:t>(.*?)</a:t>", repl_text, block, flags=re.DOTALL)

        return re.sub(r"<a:tbl>[\s\S]*?</a:tbl>", replace_table, content, flags=re.DOTALL)

    def _rewrite_template_media_metadata(self, *, content: str, node: OutlineNode, slide_no: int) -> str:
        def repl_cnvpr(match: re.Match[str]) -> str:
            tag = match.group(0)
            attrs = self._parse_xml_attrs(tag)
            name = attrs.get("name", "")
            descr = attrs.get("descr", "")
            hint = f"{name} {descr}".lower()
            looks_media = any(word in hint for word in ("pic", "image", "icon", "logo", "placeholder", "template"))
            if not looks_media:
                return tag

            if "icon" in hint:
                semantic = f"{node.title} icon"
            elif "logo" in hint:
                semantic = f"{node.title} logo"
            else:
                semantic = f"{node.title} image"
            caption = node.bullets[0] if node.bullets else node.title
            attrs["name"] = semantic[:80]
            attrs["descr"] = caption[:160]
            attrs_str = " ".join(f'{k}="{self._xml_attr_escape(v)}"' for k, v in attrs.items())
            return f"<p:cNvPr {attrs_str}/>"

        content = re.sub(r"<p:cNvPr\b[^>]*/>", repl_cnvpr, content)

        # Replace obvious caption placeholders.
        caption_re = re.compile(r"<a:t>(.*?)</a:t>", flags=re.DOTALL | re.IGNORECASE)

        def repl_caption(match: re.Match[str]) -> str:
            text = match.group(1).strip()
            if re.search(r"(caption|placeholder|lorem|ipsum|xxxx)", text, flags=re.IGNORECASE):
                caption = node.bullets[min(slide_no - 1, max(len(node.bullets) - 1, 0))] if node.bullets else node.title
                return f"<a:t>{self._xml_escape(caption)}</a:t>"
            return match.group(0)

        return caption_re.sub(repl_caption, content)

    def _rewrite_template_image_icon_assets(self, *, unpacked: Path, slide_xml: Path, node: OutlineNode, slide_no: int) -> None:
        slide_text = slide_xml.read_text(encoding="utf-8", errors="ignore")
        slots = self._extract_picture_slots(slide_text)
        if not slots:
            return

        desired_slots = min(max(1, len(node.bullets) if node.bullets else 1), len(slots))
        keep_slots = slots[:desired_slots]
        drop_slots = slots[desired_slots:]
        drop_ids = {item["rel_id"] for item in drop_slots}
        keep_slot_map = {item["rel_id"]: item["slot_type"] for item in keep_slots}

        if drop_slots:
            ranges = [(item["start"], item["end"]) for item in drop_slots]
            slide_text = self._remove_ranges(slide_text, ranges)
            slide_xml.write_text(slide_text, encoding="utf-8")

        rels_path = slide_xml.parent / "_rels" / f"{slide_xml.name}.rels"
        if not rels_path.exists():
            return

        rels_text = rels_path.read_text(encoding="utf-8", errors="ignore")
        tags = list(re.finditer(r"<Relationship\b[^>]*/>", rels_text))
        if not tags:
            return

        media_dir = unpacked / "ppt" / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        out: list[str] = []
        cursor = 0
        replaced_any = False
        seen_exts: set[str] = set()
        for tag_match in tags:
            out.append(rels_text[cursor:tag_match.start()])
            tag = tag_match.group(0)
            attrs = self._parse_xml_attrs(tag)
            rel_id = attrs.get("Id", "")
            rel_type = attrs.get("Type", "")
            target = attrs.get("Target", "")

            if rel_id in drop_ids and rel_type.endswith("/image"):
                replaced_any = True
                cursor = tag_match.end()
                continue

            should_replace = rel_type.endswith("/image") and bool(target) and (
                rel_id in keep_slot_map or any(word in target.lower() for word in ("placeholder", "template", "image", "icon", "logo"))
            )
            if not should_replace:
                out.append(tag)
                cursor = tag_match.end()
                continue

            slot_type = keep_slot_map.get(rel_id, "image")
            query = self._build_asset_query(node=node, slot_type=slot_type, slide_no=slide_no)
            asset_bytes, ext = self._fetch_slot_asset(
                query=query,
                slot_type=slot_type,
                node=node,
                slide_no=slide_no,
                rel_id=rel_id,
            )
            filename = f"slot-s{slide_no:02d}-{rel_id.lower() or 'img'}-{slot_type}.{ext}"
            target_file = media_dir / filename
            target_file.write_bytes(asset_bytes)
            attrs["Target"] = self._relative_target(from_dir=slide_xml.parent, to_path=target_file)
            attrs_str = " ".join(f'{k}="{self._xml_attr_escape(v)}"' for k, v in attrs.items())
            out.append(f"<Relationship {attrs_str}/>")
            replaced_any = True
            seen_exts.add(ext)
            cursor = tag_match.end()
        out.append(rels_text[cursor:])

        if replaced_any:
            rels_path.write_text("".join(out), encoding="utf-8")
            self._ensure_image_content_types(unpacked=unpacked, exts=seen_exts)

    def _extract_picture_slots(self, slide_text: str) -> list[dict[str, Any]]:
        slots: list[dict[str, Any]] = []
        for match in re.finditer(r"<p:pic\b[\s\S]*?</p:pic>", slide_text):
            block = match.group(0)
            blip = re.search(r"<a:blip\b[^>]*r:embed=\"([^\"]+)\"", block)
            if not blip:
                continue
            rel_id = blip.group(1)
            cnvpr = re.search(r"<p:cNvPr\b[^>]*/>", block)
            hint = ""
            if cnvpr:
                attrs = self._parse_xml_attrs(cnvpr.group(0))
                hint = f"{attrs.get('name', '')} {attrs.get('descr', '')}".lower()
            if "icon" in hint:
                slot_type = "icon"
            elif "logo" in hint:
                slot_type = "logo"
            else:
                slot_type = "image"
            slots.append(
                {
                    "rel_id": rel_id,
                    "slot_type": slot_type,
                    "start": match.start(),
                    "end": match.end(),
                }
            )
        return slots

    def _remove_ranges(self, text: str, ranges: list[tuple[int, int]]) -> str:
        if not ranges:
            return text
        normalized = sorted(ranges, key=lambda item: item[0])
        out: list[str] = []
        cursor = 0
        for start, end in normalized:
            out.append(text[cursor:start])
            cursor = max(cursor, end)
        out.append(text[cursor:])
        return "".join(out)

    def _build_asset_query(self, *, node: OutlineNode, slot_type: str, slide_no: int) -> str:
        head = node.title.strip() or f"slide {slide_no}"
        tail = node.bullets[0].strip() if node.bullets else ""
        if slot_type == "icon":
            return f"{head} {tail} flat icon"
        if slot_type == "logo":
            return f"{head} {tail} company logo"
        return f"{head} {tail} presentation photo"

    def _fetch_slot_asset(self, *, query: str, slot_type: str, node: OutlineNode, slide_no: int, rel_id: str) -> tuple[bytes, str]:
        provider = self.settings.asset_provider.lower().strip()
        if provider == "mock":
            return self._build_slot_png_bytes(node=node, slot_type=slot_type, slide_no=slide_no, rel_id=rel_id), "png"
        if provider == "none":
            raise TemplateAssetError("asset provider is disabled")

        providers = self._asset_provider_chain(provider)
        if not providers:
            raise TemplateAssetError(f"no configured asset providers for {provider}")

        last_error: Exception | None = None
        for name in providers:
            for _ in range(max(1, self.settings.asset_max_retries)):
                try:
                    if name == "unsplash":
                        return self._fetch_unsplash_asset(query=query, slot_type=slot_type)
                    if name == "pexels":
                        return self._fetch_pexels_asset(query=query, slot_type=slot_type)
                except Exception as exc:  # noqa: PERF203
                    last_error = exc
                    continue
        raise TemplateAssetError(f"asset fetch failed for query={query!r}: {last_error}")

    def _asset_provider_chain(self, provider: str) -> list[str]:
        if provider == "unsplash":
            return ["unsplash"]
        if provider == "pexels":
            return ["pexels"]
        if provider == "auto":
            order: list[str] = []
            if self.settings.unsplash_access_key:
                order.append("unsplash")
            if self.settings.pexels_api_key:
                order.append("pexels")
            return order
        return []

    def _fetch_unsplash_asset(self, *, query: str, slot_type: str) -> tuple[bytes, str]:
        key = self.settings.unsplash_access_key.strip()
        if not key:
            raise TemplateAssetError("missing UNSPLASH_ACCESS_KEY")
        orientation = "landscape" if slot_type == "image" else "squarish"
        with httpx.Client(timeout=self.settings.asset_timeout_sec, follow_redirects=True) as client:
            resp = client.get(
                "https://api.unsplash.com/search/photos",
                params={"query": query, "per_page": 1, "orientation": orientation},
                headers={"Authorization": f"Client-ID {key}"},
            )
            resp.raise_for_status()
            payload = resp.json()
            results = payload.get("results", []) if isinstance(payload, dict) else []
            if not results:
                raise TemplateAssetError("unsplash returned no results")
            first = results[0] if isinstance(results[0], dict) else {}
            urls = first.get("urls", {}) if isinstance(first, dict) else {}
            image_url = urls.get("regular") or urls.get("full") or urls.get("small")
            if not image_url:
                raise TemplateAssetError("unsplash response missing image url")
            return self._download_asset(client=client, url=str(image_url))

    def _fetch_pexels_asset(self, *, query: str, slot_type: str) -> tuple[bytes, str]:
        key = self.settings.pexels_api_key.strip()
        if not key:
            raise TemplateAssetError("missing PEXELS_API_KEY")
        orientation = "landscape" if slot_type == "image" else "square"
        with httpx.Client(timeout=self.settings.asset_timeout_sec, follow_redirects=True) as client:
            resp = client.get(
                "https://api.pexels.com/v1/search",
                params={"query": query, "per_page": 1, "orientation": orientation},
                headers={"Authorization": key},
            )
            resp.raise_for_status()
            payload = resp.json()
            photos = payload.get("photos", []) if isinstance(payload, dict) else []
            if not photos:
                raise TemplateAssetError("pexels returned no results")
            first = photos[0] if isinstance(photos[0], dict) else {}
            src = first.get("src", {}) if isinstance(first, dict) else {}
            image_url = src.get("large2x") or src.get("large") or src.get("original")
            if not image_url:
                raise TemplateAssetError("pexels response missing image url")
            return self._download_asset(client=client, url=str(image_url))

    def _download_asset(self, *, client: httpx.Client, url: str) -> tuple[bytes, str]:
        resp = client.get(url)
        resp.raise_for_status()
        content = resp.content
        if not content:
            raise TemplateAssetError("downloaded asset is empty")
        ext = self._guess_image_ext(content_type=resp.headers.get("content-type", ""), url=url)
        return content, ext

    def _guess_image_ext(self, *, content_type: str, url: str) -> str:
        lowered = content_type.lower()
        if "png" in lowered:
            return "png"
        if "jpeg" in lowered or "jpg" in lowered:
            return "jpg"
        if "webp" in lowered:
            return "webp"
        suffix = Path(url.split("?", 1)[0]).suffix.lower().lstrip(".")
        if suffix in {"png", "jpg", "jpeg", "webp"}:
            return "jpg" if suffix == "jpeg" else suffix
        return "jpg"

    def _build_slot_png_bytes(self, *, node: OutlineNode, slot_type: str, slide_no: int, rel_id: str) -> bytes:
        key = f"{node.title}|{slot_type}|{slide_no}|{rel_id}".encode("utf-8", errors="ignore")
        seed = zlib.crc32(key) & 0xFFFFFFFF
        r = 40 + (seed & 0x7F)
        g = 40 + ((seed >> 8) & 0x7F)
        b = 40 + ((seed >> 16) & 0x7F)
        width = 96
        height = 96
        row = bytes([0]) + bytes([r, g, b] * width)
        raw = row * height
        compressed = zlib.compress(raw, level=9)

        def chunk(tag: bytes, payload: bytes) -> bytes:
            body = tag + payload
            return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")

    def _ensure_image_content_types(self, *, unpacked: Path, exts: set[str]) -> None:
        if not exts:
            return
        content_types_path = unpacked / "[Content_Types].xml"
        if not content_types_path.exists():
            return
        text = content_types_path.read_text(encoding="utf-8", errors="ignore")
        content_map = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "webp": "image/webp",
        }
        changed = False
        for ext in sorted(exts):
            if ext not in content_map:
                continue
            if re.search(rf'<Default\b[^>]*Extension="{re.escape(ext)}"[^>]*/>', text):
                continue
            text = text.replace(
                "</Types>",
                f'  <Default Extension="{ext}" ContentType="{content_map[ext]}"/>\n</Types>',
            )
            changed = True
        if changed:
            content_types_path.write_text(text, encoding="utf-8")

    def _relative_target(self, *, from_dir: Path, to_path: Path) -> str:
        return Path(os.path.relpath(to_path, from_dir)).as_posix()

    def _rewrite_related_chart_xml(
        self,
        *,
        unpacked: Path,
        slide_xml: Path,
        node: OutlineNode,
        chart_plan: ChartPlan,
    ) -> dict[str, Any]:
        rels_path = slide_xml.parent / "_rels" / f"{slide_xml.name}.rels"
        if not rels_path.exists():
            return {"has_chart_slot": False, "has_verified_data": chart_plan.has_verified_data, "mode": "none", "source": chart_plan.source}
        rels_text = rels_path.read_text(encoding="utf-8", errors="ignore")
        chart_targets: list[str] = []
        for tag in re.findall(r"<Relationship\b[^>]*/>", rels_text):
            attrs = self._parse_xml_attrs(tag)
            rel_type = attrs.get("Type", "")
            target = attrs.get("Target", "")
            if rel_type.endswith("/chart") and target:
                chart_targets.append(target)
        if not chart_targets:
            return {"has_chart_slot": False, "has_verified_data": chart_plan.has_verified_data, "mode": "none", "source": chart_plan.source}
        report = {
            "has_chart_slot": True,
            "has_verified_data": chart_plan.has_verified_data,
            "mode": chart_plan.mode,
            "source": chart_plan.source,
            "note": chart_plan.note,
            "labels": chart_plan.labels,
        }
        for target in chart_targets:
            chart_path = (slide_xml.parent / target).resolve()
            try:
                chart_path.relative_to(unpacked.resolve())
            except ValueError:
                continue
            if not chart_path.exists():
                continue
            chart_xml = chart_path.read_text(encoding="utf-8", errors="ignore")
            chart_xml = self._rewrite_chart_xml_content(
                chart_xml=chart_xml,
                node=node,
                chart_plan=chart_plan,
            )
            chart_path.write_text(chart_xml, encoding="utf-8")
        return report

    def _rewrite_chart_xml_content(self, *, chart_xml: str, node: OutlineNode, chart_plan: ChartPlan) -> str:
        chart_xml = re.sub(
            r"<a:t>.*?</a:t>",
            f"<a:t>{self._xml_escape(node.title)}</a:t>",
            chart_xml,
            count=1,
            flags=re.DOTALL,
        )
        categories = chart_plan.labels[:5] or [node.title]
        values = [str(value).rstrip("0").rstrip(".") for value in chart_plan.values[: len(categories)]]
        if len(values) < len(categories):
            values.extend(["1" for _ in range(len(categories) - len(values))])
        chart_xml = self._rewrite_chart_cache_points(
            chart_xml=chart_xml,
            cache_tag="c:strCache",
            value_tag="c:v",
            values=categories,
        )
        chart_xml = self._rewrite_chart_cache_points(
            chart_xml=chart_xml,
            cache_tag="c:numCache",
            value_tag="c:v",
            values=values,
        )
        return chart_xml

    def _rewrite_chart_cache_points(
        self,
        *,
        chart_xml: str,
        cache_tag: str,
        value_tag: str,
        values: list[str],
    ) -> str:
        pattern = rf"<{cache_tag}>[\s\S]*?</{cache_tag}>"

        def repl(match: re.Match[str]) -> str:
            block = match.group(0)
            pt_pattern = re.compile(rf"<c:pt\b[^>]*idx=\"(\d+)\"[^>]*>[\s\S]*?<c:v>.*?</c:v>[\s\S]*?</c:pt>")
            pts = list(pt_pattern.finditer(block))
            if not pts:
                return block
            out: list[str] = []
            cursor = 0
            for idx, pt in enumerate(pts):
                out.append(block[cursor:pt.start()])
                value = values[idx] if idx < len(values) else values[-1]
                out.append(
                    re.sub(
                        r"<c:v>.*?</c:v>",
                        f"<c:v>{self._xml_escape(value)}</c:v>",
                        pt.group(0),
                        flags=re.DOTALL,
                    )
                )
                cursor = pt.end()
            out.append(block[cursor:])
            rebuilt = "".join(out)
            rebuilt = re.sub(
                r"<c:ptCount\b[^>]*/>",
                f'<c:ptCount val="{len(pts)}"/>',
                rebuilt,
                count=1,
            )
            return rebuilt

        return re.sub(pattern, repl, chart_xml)

    def _analyze_and_reflow_template_layout(self, *, slide_xml: Path, slide_no: int) -> dict[str, Any]:
        content = slide_xml.read_text(encoding="utf-8", errors="ignore")
        boxes_before = self._extract_layout_boxes(content)
        before = self._collect_layout_issues(boxes_before)
        if not boxes_before:
            return {
                "slide_no": slide_no,
                "box_count": 0,
                "moved_count": 0,
                "issues_before_count": 0,
                "issues_after_count": 0,
                "issues_before": [],
                "issues_after": [],
                "fidelity_score": 100,
                "passed": True,
            }

        rewritten, moved_count = self._reflow_layout_boxes(content=content, boxes=boxes_before)
        if moved_count:
            slide_xml.write_text(rewritten, encoding="utf-8")
            boxes_after = self._extract_layout_boxes(rewritten)
        else:
            boxes_after = boxes_before
        after = self._collect_layout_issues(boxes_after)
        fidelity_score = self._compute_template_fidelity_score(
            box_count=len(boxes_before),
            moved_count=moved_count,
            issues_after_count=len(after["issues"]),
        )
        return {
            "slide_no": slide_no,
            "box_count": len(boxes_before),
            "moved_count": moved_count,
            "issues_before_count": len(before["issues"]),
            "issues_after_count": len(after["issues"]),
            "issues_before": before["issues"],
            "issues_after": after["issues"],
            "fidelity_score": fidelity_score,
            "passed": not after["issues"],
        }

    def _extract_layout_boxes(self, content: str) -> list[LayoutBox]:
        boxes: list[LayoutBox] = []
        pattern = re.compile(r"<p:(sp|pic|graphicFrame)\b[\s\S]*?</p:\1>")
        for match in pattern.finditer(content):
            xml_tag = match.group(1)
            block = match.group(0)
            xfrm = re.search(r"<a:xfrm\b[^>]*>([\s\S]*?)</a:xfrm>", block)
            if not xfrm:
                continue
            xfrm_body = xfrm.group(1)
            off = re.search(r"<a:off\b[^>]*/>", xfrm_body)
            ext = re.search(r"<a:ext\b[^>]*/>", xfrm_body)
            if not off or not ext:
                continue
            off_attrs = self._parse_xml_attrs(off.group(0))
            ext_attrs = self._parse_xml_attrs(ext.group(0))
            try:
                x_emu = int(off_attrs.get("x", "0"))
                y_emu = int(off_attrs.get("y", "0"))
                w_emu = int(ext_attrs.get("cx", "0"))
                h_emu = int(ext_attrs.get("cy", "0"))
            except ValueError:
                continue
            if w_emu <= 0 or h_emu <= 0:
                continue
            rel_match = re.search(r"<a:blip\b[^>]*r:embed=\"([^\"]+)\"", block)
            rel_id = rel_match.group(1) if rel_match else None
            cnvpr = re.search(r"<p:cNvPr\b[^>]*/>", block)
            element_id = None
            if cnvpr:
                attrs = self._parse_xml_attrs(cnvpr.group(0))
                element_id = attrs.get("id") or attrs.get("name")
            element_type = self._layout_element_type(xml_tag=xml_tag, block=block)
            boxes.append(
                LayoutBox(
                    element_type=element_type,
                    xml_tag=xml_tag,
                    block_start=match.start(),
                    block_end=match.end(),
                    x_emu=x_emu,
                    y_emu=y_emu,
                    w_emu=w_emu,
                    h_emu=h_emu,
                    rel_id=rel_id,
                    element_id=element_id,
                )
            )
        return boxes

    def _layout_element_type(self, *, xml_tag: str, block: str) -> str:
        if xml_tag == "pic":
            hint = ""
            cnvpr = re.search(r"<p:cNvPr\b[^>]*/>", block)
            if cnvpr:
                attrs = self._parse_xml_attrs(cnvpr.group(0))
                hint = f"{attrs.get('name', '')} {attrs.get('descr', '')}".lower()
            if "icon" in hint:
                return "icon"
            if "logo" in hint:
                return "logo"
            return "image"
        if xml_tag == "graphicFrame":
            lowered = block.lower()
            if "<a:tbl" in lowered:
                return "table"
            if "chart" in lowered:
                return "chart"
            return "graphic"
        if "<p:txBody" in block:
            return "text"
        return "shape"

    def _collect_layout_issues(self, boxes: list[LayoutBox]) -> dict[str, Any]:
        issues: list[str] = []
        for idx, box in enumerate(boxes, start=1):
            if box.x_emu < 0 or box.y_emu < 0:
                issues.append(f"box-{idx} negative position")
                continue
            if box.x_emu + box.w_emu > SLIDE_WIDTH_EMU or box.y_emu + box.h_emu > SLIDE_HEIGHT_EMU:
                issues.append(f"box-{idx} out of slide bounds")
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if self._boxes_overlap_significantly(boxes[i], boxes[j]):
                    issues.append(f"box-{i + 1} overlaps box-{j + 1}")
        return {"issues": issues}

    def _boxes_overlap_significantly(self, left: LayoutBox, right: LayoutBox) -> bool:
        x_overlap = max(0, min(left.x_emu + left.w_emu, right.x_emu + right.w_emu) - max(left.x_emu, right.x_emu))
        y_overlap = max(0, min(left.y_emu + left.h_emu, right.y_emu + right.h_emu) - max(left.y_emu, right.y_emu))
        if x_overlap <= 0 or y_overlap <= 0:
            return False
        overlap_area = x_overlap * y_overlap
        min_area = min(left.w_emu * left.h_emu, right.w_emu * right.h_emu)
        if min_area <= 0:
            return False
        return overlap_area / min_area >= 0.08

    def _reflow_layout_boxes(self, *, content: str, boxes: list[LayoutBox]) -> tuple[str, int]:
        if not boxes:
            return content, 0
        gap = 120_000
        ordered = sorted(range(len(boxes)), key=lambda idx: (boxes[idx].y_emu, boxes[idx].x_emu))
        adjusted: list[tuple[int, int, int, int]] = [(b.x_emu, b.y_emu, b.w_emu, b.h_emu) for b in boxes]
        placed: list[tuple[int, int, int, int]] = []
        moved_count = 0

        for idx in ordered:
            x_emu, y_emu, w_emu, h_emu = adjusted[idx]
            if w_emu > SLIDE_WIDTH_EMU or h_emu > SLIDE_HEIGHT_EMU:
                placed.append((x_emu, y_emu, w_emu, h_emu))
                continue
            x_emu = min(max(0, x_emu), SLIDE_WIDTH_EMU - w_emu)
            y_emu = min(max(0, y_emu), SLIDE_HEIGHT_EMU - h_emu)
            attempts = 0
            while attempts < 24:
                overlaps = [
                    item
                    for item in placed
                    if self._rect_overlap_significant(
                        x_emu=x_emu,
                        y_emu=y_emu,
                        w_emu=w_emu,
                        h_emu=h_emu,
                        other=item,
                    )
                ]
                if not overlaps:
                    break
                lowest_bottom = max(other[1] + other[3] for other in overlaps)
                candidate_y = lowest_bottom + gap
                if candidate_y + h_emu > SLIDE_HEIGHT_EMU:
                    break
                y_emu = candidate_y
                attempts += 1
            adjusted[idx] = (x_emu, y_emu, w_emu, h_emu)
            placed.append((x_emu, y_emu, w_emu, h_emu))
            if x_emu != boxes[idx].x_emu or y_emu != boxes[idx].y_emu:
                moved_count += 1

        if moved_count == 0:
            return content, 0
        updates: list[tuple[int, int, str]] = []
        for idx, box in enumerate(boxes):
            x_emu, y_emu, _, _ = adjusted[idx]
            if x_emu == box.x_emu and y_emu == box.y_emu:
                continue
            block = content[box.block_start:box.block_end]
            rewritten = self._rewrite_box_off_tag(block=block, x_emu=x_emu, y_emu=y_emu)
            updates.append((box.block_start, box.block_end, rewritten))
        if not updates:
            return content, 0
        updates.sort(key=lambda item: item[0])
        out: list[str] = []
        cursor = 0
        for start, end, payload in updates:
            out.append(content[cursor:start])
            out.append(payload)
            cursor = end
        out.append(content[cursor:])
        return "".join(out), moved_count

    def _rect_overlap_significant(
        self,
        *,
        x_emu: int,
        y_emu: int,
        w_emu: int,
        h_emu: int,
        other: tuple[int, int, int, int],
    ) -> bool:
        ox, oy, ow, oh = other
        x_overlap = max(0, min(x_emu + w_emu, ox + ow) - max(x_emu, ox))
        y_overlap = max(0, min(y_emu + h_emu, oy + oh) - max(y_emu, oy))
        if x_overlap <= 0 or y_overlap <= 0:
            return False
        overlap_area = x_overlap * y_overlap
        min_area = min(w_emu * h_emu, ow * oh)
        if min_area <= 0:
            return False
        return overlap_area / min_area >= 0.08

    def _rewrite_box_off_tag(self, *, block: str, x_emu: int, y_emu: int) -> str:
        def repl(match: re.Match[str]) -> str:
            attrs = self._parse_xml_attrs(match.group(0))
            attrs["x"] = str(x_emu)
            attrs["y"] = str(y_emu)
            attrs_str = " ".join(f'{key}="{self._xml_attr_escape(value)}"' for key, value in attrs.items())
            return f"<a:off {attrs_str}/>"

        return re.sub(r"<a:off\b[^>]*/>", repl, block, count=1)

    def _compute_template_fidelity_score(self, *, box_count: int, moved_count: int, issues_after_count: int) -> int:
        if box_count <= 0:
            return 100
        move_ratio = moved_count / box_count
        move_penalty = int(move_ratio * 55)
        issue_penalty = min(45, issues_after_count * 15)
        return max(0, 100 - move_penalty - issue_penalty)

    def _xml_escape(self, text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def _xml_unescape(self, text: str) -> str:
        return html.unescape(text)

    def _xml_attr_escape(self, text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
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






