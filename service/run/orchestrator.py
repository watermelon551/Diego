from __future__ import annotations

import asyncio
import httpx
import json
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import traceback
import zlib
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..config import Settings, load_settings
from ..llm import (
    GeneratedSlide,
    LLMClient,
    LLMEmptyResponseError,
    LLMTimeoutError,
    OpenAICompatibleLLMClient,
    OutlineFormatError,
    SlideSpec,
)
from ..models import (
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
from ..design.skill_profile import PALETTES, FONT_PAIRS, STYLE_RECIPES, DesignProfile, StyleRecipe, allowed_layouts_for, choose_design_profile, enforce_layout_variety
from ..design.style_catalog import STYLE_PRESET_AUTO, get_style_theme_hint, resolve_style_choice
from ..infra.store import RunStore, now_iso


from .types import (
    ChartFact,
    ChartPlan,
    JsLayoutBox,
    LayoutBox,
    SlideGenerationError,
    VisualPolicyUnsatisfiedError,
    SlotGraph,
    TemplateAssetError,
    TemplateLayoutConflictError,
    TemplateSlotMappingError,
)
from ..slides.js_quality_mixin import SlideJsQualityMixin
from ..templates.template_ops_mixin import TemplateOpsMixin
from .flows import OutlineFlowService, ScratchFlowService, TemplateFlowService
from .services import CompileService, QualityRepairService, ReportingService

class RunOrchestrator(SlideJsQualityMixin, TemplateOpsMixin):
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
        # Keep subprocess monkeypatch compatibility via legacy shim imports.
        self.subprocess = subprocess
        self.slide_concurrency = max(1, settings.slide_concurrency)
        self.slide_retry = max(1, settings.slide_retry)
        self.llm_max_retries = max(1, settings.llm_max_retries)
        self.outline_timeout_retries = max(0, settings.outline_timeout_retries)
        self.outline_timeout_backoff_sec = max(0.0, settings.outline_timeout_backoff_sec)
        self.repair_rounds = max(1, settings.repair_rounds)
        self.max_slide_repair_rounds = max(1, settings.max_slide_repair_rounds)
        self.llm_request_concurrency = max(1, int(getattr(settings, "llm_request_concurrency", 6)))
        self.slide_candidate_workers = max(1, min(5, int(getattr(settings, "slide_candidate_workers", 3))))
        self.llm_timeout_jitter_sec = max(0.0, float(getattr(settings, "llm_timeout_jitter_sec", 0.2)))
        self.slide_fatal_early_stop_rounds = max(1, int(getattr(settings, "slide_fatal_early_stop_rounds", 2)))
        self.run_max_llm_calls = max(0, int(getattr(settings, "run_max_llm_calls", 0)))
        self.keep_failed_candidate_js = bool(getattr(settings, "keep_failed_candidate_js", True))
        self.slide_auto_canonicalize = bool(getattr(settings, "slide_auto_canonicalize", True))
        self.slide_diag_max_js_lines = max(40, int(getattr(settings, "slide_diag_max_js_lines", 260)))
        self.slide_diag_max_stderr_chars = max(2000, int(getattr(settings, "slide_diag_max_stderr_chars", 12000)))
        self.preview_qa_concurrency = max(1, int(getattr(settings, "preview_qa_concurrency", self.slide_concurrency)))
        self.asset_fetch_concurrency = max(1, int(getattr(settings, "asset_fetch_concurrency", 2)))
        self.llm_concurrency_build = max(1, int(getattr(settings, "llm_concurrency_build", 3)))
        self.llm_concurrency_evaluate = max(1, int(getattr(settings, "llm_concurrency_evaluate", 2)))
        self.llm_concurrency_repair = max(1, int(getattr(settings, "llm_concurrency_repair", 1)))
        self.timeout_streak_degrade_threshold = max(1, int(getattr(settings, "timeout_streak_degrade_threshold", 3)))
        self.timeout_streak_recover_window_sec = max(0.0, float(getattr(settings, "timeout_streak_recover_window_sec", 120.0)))
        self._llm_request_gate = threading.BoundedSemaphore(self.llm_request_concurrency)
        self._llm_phase_build_gate = threading.BoundedSemaphore(min(self.llm_request_concurrency, self.llm_concurrency_build))
        self._llm_phase_evaluate_gate = threading.BoundedSemaphore(min(self.llm_request_concurrency, self.llm_concurrency_evaluate))
        self._llm_phase_repair_gate = threading.BoundedSemaphore(min(self.llm_request_concurrency, self.llm_concurrency_repair))
        self._llm_pressure_gate = threading.BoundedSemaphore(1)
        self._preview_qa_gate = threading.BoundedSemaphore(self.preview_qa_concurrency)
        self._asset_fetch_gate = threading.BoundedSemaphore(self.asset_fetch_concurrency)
        self._timeout_lock = threading.Lock()
        self._timeout_streak = 0
        self._last_timeout_monotonic = 0.0
        self._run_budget_lock = threading.Lock()
        self._run_llm_call_counts: dict[str, int] = {}
        self._run_llm_call_limits: dict[str, int] = {}
        self._js_api_contract = self._load_js_api_contract()
        self._outline_flow = OutlineFlowService(self)
        self._scratch_flow = ScratchFlowService(self)
        self._template_flow = TemplateFlowService(self)
        self._compile_service = CompileService(self)
        self._quality_service = QualityRepairService(self)
        self._reporting_service = ReportingService(self)

    def _use_agentic_engine(self) -> bool:
        return self.settings.generation_engine == "agentic_v2"

    def _load_js_api_contract(self) -> dict[str, Any]:
        default_shapes = [
            "RECTANGLE",
            "ROUNDED_RECTANGLE",
            "OVAL",
            "LINE",
            "RIGHT_TRIANGLE",
            "DIAMOND",
            "CHEVRON",
            "HEXAGON",
            "PARALLELOGRAM",
            "PENTAGON",
            "PIE",
        ]
        default_charts = ["BAR", "LINE", "PIE", "DOUGHNUT", "SCATTER", "BUBBLE", "RADAR"]
        shapes = list(default_shapes)
        charts = list(default_charts)
        types_path = Path.cwd() / "node_modules" / "pptxgenjs" / "types" / "index.d.ts"
        try:
            if types_path.exists():
                text = types_path.read_text(encoding="utf-8", errors="ignore")
                shapes_block = re.search(r"shapes\s*:\s*\{(?P<body>[\s\S]{0,9000}?)\}\s*;", text)
                if shapes_block:
                    parsed = re.findall(r"\b([A-Z][A-Z0-9_]+)\s*:", shapes_block.group("body"))
                    if parsed:
                        shapes = self._dedupe_preserve_order(parsed)
                chart_block = re.search(r"ChartType[\s\S]{0,3000}\{(?P<body>[\s\S]{0,5000}?)\}", text)
                if chart_block:
                    parsed = re.findall(r"\b([A-Z][A-Z0-9_]+)\s*:", chart_block.group("body"))
                    if parsed:
                        charts = self._dedupe_preserve_order(parsed)
        except Exception:
            pass
        return {
            "legal_shape_enum": shapes[:40],
            "legal_chart_enum": charts[:24],
            "required_export": "module.exports = { createSlide, slideConfig };",
            "required_signature": "function createSlide(pres, theme)",
            "forbidden_api": [
                "pres.shapes.ELLIPSE",
                "slide.addPageBadge",
                "addGroup()",
                "createCanvas()",
                "slide.background(...)",
                "pres.utilitextfit(...)",
            ],
            "known_fix_examples": [
                "ELLIPSE -> OVAL",
                "RT_TRIANGLE -> RIGHT_TRIANGLE",
                "slide.background(theme.bg) -> slide.background = { color: theme.bg }",
                "ShapeType.RECTANGLE -> pres.shapes.RECTANGLE",
                "module.exports = createSlide -> module.exports = { createSlide, slideConfig }",
            ],
        }

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
            error_details=run.error_details,
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
                seed=f"{run.input.topic}|{self._resolved_template_style(run)}|{run_id}|confirm",
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

    def _retryable_http_statuses(self) -> set[int]:
        # 529 is provider overload; 429/5xx are transient in most LLM gateways.
        return {
            408,
            409,
            425,
            429,
            500,
            502,
            503,
            504,
            520,
            521,
            522,
            523,
            524,
            529,
        }

    def _is_retryable_http_status_error(self, exc: Exception) -> bool:
        if not isinstance(exc, httpx.HTTPStatusError):
            return False
        try:
            code = int(exc.response.status_code)
        except Exception:
            return False
        return code in self._retryable_http_statuses()

    def _retry_after_seconds(self, exc: Exception) -> float | None:
        if not isinstance(exc, httpx.HTTPStatusError):
            return None
        header = (exc.response.headers.get("Retry-After") or "").strip()
        if not header:
            return None
        try:
            value = float(header)
        except ValueError:
            return None
        if value < 0:
            return None
        return value

    def _is_retryable_llm_exception(self, exc: Exception) -> bool:
        if isinstance(exc, (LLMTimeoutError, httpx.TimeoutException, TimeoutError)):
            return True
        if isinstance(exc, LLMEmptyResponseError):
            return True
        if isinstance(exc, httpx.NetworkError):
            return True
        if self._is_retryable_http_status_error(exc):
            return True
        return False

    def _llm_phase_bucket(self, phase: str) -> str:
        lowered = str(phase or "").lower()
        if any(token in lowered for token in (".repair", "repair", ".revise", "polish")):
            return "repair"
        if any(token in lowered for token in (".evaluate", ".review", "critic", "quality", "qa")):
            return "evaluate"
        return "build"

    def _llm_phase_gate(self, phase: str) -> threading.BoundedSemaphore:
        bucket = self._llm_phase_bucket(phase)
        if bucket == "repair":
            return self._llm_phase_repair_gate
        if bucket == "evaluate":
            return self._llm_phase_evaluate_gate
        return self._llm_phase_build_gate

    def _is_under_timeout_pressure(self) -> bool:
        with self._timeout_lock:
            streak = self._timeout_streak
            last_timeout = self._last_timeout_monotonic
        if streak < self.timeout_streak_degrade_threshold:
            return False
        if self.timeout_streak_recover_window_sec <= 0:
            return True
        return (time.monotonic() - last_timeout) <= self.timeout_streak_recover_window_sec

    def _note_timeout(self) -> None:
        with self._timeout_lock:
            self._timeout_streak = min(100, self._timeout_streak + 1)
            self._last_timeout_monotonic = time.monotonic()

    def _note_llm_success(self) -> None:
        with self._timeout_lock:
            if self._timeout_streak > 0:
                self._timeout_streak -= 1

    def _recommended_candidate_workers(self) -> int:
        base = max(1, self.slide_candidate_workers)
        with self._timeout_lock:
            streak = self._timeout_streak
        if streak >= 8:
            return 1
        if streak >= 4:
            return min(base, 2)
        return base

    def _init_run_llm_budget(self, *, run_id: str, target_slide_count: int) -> None:
        dynamic_default = max(
            60,
            int(target_slide_count) * (max(1, self.max_slide_repair_rounds) * 2 + 4),
        )
        limit = self.run_max_llm_calls if self.run_max_llm_calls > 0 else dynamic_default
        with self._run_budget_lock:
            self._run_llm_call_counts[run_id] = 0
            self._run_llm_call_limits[run_id] = max(1, limit)

    def _clear_run_llm_budget(self, run_id: str) -> None:
        with self._run_budget_lock:
            self._run_llm_call_counts.pop(run_id, None)
            self._run_llm_call_limits.pop(run_id, None)

    def _consume_run_llm_budget(self, *, run_id: str, phase: str) -> None:
        with self._run_budget_lock:
            limit = self._run_llm_call_limits.get(run_id)
            if limit is None:
                return
            next_count = self._run_llm_call_counts.get(run_id, 0) + 1
            self._run_llm_call_counts[run_id] = next_count
            if next_count > limit:
                raise RuntimeError(f"llm call budget exceeded at {phase}: {next_count}>{limit}")

    def _is_timeout_failure_payload(self, payload: dict[str, Any]) -> bool:
        reason = str(payload.get("reason", "")).lower()
        error_type = str(payload.get("error_type", ""))
        if "timeout" in reason or "Timeout" in error_type:
            return True
        # Treat transient overload/rate-limit server codes as timeout-like pressure signals.
        if any(code in reason for code in (" 429", " 500", " 502", " 503", " 504", " 529")):
            return True
        return False
    def _exception_reason(self, exc: Exception) -> str:
        reason = str(exc).strip()
        return reason or repr(exc)

    def _resolved_template_style(self, run: RunRecord) -> str:
        report = run.research_report if isinstance(run.research_report, dict) else {}
        style = str(report.get("effective_template_style", "")).strip()
        return style or run.input.template_style

    def _resolve_content_source_mode(self, run: RunRecord) -> str:
        return "rag_first" if run.input.rag_source_ids else "model_only"

    def _resolve_image_source_mode(self, run: RunRecord) -> str:
        if run.input.visual_policy == VisualPolicy.BASIC_GRAPHICS_ONLY:
            return "graphics_only"
        provider = self.settings.asset_provider.lower().strip()
        if provider == "none":
            return "disabled"
        if provider == "mock":
            return "mock"
        return provider or "auto"

    def _selected_style_preset(self, run: RunRecord):
        if run.input.generation_mode != GenerationMode.SCRATCH:
            return None
        return resolve_style_choice(getattr(run.input, "style_preset", STYLE_PRESET_AUTO))

    def _requested_template_style(self, run: RunRecord) -> str:
        preset = self._selected_style_preset(run)
        if preset is not None:
            return preset.template_style_hint
        return run.input.template_style

    def _apply_style_preset_to_requirements(self, *, run: RunRecord, report: dict[str, Any]) -> dict[str, Any]:
        preset = self._selected_style_preset(run)
        normalized = dict(report or {})
        normalized["style_preset"] = getattr(run.input, "style_preset", STYLE_PRESET_AUTO)
        if preset is None:
            normalized["style_reference_name"] = ""
            return normalized

        normalized["style_reference_name"] = preset.name
        normalized["style_intent"] = preset.prompt
        normalized["effective_template_style"] = preset.template_style_hint

        notes_raw = normalized.get("design_notes", [])
        notes = [str(item).strip() for item in notes_raw if str(item).strip()] if isinstance(notes_raw, list) else []
        notes = [preset.prompt] + [item for item in notes if item != preset.prompt]
        normalized["design_notes"] = notes[:8]

        design_intent = normalized.get("design_intent", {})
        if not isinstance(design_intent, dict):
            design_intent = {}
        if not str(design_intent.get("style_recipe", "")).strip():
            design_intent["style_recipe"] = preset.style_recipe_hint
        if not str(design_intent.get("rationale", "")).strip():
            design_intent["rationale"] = f"apply selected style preset: {preset.name}"
        style_theme = get_style_theme_hint(preset.id)
        if style_theme:
            existing_theme_raw = design_intent.get("theme") if isinstance(design_intent.get("theme"), dict) else {}
            existing_theme: dict[str, str] = {}
            for key in ("primary", "secondary", "accent", "light", "bg"):
                candidate = self._normalize_hex6(str(existing_theme_raw.get(key, "")))
                if candidate:
                    existing_theme[key] = candidate
            if len(existing_theme) >= 5:
                # Keep LLM-analyzed colors when analysis phase already produced a full theme.
                design_intent["theme"] = existing_theme
            else:
                # Fallback/patch only missing colors from style preset.
                merged_theme = dict(style_theme)
                merged_theme.update(existing_theme)
                design_intent["theme"] = merged_theme
            design_intent["palette_name"] = preset.name
            normalized["palette_name"] = preset.name
        normalized["design_intent"] = design_intent
        return normalized

    def _compose_requirements_report(
        self,
        *,
        run: RunRecord,
        research_brief: dict[str, Any],
        design_intent: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        report: dict[str, Any] = dict(research_brief or {})
        intent_raw = dict(design_intent or {})
        notes_raw = report.get("design_notes", [])
        notes = [str(item).strip() for item in notes_raw if str(item).strip()] if isinstance(notes_raw, list) else []
        page_focus_raw = report.get("page_focus", [])
        page_focus = [str(item).strip() for item in page_focus_raw if str(item).strip()] if isinstance(page_focus_raw, list) else []
        tone = str(report.get("tone", "")).strip()
        style_intent = str(report.get("style_intent", "")).strip() or tone or "professional"
        effective_template_style = str(report.get("effective_template_style", "")).strip() or run.input.template_style
        theme_overrides_raw = intent_raw.get("theme") if isinstance(intent_raw.get("theme"), dict) else {}
        theme_overrides = {
            key: value
            for key, value in {
                "primary": self._normalize_hex6(str(theme_overrides_raw.get("primary", ""))),
                "secondary": self._normalize_hex6(str(theme_overrides_raw.get("secondary", ""))),
                "accent": self._normalize_hex6(str(theme_overrides_raw.get("accent", ""))),
                "light": self._normalize_hex6(str(theme_overrides_raw.get("light", ""))),
                "bg": self._normalize_hex6(str(theme_overrides_raw.get("bg", ""))),
            }.items()
            if value
        }
        design_intent_norm = {
            "palette_name": str(intent_raw.get("palette_name", "")).strip(),
            "style_recipe": str(intent_raw.get("style_recipe", "")).strip().lower(),
            "title_font": str(intent_raw.get("title_font", "")).strip(),
            "body_font": str(intent_raw.get("body_font", "")).strip(),
            "visual_strategy": str(intent_raw.get("visual_strategy", "")).strip(),
            "density": str(intent_raw.get("density", "")).strip(),
            "rationale": str(intent_raw.get("rationale", "")).strip(),
            "theme": theme_overrides,
        }
        report.update(
            {
                "audience": str(report.get("audience", "")).strip() or "general audience",
                "purpose": str(report.get("purpose", "")).strip() or f"explain {run.input.topic} clearly",
                "tone": tone or "professional",
                "narrative_arc": str(report.get("narrative_arc", "")).strip() or "problem -> analysis -> solution -> summary",
                "page_focus": page_focus[: run.input.target_slide_count],
                "design_notes": notes[:8],
                "style_intent": style_intent,
                "effective_template_style": effective_template_style,
                "design_intent": design_intent_norm,
                "style_preset": getattr(run.input, "style_preset", STYLE_PRESET_AUTO),
                "page_count_fixed": run.input.target_slide_count,
                "content_source_mode": self._resolve_content_source_mode(run),
                "image_source_mode": self._resolve_image_source_mode(run),
            }
        )
        return report

    def _normalize_hex6(self, raw: str) -> str | None:
        value = (raw or "").strip().lstrip("#")
        if len(value) == 3 and all(ch in "0123456789abcdefABCDEF" for ch in value):
            value = "".join(ch * 2 for ch in value)
        if len(value) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in value):
            return None
        return value.upper()

    def _resolve_palette_theme(self, *, base: DesignProfile, design_intent: dict[str, Any]) -> tuple[str, dict[str, str]]:
        palette_name = str(design_intent.get("palette_name", "")).strip()
        for name, palette in PALETTES:
            if palette_name and name.lower() == palette_name.lower():
                return name, {
                    "primary": palette[0],
                    "secondary": palette[1],
                    "accent": palette[4],
                    "light": palette[3],
                    "bg": palette[2],
                }

        theme = dict(base.theme)
        theme_payload = design_intent.get("theme") if isinstance(design_intent.get("theme"), dict) else {}
        for key in ("primary", "secondary", "accent", "light", "bg"):
            candidate = self._normalize_hex6(str(theme_payload.get(key, "")))
            if candidate:
                theme[key] = candidate
        return (palette_name or base.palette_name), theme

    def _resolve_style_recipe_name(
        self,
        *,
        design_intent: dict[str, Any],
        style_intent: str,
        template_style: str,
        fallback: str,
    ) -> str:
        explicit = str(design_intent.get("style_recipe", "")).strip().lower()
        if explicit in STYLE_RECIPES:
            return explicit
        merged = f"{style_intent} {template_style}".lower()
        if any(word in merged for word in ("brutal", "sharp", "authority", "finance", "data")):
            return "sharp"
        if any(word in merged for word in ("premium", "luxury", "editorial", "brand")):
            return "pill"
        if any(word in merged for word in ("creative", "marketing", "rounded", "friendly")):
            return "rounded"
        if any(word in merged for word in ("soft", "education", "training", "balanced")):
            return "soft"
        return fallback if fallback in STYLE_RECIPES else "soft"

    def _resolve_font_from_intent(self, *, preferred: str, fallback: str) -> str:
        normalized_preferred = preferred.strip()
        if not normalized_preferred:
            return fallback
        available = {font for pair in FONT_PAIRS for font in pair}
        return normalized_preferred if normalized_preferred in available else fallback

    def _resolve_design_profile(self, *, topic: str, template_style: str, requirements_report: dict[str, Any]) -> DesignProfile:
        base = choose_design_profile(topic=topic, template_style=template_style)
        design_intent = requirements_report.get("design_intent", {})
        if not isinstance(design_intent, dict):
            design_intent = {}
        palette_name, theme = self._resolve_palette_theme(base=base, design_intent=design_intent)
        style_name = self._resolve_style_recipe_name(
            design_intent=design_intent,
            style_intent=str(requirements_report.get("style_intent", "")),
            template_style=template_style,
            fallback=base.style.name,
        )
        style = STYLE_RECIPES.get(style_name, base.style)
        title_font = self._resolve_font_from_intent(
            preferred=str(design_intent.get("title_font", "")),
            fallback=base.title_font,
        )
        body_font = self._resolve_font_from_intent(
            preferred=str(design_intent.get("body_font", "")),
            fallback=base.body_font,
        )
        return DesignProfile(
            palette_name=palette_name,
            theme=theme,
            title_font=title_font,
            body_font=body_font,
            style=style,
        )
    async def _call_llm_with_timeout_retry(
        self,
        *,
        run_id: str,
        phase: str,
        action: Any,
    ) -> Any:
        max_attempts = self.outline_timeout_retries + 1
        gate_timeout_sec = max(1.0, float(self.settings.llm_timeout_sec) + 5.0)
        phase_gate = self._llm_phase_gate(phase)
        for attempt in range(1, max_attempts + 1):
            acquired_global = False
            acquired_phase = False
            acquired_pressure = False
            try:
                self._consume_run_llm_budget(run_id=run_id, phase=phase)
                acquired_global = await asyncio.to_thread(self._llm_request_gate.acquire, True, gate_timeout_sec)
                if not acquired_global:
                    raise TimeoutError("llm request concurrency gate timeout")
                acquired_phase = await asyncio.to_thread(phase_gate.acquire, True, gate_timeout_sec)
                if not acquired_phase:
                    raise TimeoutError("llm phase concurrency gate timeout")
                if self._is_under_timeout_pressure():
                    acquired_pressure = await asyncio.to_thread(self._llm_pressure_gate.acquire, True, gate_timeout_sec)
                    if not acquired_pressure:
                        raise TimeoutError("llm pressure gate timeout")
                result = await action()
                self._note_llm_success()
                return result
            except Exception as exc:
                if not self._is_retryable_llm_exception(exc):
                    raise
                self._note_timeout()
                reason = self._exception_reason(exc)
                await self._publish(
                    run_id,
                    EventType.LLM_REQUEST_TIMEOUT,
                    {
                        "phase": phase,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "reason": reason,
                    },
                )
                if attempt >= max_attempts:
                    raise LLMTimeoutError(attempts=attempt, reason=reason, phase=phase) from exc
                jitter = random.uniform(0.0, self.llm_timeout_jitter_sec) if self.llm_timeout_jitter_sec > 0 else 0.0
                delay = self.outline_timeout_backoff_sec * (2 ** (attempt - 1)) + jitter
                retry_after = self._retry_after_seconds(exc)
                if retry_after is not None:
                    delay = max(delay, retry_after)
                await self._publish(
                    run_id,
                    EventType.LLM_REQUEST_RETRY,
                    {
                        "phase": phase,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "next_delay_sec": round(delay, 2),
                        "reason": reason,
                    },
                )
                if delay > 0:
                    await asyncio.sleep(delay)
            finally:
                if acquired_pressure:
                    self._llm_pressure_gate.release()
                if acquired_phase:
                    phase_gate.release()
                if acquired_global:
                    self._llm_request_gate.release()
        raise RuntimeError("unreachable timeout retry loop")

    async def _call_outline_with_timeout_retry(
        self,
        *,
        run_id: str,
        phase: str,
        action: Any,
    ) -> Any:
        return await self._call_llm_with_timeout_retry(run_id=run_id, phase=phase, action=action)

    async def _generate_outline(self, run_id: str) -> None:
        await self._outline_flow.execute(run_id)

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
        await self._scratch_flow.execute(run_id)

    async def _complete_post_compile_quality(
        self,
        *,
        run_id: str,
        mode: GenerationMode,
        design: DesignProfile,
    ) -> bool:
        return await self._quality_service.complete_post_compile_quality(run_id=run_id, mode=mode, design=design)

    async def _finalize_run_success(self, run_id: str, *, from_stage: str, reason: str) -> None:
        def apply_success(r: RunRecord) -> None:
            r.status = RunStatus.SUCCEEDED
            r.error_code = None
            r.failed_stage = None
            r.retryable = False
            r.error_details = {}

        await self.store.update_run(run_id, apply_success)
        self._clear_run_llm_budget(run_id)
        await self._publish(
            run_id,
            EventType.RUN_FINALIZED,
            {"final_status": RunStatus.SUCCEEDED.value, "from_stage": from_stage, "reason": reason},
        )

    async def _generate_from_template(self, run_id: str) -> None:
        await self._template_flow.execute(run_id)

    def _template_work_paths(self, artifact_dir: Path) -> tuple[Path, Path, Path, Path, Path, Path, Path, Path]:
        return self._compile_service.template_work_paths(artifact_dir)

    def _pack_template_unpacked(self, *, unpacked: Path, edited: Path) -> None:
        self._compile_service.pack_template_unpacked(unpacked=unpacked, edited=edited)

    async def _compile_template_js(self, *, template_slides_dir: Path) -> bool:
        return await self._compile_service.compile_template_js(template_slides_dir=template_slides_dir)

    async def _apply_template_nodes_once(
        self,
        *,
        run_id: str,
        unpacked: Path,
        design: DesignProfile,
        use_review: bool,
        forced_issues: list[str] | None,
    ) -> list[SlideArtifact] | None:
        return await self._compile_service.apply_template_nodes_once(
            run_id=run_id,
            unpacked=unpacked,
            design=design,
            use_review=use_review,
            forced_issues=forced_issues,
        )

    async def _revise_template_slides(self, *, run_id: str, design: DesignProfile, forced_issues: list[str] | None) -> bool:
        return await self._compile_service.revise_template_slides(
            run_id=run_id,
            design=design,
            forced_issues=forced_issues,
        )

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
        effective_template_style = self._resolved_template_style(run)
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
                generated = await self._call_llm_with_timeout_retry(
                    run_id=run_id,
                    phase=f"slide.{slide_no}.legacy.generate",
                    action=lambda: self.llm_client.generate_slide(
                        topic=run.input.topic,
                        project_id=run.input.project_id,
                        template_style=effective_template_style,
                        slide_no=slide_no,
                        target_slide_count=run.input.target_slide_count,
                        outline_node=node,
                        rag_source_ids=run.input.rag_source_ids,
                    ),
                )
                candidate = generated
                rule_violations = self._quality_service.check_slide_content_rules(candidate, node)
                reviewed = await self._call_llm_with_timeout_retry(
                    run_id=run_id,
                    phase=f"slide.{slide_no}.legacy.review",
                    action=lambda: self.llm_client.review_slide(
                        topic=run.input.topic,
                        template_style=effective_template_style,
                        slide_no=slide_no,
                        target_slide_count=run.input.target_slide_count,
                        outline_node=node,
                        candidate=candidate,
                        rule_violations=rule_violations,
                    ),
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
            except Exception as exc:
                retries += 1
                if retries >= self.slide_retry:
                    raise SlideGenerationError(
                        slide_no=slide_no,
                        phase="slide.content.generate",
                        reason=self._exception_reason(exc),
                        details={"error_type": type(exc).__name__, "retries": retries},
                    ) from exc
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
        effective_template_style = self._resolved_template_style(run)
        slide_plan = self._build_slide_plan(node=node, design=design, slide_no=slide_no)
        self._apply_visual_policy_to_slide_plan(
            slide_plan=slide_plan,
            page_type=node.page_type,
            visual_policy=run.input.visual_policy,
        )
        slide_plan["api_contract"] = dict(self._js_api_contract)
        assets = await self._prepare_scratch_visual_assets(
            run=run,
            node=node,
            slide_no=slide_no,
            slide_plan=slide_plan,
            slides_dir=slides_dir,
        )
        if assets:
            visual_plan = slide_plan.get("visual_plan") if isinstance(slide_plan.get("visual_plan"), dict) else {}
            visual_plan = dict(visual_plan)
            visual_plan["assets"] = assets
            slide_plan["visual_plan"] = visual_plan
        slide_brief = self._build_slide_brief(run=run, node=node, slide_no=slide_no, slide_plan=slide_plan)
        await self._publish(
            run_id,
            EventType.SLIDE_PLAN_COMPLETED,
            {
                "slide_no": slide_no,
                "layout": slide_plan.get("layout"),
                "visual_policy": run.input.visual_policy.value,
                "visual_plan": slide_plan.get("visual_plan", {}),
                "constraints": slide_plan.get("constraints", {}),
            },
        )
        await self._publish(
            run_id,
            EventType.SLIDE_CODEGEN_STARTED,
            {"slide_no": slide_no, "engine": self.settings.generation_engine},
        )

        slide_path = slides_dir / f"slide-{slide_no:02d}.js"
        candidate_path = slides_dir / f"slide-{slide_no:02d}-cand-01.js"
        best_js = ""
        best_chart_plan: ChartPlan | None = None
        best_citations: list[str] = []
        best_variant: dict[str, Any] = {}

        last_major_issues: list[str] = []
        last_warnings: list[str] = []
        last_failure_context: dict[str, Any] = {}
        selected_repair_directives: list[str] = []
        selected_preview_text = ""
        quality_score = 0
        round_passed = 0
        degraded_accept = False
        soft_round_limit = max(1, self.max_slide_repair_rounds)
        hard_round_limit = soft_round_limit + 2
        compile_failure_markers = (
            "missing export contract",
            "createslide signature invalid",
            "createslide must be synchronous",
            "addtext call signature invalid",
            "addshape call signature invalid",
            "preview compile failed",
            "preview skipped due to fatal contract issue",
            "preview pptx missing",
            "forbidden api detected",
            "llm_output_not_executable",
            "jsondecodeerror",
        )
        best_compile_ok = False

        for repair_round in range(1, hard_round_limit + 1):
            variant = {
                "mode": "scratch_llm_js",
                "worker": 1,
                "round": repair_round,
                "layout_anchor": str(slide_plan.get("layout", "")),
                "seed": f"s{slide_no}-r{repair_round}-scratch-llm-js",
            }
            candidate_plan = dict(slide_plan)
            candidate_plan["candidate_worker"] = 1
            candidate_plan["variant"] = variant
            candidate_plan["repair_round"] = repair_round
            candidate_plan["previous_issues"] = last_major_issues[:8]
            llm_phase = "candidate.build"
            citations = self._normalize_citations([], run.input.rag_source_ids, slide_no)

            try:
                if repair_round == 1 or not best_js:
                    js_code = await self._call_llm_with_timeout_retry(
                        run_id=run_id,
                        phase=f"slide.{slide_no}.round.{repair_round}.candidate.1.build",
                        action=lambda: self.llm_client.generate_slide_js(
                            topic=run.input.topic,
                            template_style=effective_template_style,
                            slide_no=slide_no,
                            target_slide_count=run.input.target_slide_count,
                            outline_node=node,
                            theme=design.theme,
                            title_font=design.title_font,
                            body_font=design.body_font,
                            rag_source_ids=run.input.rag_source_ids,
                            visual_policy=run.input.visual_policy,
                            slide_plan=candidate_plan,
                            slide_brief=slide_brief,
                        ),
                    )
                else:
                    llm_phase = "candidate.repair"
                    js_code = await self._call_llm_with_timeout_retry(
                        run_id=run_id,
                        phase=f"slide.{slide_no}.round.{repair_round}.candidate.1.repair",
                        action=lambda: self.llm_client.critique_slide_js(
                            topic=run.input.topic,
                            template_style=effective_template_style,
                            slide_no=slide_no,
                            target_slide_count=run.input.target_slide_count,
                            outline_node=node,
                            candidate_js=best_js,
                            issues=self._dedupe_preserve_order(last_major_issues + last_warnings),
                            failure_context=last_failure_context,
                            visual_policy=run.input.visual_policy,
                            slide_plan=candidate_plan,
                            repair_directives=selected_repair_directives,
                            preview_text=selected_preview_text,
                            slide_brief=slide_brief,
                        ),
                    )
                js_code, normalize_fixes = self._normalize_generated_slide_js(
                    js_code,
                    slide_no=slide_no,
                    node=node,
                    target_slide_count=run.input.target_slide_count,
                )
                auto_fixes: list[str] = []
                if self.slide_auto_canonicalize:
                    js_code, auto_fixes = self._auto_canonicalize_slide_js(
                        js_code,
                        slide_no=slide_no,
                        node=node,
                        target_slide_count=run.input.target_slide_count,
                    )
                if normalize_fixes or auto_fixes:
                    await self._publish(
                        run_id,
                        EventType.SLIDE_AUTO_FIX_APPLIED,
                        {
                            "slide_no": slide_no,
                            "round": repair_round,
                            "candidate": 1,
                            "fixes": self._dedupe_preserve_order(normalize_fixes + auto_fixes)[:24],
                        },
                    )
                js_code = self._apply_local_js_guardrails(
                    js_code=js_code,
                    slide_no=slide_no,
                    page_type=node.page_type,
                )
                generated = self._quality_service.extract_candidate_from_js(
                    js_code=js_code,
                    fallback_node=node,
                    citations=citations,
                )
                chart_plan = self._build_chart_plan_from_bullets(
                    node=OutlineNode(
                        title=generated.title,
                        bullets=list(generated.bullets),
                        page_type=node.page_type,
                        layout_hint=generated.layout_hint or node.layout_hint,
                    ),
                    source_refs=citations,
                )
            except Exception as exc:
                build_issue = f"candidate build failed: {self._exception_reason(exc)}"
                classified = self._classify_slide_issues([build_issue])
                selected_repair_directives = self._build_local_repair_directives(classified=classified)
                quality_score = self._local_quality_score(classified=classified)
                last_failure_context = self._build_slide_failure_context(
                    phase=llm_phase,
                    slide_js_path=candidate_path,
                    candidate_js=(best_js or ""),
                    issues=[build_issue],
                    diagnostics={
                        "error_class": type(exc).__name__,
                        "error_message": self._exception_reason(exc),
                        "attempt": repair_round,
                        "gate_summary": {
                            "blocking": len(classified["blocking"]),
                            "high_risk": len(classified["high_risk"]),
                            "warnings": len(classified["warnings"]),
                        },
                    },
                )
                await self._publish(
                    run_id,
                    EventType.SLIDE_FAILURE_DIAGNOSTICS,
                    {
                        "slide_no": slide_no,
                        "round": repair_round,
                        "candidate": 1,
                        "phase": llm_phase,
                        "context": last_failure_context,
                        "error_type": type(exc).__name__,
                        "stderr_excerpt": last_failure_context.get("stderr_excerpt", ""),
                        "error_location": last_failure_context.get("error_location", {}),
                        "repair_hint": selected_repair_directives[:5],
                    },
                )
                await self._publish_retry_context_event(
                    run_id=run_id,
                    slide_no=slide_no,
                    repair_round=repair_round,
                    candidate_no=1,
                    phase=llm_phase,
                    issues=[build_issue],
                    context=last_failure_context,
                )
                await self._publish(
                    run_id,
                    EventType.SLIDE_CANDIDATE_GENERATED,
                    {
                        "slide_no": slide_no,
                        "round": repair_round,
                        "candidate": 1,
                        "score": quality_score,
                        "passed": False,
                        "hard_issue_count": len(classified["blocking"]) + len(classified["high_risk"]),
                        "llm_issue_count": 0,
                        "error": self._exception_reason(exc),
                        "phase": llm_phase,
                        "variant": variant,
                        "gate": {
                            "blocking": len(classified["blocking"]),
                            "high_risk": len(classified["high_risk"]),
                            "warnings": len(classified["warnings"]),
                        },
                    },
                )
                if repair_round >= soft_round_limit and best_js and best_compile_ok:
                    slide_path.write_text(best_js, encoding="utf-8")
                    round_passed = repair_round
                    degraded_accept = True
                    break
                if repair_round >= hard_round_limit:
                    raise SlideGenerationError(
                        slide_no=slide_no,
                        phase=llm_phase,
                        reason=self._exception_reason(exc),
                        round_no=repair_round,
                        details={"issues": [build_issue]},
                    ) from exc
                last_major_issues = list(classified["blocking"] + classified["high_risk"])
                last_warnings = list(classified["warnings"])
                continue

            candidate_path.write_text(js_code, encoding="utf-8")
            hard_issues = self._validate_slide_js_contract(
                js_code,
                slide_no=slide_no,
                page_type=node.page_type.value,
                visual_policy=run.input.visual_policy,
            )
            fatal_contract = any(
                issue in {"missing export contract", "createSlide signature invalid", "createSlide must be synchronous"}
                for issue in hard_issues
            )

            preview_mode = "full"
            preview_text = ""
            preview_issues: list[str] = []
            preview_diag: dict[str, Any] = {}
            if fatal_contract:
                preview_mode = "skip_contract_failure"
                preview_issues.append("preview skipped due to fatal contract issue")
            else:
                preview_issues, preview_text, preview_diag = await self._run_slide_preview_qa_with_text(
                    run_id=run_id,
                    slide_js=candidate_path,
                    slide_no=slide_no,
                )

            all_issues = self._dedupe_preserve_order(list(hard_issues) + list(preview_issues))
            compile_ok = not any(
                any(marker in str(issue).lower() for marker in compile_failure_markers)
                for issue in all_issues
            )
            classified = self._classify_slide_issues(all_issues)
            blocking = list(classified["blocking"])
            high_risk = list(classified["high_risk"])
            warnings = list(classified["warnings"])
            needs_repair = bool(blocking)
            degraded_notes = self._dedupe_preserve_order(high_risk + warnings)
            quality_score = self._local_quality_score(classified=classified)
            selected_repair_directives = self._build_local_repair_directives(classified=classified)
            if needs_repair:
                diagnostics = dict(preview_diag or {})
                diagnostics.setdefault("preview_mode", preview_mode)
                diagnostics["attempt"] = repair_round
                diagnostics["gate_summary"] = {
                    "blocking": len(blocking),
                    "high_risk": len(high_risk),
                    "warnings": len(warnings),
                }
                last_failure_context = self._build_slide_failure_context(
                    phase=("candidate.contract" if fatal_contract else "candidate.preview"),
                    slide_js_path=candidate_path,
                    candidate_js=js_code,
                    issues=all_issues,
                    diagnostics=diagnostics,
                )
                await self._publish(
                    run_id,
                    EventType.SLIDE_FAILURE_DIAGNOSTICS,
                    {
                        "slide_no": slide_no,
                        "round": repair_round,
                        "candidate": 1,
                        "phase": ("candidate.contract" if fatal_contract else "candidate.preview"),
                        "context": last_failure_context,
                        "error_type": str(last_failure_context.get("error_class", "")),
                        "stderr_excerpt": last_failure_context.get("stderr_excerpt", ""),
                        "error_location": last_failure_context.get("error_location", {}),
                        "repair_hint": selected_repair_directives[:5],
                    },
                )
                await self._publish_retry_context_event(
                    run_id=run_id,
                    slide_no=slide_no,
                    repair_round=repair_round,
                    candidate_no=1,
                    phase=("candidate.contract" if fatal_contract else "candidate.preview"),
                    issues=all_issues,
                    context=last_failure_context,
                )

            await self._publish(
                run_id,
                EventType.SLIDE_CANDIDATE_GENERATED,
                {
                    "slide_no": slide_no,
                    "round": repair_round,
                    "candidate": 1,
                    "score": quality_score,
                    "passed": not needs_repair,
                    "hard_issue_count": len(blocking) + len(high_risk),
                    "llm_issue_count": 0,
                    "preview_mode": preview_mode,
                    "variant": variant,
                    "gate": {
                        "blocking": len(blocking),
                        "high_risk": len(high_risk),
                        "warnings": len(warnings),
                    },
                },
            )
            await self._append_candidate_selection_entry(
                run_id=run_id,
                entry={
                    "slide_no": slide_no,
                    "round": repair_round,
                    "selected_candidate": 1,
                    "selected_score": quality_score,
                    "selected_passed": not needs_repair,
                    "selected_degraded": bool(degraded_notes) and not needs_repair,
                    "selected_variant": variant,
                    "degraded_accept": bool(degraded_notes) and not needs_repair,
                    "candidates": [
                        {
                            "candidate": 1,
                            "mode": "scratch_llm_js",
                            "variant": variant,
                            "score": quality_score,
                            "passed": not needs_repair,
                            "degraded": bool(degraded_notes) and not needs_repair,
                            "hard_issue_count": len(blocking) + len(high_risk),
                            "llm_issue_count": 0,
                            "preview_mode": preview_mode,
                        }
                    ],
                },
            )
            await self._publish(
                run_id,
                EventType.SLIDE_SELECTION_COMPLETED,
                {
                    "slide_no": slide_no,
                    "round": repair_round,
                    "selected_candidate": 1,
                    "score": quality_score,
                    "passed": not needs_repair,
                    "degraded": bool(degraded_notes) and not needs_repair,
                    "variant": variant,
                },
            )
            await self._append_quality_gate_entry(
                run_id=run_id,
                entry={
                    "slide_no": slide_no,
                    "round": repair_round,
                    "visual_policy": run.input.visual_policy.value,
                    "score": quality_score,
                    "threshold": 0,
                    "hard_issues": list(blocking + high_risk),
                    "llm_issues": [],
                    "repair_directives": list(selected_repair_directives),
                    "blocking_issues": list(blocking),
                    "high_risk_issues": list(high_risk),
                    "warnings": list(warnings),
                    "passed": not needs_repair,
                },
            )
            await self._publish(
                run_id,
                EventType.SLIDE_QUALITY_GATE_COMPLETED,
                {
                    "slide_no": slide_no,
                    "round": repair_round,
                    "score": quality_score,
                    "threshold": 0,
                    "passed": not needs_repair,
                    "hard_issue_count": len(blocking) + len(high_risk),
                    "llm_issue_count": 0,
                    "gate": {
                        "blocking": len(blocking),
                        "high_risk": len(high_risk),
                        "warnings": len(warnings),
                    },
                },
            )

            best_js = js_code
            best_chart_plan = chart_plan
            best_citations = list(citations)
            best_variant = dict(variant)
            selected_preview_text = preview_text
            last_major_issues = list(blocking + high_risk)
            last_warnings = list(degraded_notes)
            best_compile_ok = compile_ok
            candidate_path.unlink(missing_ok=True)

            if not needs_repair:
                slide_path.write_text(best_js, encoding="utf-8")
                round_passed = repair_round
                degraded_accept = bool(degraded_notes)
                last_failure_context = {}
                break

            visual_policy_blocked = any(
                "visual_policy violation" in item.lower()
                for item in (last_major_issues + last_warnings)
            )
            if visual_policy_blocked and repair_round >= soft_round_limit:
                raise VisualPolicyUnsatisfiedError(
                    f"slide {slide_no} cannot satisfy visual policy: {'; '.join((last_major_issues + last_warnings)[:3])}"
                )

            if repair_round >= soft_round_limit and best_compile_ok:
                slide_path.write_text(best_js, encoding="utf-8")
                round_passed = repair_round
                degraded_accept = True
                break

            await self._publish(
                run_id,
                EventType.SLIDE_CRITIC_COMPLETED,
                {"slide_no": slide_no, "round": repair_round, "issues": list(last_major_issues)},
            )
            await self._publish(
                run_id,
                EventType.SLIDE_REPAIR_DIRECTIVES_GENERATED,
                {
                    "slide_no": slide_no,
                    "round": repair_round,
                    "directives": selected_repair_directives,
                    "variant": best_variant,
                },
            )
            await self._publish(
                run_id,
                EventType.SLIDE_REPAIR_COMPLETED,
                {"slide_no": slide_no, "round": repair_round},
            )

            if repair_round >= hard_round_limit:
                if self.keep_failed_candidate_js and best_js:
                    self._persist_failed_candidate_js(
                        slides_dir=slides_dir,
                        slide_no=slide_no,
                        js_code=best_js,
                        round_no=repair_round,
                        issues=(last_major_issues + last_warnings)[:20],
                    )
                all_issues = self._dedupe_preserve_order(last_major_issues + last_warnings)
                if any("visual_policy violation" in item.lower() for item in all_issues):
                    raise VisualPolicyUnsatisfiedError(
                        f"slide {slide_no} cannot satisfy visual policy: {'; '.join(all_issues[:3])}"
                    )
                raise SlideGenerationError(
                    slide_no=slide_no,
                    phase="candidate.rounds_exhausted",
                    reason=f"failed after {hard_round_limit} rounds (base={soft_round_limit}, extra=2)",
                    round_no=repair_round,
                    details={
                        "issues": (last_major_issues + last_warnings)[:20],
                        "failure_context": last_failure_context,
                    },
                )

        if round_passed == 0 or not slide_path.exists():
            raise SlideGenerationError(
                slide_no=slide_no,
                phase="candidate.missing_output",
                reason="single-candidate generation produced no accepted slide",
                round_no=hard_round_limit,
                details={"issues": (last_major_issues + last_warnings)[:20]},
            )

        final_js = slide_path.read_text(encoding="utf-8")
        citations = list(best_citations) if best_citations else self._normalize_citations([], run.input.rag_source_ids, slide_no)
        if best_chart_plan is not None:
            await self._append_chart_truth_report(
                run_id=run_id,
                entry={
                    "slide_no": slide_no,
                    "has_verified_data": best_chart_plan.has_verified_data,
                    "mode": best_chart_plan.mode,
                    "source": best_chart_plan.source,
                    "note": best_chart_plan.note,
                    "labels": best_chart_plan.labels,
                },
            )
            await self._publish(
                run_id,
                EventType.CHART_TRUTH_CHECKED,
                {
                    "slide_no": slide_no,
                    "has_verified_data": best_chart_plan.has_verified_data,
                    "mode": best_chart_plan.mode,
                    "source": best_chart_plan.source,
                },
            )

        await self._append_quality_entry(
            run_id=run_id,
            entry={
                "slide_no": slide_no,
                "passed_round": round_passed,
                "issues_last_round": list(last_major_issues + last_warnings),
                "engine": self.settings.generation_engine,
                "quality_score": quality_score,
                "visual_policy": run.input.visual_policy.value,
                "selected_variant": best_variant,
                "degraded_accept": degraded_accept,
                "preview_text_excerpt": selected_preview_text[:300],
                "repair_directives": selected_repair_directives[:8],
                "llm_issues": [],
            },
        )
        await self._publish(
            run_id,
            EventType.SLIDE_CODEGEN_COMPLETED,
            {"slide_no": slide_no, "rounds": round_passed, "degraded_accept": degraded_accept},
        )
        return SlideArtifact(
            slide_no=slide_no,
            js_path=str(slide_path),
            js_code=final_js,
            status=(f"ok_agentic_degraded_round_{round_passed}" if degraded_accept else f"ok_agentic_round_{round_passed}"),
            citations=citations,
        )

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

        image_slots = 1 if (node.page_type == SlidePageType.CONTENT and visual_kind in {"image_or_showcase", "icon_rows"}) else 0
        return {
            "slide_no": slide_no,
            "page_type": node.page_type.value,
            "layout": layout,
            "visual_plan": {
                "kind": visual_kind,
                "must_have_badge": node.page_type != SlidePageType.COVER,
                "image_slots": image_slots,
                "chart_preferred": visual_kind in {"chart_callout"},
            },
            "constraints": {
                "min_margin_in": 0.5 if node.page_type == SlidePageType.CONTENT else 0.35,
                "min_block_gap_in": 0.22 if node.page_type == SlidePageType.CONTENT else 0.18,
                "body_align": "left",
                "title_min_size": 36,
                "body_preferred_size": "14-16",
                "title_body_min_delta": 18,
                "must_use_shrink": True,
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

    def _layout_supports_image(self, layout_hint: str | None) -> bool:
        return str(layout_hint or "").strip() in {"content-two-column", "content-showcase", "content-icon-rows"}

    def _apply_visual_policy_to_slide_plan(
        self,
        *,
        slide_plan: dict[str, Any],
        page_type: SlidePageType,
        visual_policy: VisualPolicy,
    ) -> None:
        if page_type != SlidePageType.CONTENT:
            return
        visual_plan = slide_plan.get("visual_plan")
        if not isinstance(visual_plan, dict):
            visual_plan = {}
            slide_plan["visual_plan"] = visual_plan
        if visual_policy == VisualPolicy.MEDIA_REQUIRED:
            layout = str(slide_plan.get("layout", "")).strip()
            if not self._layout_supports_image(layout):
                slide_plan["layout"] = "content-showcase"
            visual_plan["kind"] = "image_or_showcase"
            visual_plan["image_slots"] = max(1, int(visual_plan.get("image_slots", 0) or 0))
            visual_plan["chart_preferred"] = False
        elif visual_policy == VisualPolicy.BASIC_GRAPHICS_ONLY:
            visual_plan["image_slots"] = 0

    def _extract_slide_plan_assets(self, slide_plan: dict[str, Any]) -> list[dict[str, Any]]:
        visual_plan = slide_plan.get("visual_plan")
        if not isinstance(visual_plan, dict):
            return []
        assets = visual_plan.get("assets", [])
        if not isinstance(assets, list):
            return []
        out: list[dict[str, Any]] = []
        for item in assets:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path", "")).strip()
            if not path:
                continue
            out.append({"path": path, "slot": str(item.get("slot", "")).strip(), "type": str(item.get("type", "")).strip()})
        return out

    def _apply_local_spec_repairs(
        self,
        *,
        spec: SlideSpec,
        node: OutlineNode,
        repair_round: int,
        issues: list[str],
        visual_policy: VisualPolicy,
    ) -> SlideSpec:
        page_type = spec.page_type or node.page_type
        repaired = SlideSpec(
            title=spec.title or node.title,
            subtitle=spec.subtitle,
            bullets=list(spec.bullets or node.bullets),
            page_type=page_type,
            layout_hint=spec.layout_hint or node.layout_hint,
            visual_kind=spec.visual_kind or "shape",
            emphasis=spec.emphasis,
            citations=list(spec.citations),
        )
        lowered_issues = [str(item).lower() for item in issues if str(item).strip()]
        has_geometry_issue = any(
            any(marker in item for marker in ("out of slide bounds", "overlaps box", "gap too tight", "margin too tight"))
            for item in lowered_issues
        )
        has_fit_issue = any(
            any(marker in item for marker in ("fit:'shrink'", "title/body size contrast", "title font too small"))
            for item in lowered_issues
        )
        has_visual_missing = any(
            any(marker in item for marker in ("visual_policy violation", "content slide missing non-text visual element"))
            for item in lowered_issues
        )

        if repaired.page_type == SlidePageType.CONTENT:
            if visual_policy == VisualPolicy.MEDIA_REQUIRED:
                repaired.visual_kind = "image"
                if not self._layout_supports_image(repaired.layout_hint):
                    repaired.layout_hint = "content-showcase"
            elif visual_policy == VisualPolicy.BASIC_GRAPHICS_ONLY and repaired.visual_kind == "image":
                repaired.visual_kind = "chart"
            if has_visual_missing and repaired.visual_kind not in {"image", "chart"}:
                repaired.visual_kind = "chart"

        if has_geometry_issue:
            repaired.layout_hint = self._rotate_layout_hint(
                layout_hint=repaired.layout_hint,
                page_type=repaired.page_type,
                repair_round=repair_round,
                prefer_image_layout=(visual_policy == VisualPolicy.MEDIA_REQUIRED and repaired.page_type == SlidePageType.CONTENT),
            )
        if has_fit_issue or has_geometry_issue:
            repaired.bullets = self._trim_spec_bullets(
                bullets=repaired.bullets,
                page_type=repaired.page_type,
            )
        return repaired

    def _rotate_layout_hint(
        self,
        *,
        layout_hint: str | None,
        page_type: SlidePageType,
        repair_round: int,
        prefer_image_layout: bool,
    ) -> str | None:
        allowed = allowed_layouts_for(page_type)
        if not allowed:
            return layout_hint
        preferred = [name for name in allowed if self._layout_supports_image(name)] if prefer_image_layout else []
        if preferred:
            current = str(layout_hint or "").strip()
            if current in preferred:
                return preferred[(preferred.index(current) + repair_round) % len(preferred)]
            return preferred[(repair_round - 1) % len(preferred)]
        current = str(layout_hint or "").strip()
        if current in allowed:
            return allowed[(allowed.index(current) + repair_round) % len(allowed)]
        return allowed[(repair_round - 1) % len(allowed)]

    def _trim_spec_bullets(self, *, bullets: list[str], page_type: SlidePageType) -> list[str]:
        src = [str(item).strip() for item in bullets if str(item).strip()]
        if not src:
            return src
        max_items = 4 if page_type == SlidePageType.CONTENT else 3
        max_len = 90 if page_type == SlidePageType.CONTENT else 80
        out: list[str] = []
        for item in src[:max_items]:
            cleaned = re.sub(r"\s+", " ", item).strip()
            if len(cleaned) > max_len:
                cleaned = cleaned[: max_len - 3].rstrip(" ,;:.") + "..."
            out.append(cleaned)
        return out

    def _build_slide_brief(
        self,
        *,
        run: RunRecord,
        node: OutlineNode,
        slide_no: int,
        slide_plan: dict[str, Any],
    ) -> dict[str, Any]:
        report = run.research_report if isinstance(run.research_report, dict) else {}
        page_focus_raw = report.get("page_focus", [])
        page_focus_list = [str(item).strip() for item in page_focus_raw if str(item).strip()] if isinstance(page_focus_raw, list) else []
        design_notes_raw = report.get("design_notes", [])
        design_notes = [str(item).strip() for item in design_notes_raw if str(item).strip()] if isinstance(design_notes_raw, list) else []
        design_intent = report.get("design_intent", {}) if isinstance(report.get("design_intent", {}), dict) else {}
        selected_focus = page_focus_list[slide_no - 1] if 0 < slide_no <= len(page_focus_list) else ""
        visual_plan = slide_plan.get("visual_plan", {}) if isinstance(slide_plan.get("visual_plan", {}), dict) else {}
        assets = visual_plan.get("assets", []) if isinstance(visual_plan.get("assets", []), list) else []
        return {
            "audience": str(report.get("audience", "")).strip(),
            "purpose": str(report.get("purpose", "")).strip(),
            "tone": str(report.get("tone", "")).strip(),
            "narrative_arc": str(report.get("narrative_arc", "")).strip(),
            "style_intent": str(report.get("style_intent", "")).strip(),
            "design_intent": design_intent,
            "current_page_focus": selected_focus,
            "page_type": node.page_type.value,
            "layout": str(slide_plan.get("layout", "")),
            "design_notes": design_notes[:8],
            "assets": assets,
        }

    def _candidate_variant_specs(
        self,
        *,
        slide_no: int,
        round_no: int,
        worker_count: int,
        layout: str,
    ) -> list[dict[str, Any]]:
        seeds = [
            {"composition": "balanced", "emphasis": "narrative", "density": "medium", "contrast": "high"},
            {"composition": "visual_heavy", "emphasis": "data", "density": "compact", "contrast": "high"},
            {"composition": "text_heavy", "emphasis": "explanation", "density": "airy", "contrast": "medium"},
            {"composition": "diagrammatic", "emphasis": "structure", "density": "medium", "contrast": "high"},
            {"composition": "storyboard", "emphasis": "progression", "density": "medium", "contrast": "medium"},
        ]
        variants: list[dict[str, Any]] = []
        for worker_idx in range(1, worker_count + 1):
            base = dict(seeds[(worker_idx - 1) % len(seeds)])
            base["worker"] = worker_idx
            base["round"] = round_no
            base["layout_anchor"] = layout
            base["seed"] = f"s{slide_no}-r{round_no}-w{worker_idx}-{layout}"
            variants.append(base)
        return variants

    async def _prepare_scratch_visual_assets(
        self,
        *,
        run: RunRecord,
        node: OutlineNode,
        slide_no: int,
        slide_plan: dict[str, Any],
        slides_dir: Path,
    ) -> list[dict[str, Any]]:
        if run.input.visual_policy == VisualPolicy.BASIC_GRAPHICS_ONLY:
            return []
        if node.page_type != SlidePageType.CONTENT:
            return []
        visual_plan = slide_plan.get("visual_plan", {}) if isinstance(slide_plan.get("visual_plan", {}), dict) else {}
        kind = str(visual_plan.get("kind", ""))
        requires_image = run.input.visual_policy == VisualPolicy.MEDIA_REQUIRED or kind in {"image_or_showcase", "icon_rows"}
        if not requires_image:
            return []

        slot_type = "icon" if kind == "icon_rows" else "image"
        query = self._build_asset_query(node=node, slot_type=slot_type, slide_no=slide_no)
        imgs_dir = slides_dir / "imgs"
        imgs_dir.mkdir(parents=True, exist_ok=True)
        try:
            asset_bytes, ext = await self._fetch_slot_asset_with_gate(
                query=query,
                slot_type=slot_type,
                node=node,
                slide_no=slide_no,
                rel_id=f"scratch-{slide_no:02d}-{slot_type}",
            )
            local_path = imgs_dir / f"slide-{slide_no:02d}-{slot_type}.{ext}"
            await asyncio.to_thread(local_path.write_bytes, asset_bytes)
            rel_path = Path("imgs") / local_path.name
            return [
                {
                    "slot": slot_type,
                    "type": slot_type,
                    "query": query,
                    "path": rel_path.as_posix(),
                    "provider": self.settings.asset_provider,
                }
            ]
        except Exception as exc:
            if run.input.visual_policy == VisualPolicy.MEDIA_REQUIRED:
                raise VisualPolicyUnsatisfiedError(
                    f"slide {slide_no} requires media asset but fetch failed: {self._exception_reason(exc)}"
                ) from exc
            return []

    async def _fetch_slot_asset_with_gate(
        self,
        *,
        query: str,
        slot_type: str,
        node: OutlineNode,
        slide_no: int,
        rel_id: str,
    ) -> tuple[bytes, str]:
        acquired = False
        try:
            timeout_sec = max(2.0, float(self.settings.asset_timeout_sec) + 2.0)
            acquired = await asyncio.to_thread(self._asset_fetch_gate.acquire, True, timeout_sec)
            if not acquired:
                raise TimeoutError("asset fetch concurrency gate timeout")
            return await asyncio.to_thread(
                self._fetch_slot_asset,
                query=query,
                slot_type=slot_type,
                node=node,
                slide_no=slide_no,
                rel_id=rel_id,
            )
        finally:
            if acquired:
                self._asset_fetch_gate.release()

    def _fallback_research_brief(self, *, topic: str, template_style: str, target_slide_count: int) -> dict[str, Any]:
        focus: list[str] = []
        for idx in range(1, target_slide_count + 1):
            if idx == 1:
                focus.append(f"{topic}: opening context and core claim")
            elif idx == target_slide_count:
                focus.append(f"{topic}: synthesis, decisions, and next steps")
            else:
                focus.append(f"{topic}: section {idx} with concrete evidence and visual takeaway")
        return {
            "audience": "general audience",
            "purpose": f"explain {topic} clearly with actionable insights",
            "tone": "professional and concise",
            "narrative_arc": "background -> key points -> evidence -> practical takeaways",
            "page_focus": focus,
            "design_notes": [
                f"Keep visual language consistent with template_style={template_style}.",
                "Enforce strong title/body hierarchy and left-aligned body text.",
                "Ensure every content page has a meaningful non-text visual anchor.",
            ],
            "style_intent": template_style,
            "effective_template_style": template_style,
        }

    def _slide_spec_from_generated(self, *, generated: GeneratedSlide, node: OutlineNode) -> SlideSpec:
        return SlideSpec(
            title=generated.title or node.title,
            subtitle="",
            bullets=list(generated.bullets or node.bullets),
            page_type=node.page_type,
            layout_hint=generated.layout_hint or node.layout_hint,
            visual_kind="shape",
            emphasis="",
            citations=list(generated.citations),
        )

    def _generated_from_slide_spec(self, *, spec: SlideSpec, node: OutlineNode) -> GeneratedSlide:
        return GeneratedSlide(
            title=spec.title or node.title,
            bullets=list(spec.bullets or node.bullets),
            citations=list(spec.citations),
            page_type=node.page_type,
            layout_hint=spec.layout_hint or node.layout_hint,
        )

    def _render_skill_slide_js(
        self,
        *,
        slide_no: int,
        total: int,
        node: OutlineNode,
        generated: GeneratedSlide,
        design: DesignProfile,
        chart_plan: ChartPlan,
        visual_kind: str | None = None,
        visual_assets: list[dict[str, Any]] | None = None,
    ) -> str:
        page_type = node.page_type
        title = json.dumps(generated.title, ensure_ascii=False)
        bullets_literal = json.dumps(generated.bullets, ensure_ascii=False)
        selected_layout = generated.layout_hint or node.layout_hint or "content-two-column"
        layout_hint = json.dumps(selected_layout, ensure_ascii=False)
        visual_kind_literal = json.dumps((visual_kind or "shape").strip().lower(), ensure_ascii=False)
        visual_assets_literal = json.dumps(visual_assets or [], ensure_ascii=False)
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
            visual_kind=(visual_kind or "shape").strip().lower(),
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
                f"  visualKind: {visual_kind_literal},",
                f"  assets: {visual_assets_literal},",
                f"  chartPlan: {chart_plan_literal},",
                "};",
                "",
                f"const fonts = {{ title: {json.dumps(design.title_font)}, body: {json.dumps(design.body_font)} }};",
                f"const style = {{ cornerSmall: {design.style.corner_small}, cornerMedium: {design.style.corner_medium}, cornerLarge: {design.style.corner_large}, pageMargin: {design.style.page_margin}, blockGap: {design.style.block_gap}, elementGap: {design.style.element_gap}, badgePill: {str(design.style.badge_pill).lower()} }};",
                "",
                "function addBulletList(slide, items, opts, theme) {",
                "  const maxItems = opts.maxItems || 6;",
                "  const prepared = (items || []).map((x) => String(x || '').trim()).filter(Boolean).slice(0, maxItems);",
                "  const payload = prepared.length ? prepared : [(slideConfig.title || 'Core takeaway')];",
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

    def _slide_content_block(self, *, page_type: SlidePageType, layout_hint: str, style: StyleRecipe, visual_kind: str = "shape") -> str:
        if page_type == SlidePageType.COVER:
            return self._slide_block_cover(layout_hint)
        if page_type == SlidePageType.TOC:
            return self._slide_block_toc(layout_hint)
        if page_type == SlidePageType.SECTION:
            return self._slide_block_section(layout_hint)
        if page_type == SlidePageType.SUMMARY:
            return self._slide_block_summary(layout_hint)
        return self._slide_block_content(layout_hint, visual_kind=visual_kind)

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

    def _slide_block_content(self, layout_hint: str, *, visual_kind: str = "shape") -> str:
        visual_header = [
            "  const visualKind = String(slideConfig.visualKind || 'shape').toLowerCase();",
            "  const visualAsset = Array.isArray(slideConfig.assets) ? slideConfig.assets.find((item) => item && typeof item.path === 'string' && item.path.trim()) : null;",
        ]
        if layout_hint == "content-icon-rows":
            body = "\n".join(
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
            return "\n".join(visual_header + [body])
        if layout_hint == "content-comparison":
            body = "\n".join(
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
            return "\n".join(visual_header + [body])
        if layout_hint == "content-timeline":
            body = "\n".join(
                [
                    "  const steps = bullets.slice(0, 5);",
                    "  slide.addShape(pres.shapes.LINE, { x: 1.0, y: 2.45, w: 8.0, h: 0.01, line: { color: theme.secondary, pt: 1 } });",
                    "  steps.forEach((item, idx) => {",
                    "    const x = 1.0 + idx * (8.0 / Math.max(steps.length - 1, 1));",
                    "    slide.addShape(pres.shapes.OVAL, { x: x - 0.16, y: 2.27, w: 0.32, h: 0.32, fill: { color: theme.accent }, line: { color: theme.accent } });",
                    "    slide.addText(String(idx + 1), { x: x - 0.16, y: 2.27, w: 0.32, h: 0.32, fontSize: 10, fontFace: fonts.body, color: 'FFFFFF', bold: true, align: 'center', valign: 'mid', margin: 0 });",
                    "    slide.addText(item, { x: x - 0.7, y: 2.7, w: 1.4, h: 0.8, fontSize: 12, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'center', margin: 0, fit: 'shrink' });",
                    "  });",
                ]
            )
            return "\n".join(visual_header + [body])
        if layout_hint == "content-stat-callout":
            body = "\n".join(
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
                    "    slide.addText((cp.note || 'Qualitative trend summary.').slice(0, 160), { x: 5.15, y: 1.92, w: 3.7, h: 1.0, fontSize: 13, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'left', margin: 0, fit: 'shrink' });",
                    "  }",
                    "  addBulletList(slide, bullets.slice(0, 5), { x: 4.9, y: 3.95, w: 4.2, h: 1.2, maxItems: 4, fontSize: 12 }, theme);",
                ]
            )
            return "\n".join(visual_header + [body])
        if layout_hint == "content-showcase":
            body = "\n".join(
                [
                    "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.8, y: 1.25, w: 8.4, h: 2.55, fill: { color: theme.light, transparency: 6 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                    "  if (visualKind === 'image' && visualAsset && visualAsset.path) {",
                    "    slide.addImage({ path: visualAsset.path, x: 1.0, y: 1.42, w: 7.95, h: 2.2 });",
                    "  } else {",
                    "    slide.addText('Visual showcase area', { x: 1.1, y: 2.35, w: 7.8, h: 0.4, fontSize: 14, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'center', margin: 0 });",
                    "  }",
                    "  addBulletList(slide, bullets.slice(0, 3), { x: 1.1, y: 4.02, w: 7.8, h: 0.95, maxItems: 3, fontSize: 13 }, theme);",
                ]
            )
            return "\n".join(visual_header + [body])
        body = "\n".join(
            [
                "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.7, y: 1.25, w: 4.2, h: 3.75, fill: { color: theme.light, transparency: 12 }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                "  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 5.1, y: 1.25, w: 4.2, h: 3.75, fill: { color: theme.bg }, line: { color: theme.secondary, pt: 1 }, rectRadius: style.cornerMedium });",
                "  if (visualKind === 'image' && visualAsset && visualAsset.path) {",
                "    slide.addImage({ path: visualAsset.path, x: 1.0, y: 1.55, w: 3.6, h: 3.05 });",
                "  } else {",
                "    slide.addText('Visual', { x: 1.0, y: 2.9, w: 3.5, h: 0.45, fontSize: 18, fontFace: fonts.title, color: theme.primary, bold: true, align: 'center', margin: 0 });",
                "  }",
                "  addBulletList(slide, bullets.slice(0, 6), { x: 5.35, y: 1.6, w: 3.75, h: 3.1, maxItems: 6, fontSize: 14 }, theme);",
            ]
        )
        return "\n".join(visual_header + [body])

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
        previous_report = run.qa_report if isinstance(run.qa_report, dict) else {}
        verification_cycles = int(previous_report.get("verification_cycles", 0))
        preview_cache_in = previous_report.get("preview_cache", {}) if isinstance(previous_report.get("preview_cache", {}), dict) else {}
        preview_cache_out: dict[str, Any] = {}

        if mode == GenerationMode.SCRATCH:
            slides_dir = artifact_dir / "slides"
            slide_files = sorted(
                [path for path in slides_dir.glob("slide-*.js") if re.fullmatch(r"slide-\d{2}\.js", path.name)]
            )
            if not slide_files:
                issues.append("no slide js files generated")

            observed_layouts: list[str] = []
            unchanged_preview_candidates: list[tuple[Path, int, str]] = []
            preview_runs = 0

            for idx, path in enumerate(slide_files, start=1):
                text = path.read_text(encoding="utf-8")
                page_type_match = re.search(r"type:\s*['\"]([^'\"]+)['\"]", text)
                page_type = page_type_match.group(1).strip().lower() if page_type_match else ""
                if not page_type:
                    page_type_match = re.search(r"page_type:\s*['\"]([^'\"]+)['\"]", text)
                    page_type = page_type_match.group(1).strip().lower() if page_type_match else ""
                static_issues: list[str] = []
                if "module.exports = { createSlide, slideConfig };" not in text:
                    static_issues.append(f"{path.name}: missing export contract")
                if "function createSlide(pres, theme)" not in text:
                    static_issues.append(f"{path.name}: createSlide signature invalid")
                if "async function createSlide" in text:
                    static_issues.append(f"{path.name}: createSlide must be synchronous")
                if re.search(r"['\"]#[0-9a-fA-F]{3,8}['\"]", text):
                    static_issues.append(f"{path.name}: hex color with # is forbidden")
                if re.search(r"['\"][0-9a-fA-F]{8}['\"]", text):
                    static_issues.append(f"{path.name}: 8-char hex color is forbidden")
                if idx > 1 and not self._has_valid_page_badge(js_code=text, slide_no=idx):
                    static_issues.append(f"{path.name}: missing required page badge position")
                theme_hits = sum(1 for key in ("theme.primary", "theme.secondary", "theme.accent", "theme.light", "theme.bg") if key in text)
                if "theme.primary" not in text or "theme.bg" not in text or theme_hits < 4:
                    static_issues.append(f"{path.name}: theme key usage incomplete")
                if any(char in text for char in ("•", "✓", "▪", "◦")):
                    static_issues.append(f"{path.name}: unicode bullet symbol detected")
                if re.search(r"addShape\(pres\.shapes\.LINE,[^\n]*y:\s*1\.[0-3]", text):
                    static_issues.append(f"{path.name}: title accent line pattern detected")
                if page_type == "content" and all(token not in text for token in ("addShape(", "addImage(", "addChart(")):
                    static_issues.append(f"{path.name}: content slide missing non-text visual element")
                if page_type == "content" and run.input.visual_policy == VisualPolicy.MEDIA_REQUIRED:
                    if "addImage(" not in text:
                        static_issues.append(f"{path.name}: visual_policy media_required expects addImage()")
                    if all(token not in text for token in ("addShape(", "addChart(")):
                        static_issues.append(f"{path.name}: visual_policy media_required expects shape/chart complement")
                if page_type == "content" and run.input.visual_policy == VisualPolicy.BASIC_GRAPHICS_ONLY and "addImage(" in text:
                    static_issues.append(f"{path.name}: visual_policy basic_graphics_only forbids addImage()")
                layout_match = re.search(r"(?:layoutHint|layout):\s*['\"]([^'\"]+)['\"]", text)
                if layout_match:
                    observed_layouts.append(layout_match.group(1))

                checksum = f"{zlib.crc32(text.encode('utf-8')):08x}"
                cache_entry = preview_cache_in.get(path.name, {}) if isinstance(preview_cache_in.get(path.name, {}), dict) else {}
                unchanged = str(cache_entry.get("hash", "")) == checksum
                cached_preview_issues = [str(item) for item in cache_entry.get("issues", [])] if isinstance(cache_entry.get("issues", []), list) else []

                preview_issues: list[str] = []
                preview_checked = False
                if static_issues:
                    preview_issues = []
                else:
                    should_preview = verification_cycles == 0 or not unchanged
                    if should_preview:
                        preview_issues = await self._run_slide_preview_qa(run_id=run_id, slide_js=path, slide_no=idx)
                        preview_checked = True
                        preview_runs += 1
                    else:
                        unchanged_preview_candidates.append((path, idx, checksum))
                        preview_issues = list(cached_preview_issues)

                all_slide_issues = static_issues + preview_issues
                issues.extend(all_slide_issues)
                preview_cache_out[path.name] = {
                    "hash": checksum,
                    "issues": all_slide_issues if preview_checked else preview_issues,
                    "checked": preview_checked,
                }

            if verification_cycles > 0 and preview_runs == 0 and unchanged_preview_candidates:
                sample_path, sample_no, sample_checksum = unchanged_preview_candidates[0]
                sample_issues = await self._run_slide_preview_qa(run_id=run_id, slide_js=sample_path, slide_no=sample_no)
                preview_runs += 1
                cached = preview_cache_out.get(sample_path.name, {})
                prev_cached_issues = [str(item) for item in cached.get("issues", [])] if isinstance(cached.get("issues", []), list) else []
                if sample_issues:
                    issues.extend(sample_issues)
                preview_cache_out[sample_path.name] = {
                    "hash": sample_checksum,
                    "issues": prev_cached_issues + sample_issues,
                    "checked": True,
                    "sampled": True,
                }

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

        deduped_issues = self._dedupe_preserve_order([str(item) for item in issues if str(item).strip()])
        issues_by_slide, global_issues = self._split_qa_issues_by_slide(deduped_issues)
        report = {
            "passed": not deduped_issues,
            "issues": deduped_issues,
            "issues_by_slide": {str(k): v for k, v in sorted(issues_by_slide.items(), key=lambda x: x[0])},
            "global_issues": global_issues,
            "verification_cycles": verification_cycles,
            "preview_cache": preview_cache_out,
        }
        await self.store.update_run(run_id, lambda r: setattr(r, "qa_report", report))
        await self._publish(run_id, EventType.QA_COMPLETED, report)
        return not deduped_issues
    async def _markitdown_check(self, pptx_path: Path) -> tuple[bool, str | None]:
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "markitdown", str(pptx_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
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
            encoding="utf-8",
            errors="replace",
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

    def _summarize_process_failure(self, *, stderr: str, stdout: str) -> tuple[str, str]:
        combined = (stderr or stdout or "").strip()
        if not combined:
            return "preview compile failed", ""
        lines = [line.strip() for line in combined.splitlines() if line.strip()]
        lines = [
            line
            for line in lines
            if "[UNDICI-EHPA] Warning: EnvHttpProxyAgent is experimental" not in line
            and "Use `node --trace-warnings" not in line
        ]
        if not lines:
            return "preview compile failed", ""
        filtered = [line for line in lines if not re.fullmatch(r"Node\.js v\d+(?:\.\d+){1,3}", line)]
        focus = filtered or lines
        reason = focus[0][:240] if focus else "preview compile failed"
        details = " | ".join(focus[:5])[:1200]
        return reason, details

    async def _run_slide_preview_qa(self, *, run_id: str, slide_js: Path, slide_no: int) -> list[str]:
        issues, _, _ = await self._run_slide_preview_qa_with_text(run_id=run_id, slide_js=slide_js, slide_no=slide_no)
        return issues

    async def _run_slide_preview_qa_with_text(
        self,
        *,
        run_id: str,
        slide_js: Path,
        slide_no: int,
    ) -> tuple[list[str], str, dict[str, Any]]:
        issues: list[str] = []
        preview_text = ""
        diagnostics: dict[str, Any] = {}
        cleanup_note = "skipped"
        preview_file = slide_js.parent / f"slide-{slide_no:02d}-preview.pptx"
        preview_runner = slide_js.parent / f".preview-runner-{slide_no:02d}.js"
        preview_runner.write_text(
            self._build_preview_runner_js(slide_js_name=slide_js.name, preview_name=preview_file.name),
            encoding="utf-8",
        )
        preview_cmd = ["node", preview_runner.name]
        acquired = False
        try:
            acquired = await asyncio.to_thread(self._preview_qa_gate.acquire, True, max(2.0, self.settings.llm_timeout_sec))
            if not acquired:
                raise TimeoutError("preview compile gate timeout")
            result = await asyncio.to_thread(
                subprocess.run,
                preview_cmd,
                cwd=slide_js.parent,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except Exception as exc:
            diagnostics = {
                "command": " ".join(preview_cmd),
                "exit_code": None,
                "stderr": "",
                "stdout": "",
                "error_class": type(exc).__name__,
                "error_message": self._exception_reason(exc),
            }
            issues.append(f"{slide_js.name}: preview compile failed: {self._exception_reason(exc)}")
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
            return issues, preview_text, diagnostics
        finally:
            if acquired:
                self._preview_qa_gate.release()
            preview_runner.unlink(missing_ok=True)
        if result.returncode != 0:
            reason, details = self._summarize_process_failure(stderr=result.stderr or "", stdout=result.stdout or "")
            issues.append(f"{slide_js.name}: preview compile failed: {reason}")
            if details:
                issues.append(f"{slide_js.name}: preview compile details: {details}")
            diagnostics = {
                "command": " ".join(preview_cmd),
                "exit_code": result.returncode,
                "stderr": self._truncate_diag_text(result.stderr or ""),
                "stdout": self._truncate_diag_text(result.stdout or ""),
                "error_message": reason,
            }
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
            return issues, preview_text, diagnostics

        if not preview_file.exists():
            issues.append(f"{slide_js.name}: preview pptx missing")
            diagnostics = {
                "command": " ".join(preview_cmd),
                "exit_code": 0,
                "stderr": "",
                "stdout": "",
                "error_message": "preview pptx missing",
            }
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
            return issues, preview_text, diagnostics

        preview_text, preview_issue = await self._markitdown_extract(preview_file)
        if preview_issue:
            issues.append(f"{slide_js.name}: {preview_issue}")
            diagnostics = {
                "command": f"{sys.executable} -m markitdown {preview_file.name}",
                "exit_code": 0,
                "stderr": "",
                "stdout": self._truncate_diag_text(preview_text),
                "error_message": preview_issue,
            }
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
        return issues, preview_text, diagnostics

    def _build_preview_runner_js(self, *, slide_js_name: str, preview_name: str) -> str:
        safe_slide = json.dumps(f"./{slide_js_name}")
        safe_preview = json.dumps(preview_name)
        return "\n".join(
            [
                "const pptxgen = require('pptxgenjs');",
                f"const mod = require({safe_slide});",
                "const theme = { primary: '111111', secondary: '222222', accent: '0A84FF', light: 'F2F3F5', bg: 'FFFFFF' };",
                "(async () => {",
                "  if (!mod || typeof mod.createSlide !== 'function') {",
                "    throw new Error('missing createSlide export');",
                "  }",
                "  const pres = new pptxgen();",
                "  pres.layout = 'LAYOUT_16x9';",
                "  mod.createSlide(pres, theme);",
                f"  await pres.writeFile({{ fileName: {safe_preview} }});",
                "})();",
            ]
        )

    async def _mandatory_polish_cycle(self, run_id: str, *, mode: GenerationMode, design: DesignProfile) -> bool:
        return await self._quality_service.mandatory_polish_cycle(run_id, mode=mode, design=design)

    async def _repair_loop(self, run_id: str, *, mode: GenerationMode, design: DesignProfile) -> bool:
        return await self._quality_service.repair_loop(run_id, mode=mode, design=design)

    async def _compile_scratch_slides(self, run_id: str) -> bool:
        return await self._compile_service.compile_scratch_slides(run_id)

    async def _revise_scratch_slides(
        self,
        *,
        run_id: str,
        design: DesignProfile,
        forced_issues: list[str] | None,
    ) -> bool:
        return await self._quality_service.revise_scratch_slides(
            run_id=run_id,
            design=design,
            forced_issues=forced_issues,
        )

    async def _append_chart_truth_report(self, *, run_id: str, entry: dict[str, Any]) -> None:
        await self._reporting_service.append_chart_truth_report(run_id=run_id, entry=entry)

    async def _append_quality_entry(self, *, run_id: str, entry: dict[str, Any]) -> None:
        await self._reporting_service.append_quality_entry(run_id=run_id, entry=entry)

    async def _append_quality_gate_entry(self, *, run_id: str, entry: dict[str, Any]) -> None:
        await self._reporting_service.append_quality_gate_entry(run_id=run_id, entry=entry)

    async def _append_candidate_selection_entry(self, *, run_id: str, entry: dict[str, Any]) -> None:
        await self._reporting_service.append_candidate_selection_entry(run_id=run_id, entry=entry)

    async def _append_artifact_cleanup_entry(self, *, run_id: str, entry: dict[str, Any]) -> None:
        await self._reporting_service.append_artifact_cleanup_entry(run_id=run_id, entry=entry)

    async def _append_repair_history(self, *, run_id: str, entry: dict[str, Any]) -> None:
        await self._reporting_service.append_repair_history(run_id=run_id, entry=entry)

    async def _fail_run(
        self,
        run_id: str,
        stage: str,
        error_code: str,
        retryable: bool,
        error_details: dict[str, Any] | None = None,
    ) -> None:
        def apply_fail(r: RunRecord) -> None:
            r.status = RunStatus.FAILED
            r.error_code = error_code
            r.failed_stage = stage
            r.retryable = retryable
            r.error_details = dict(error_details or {})

        await self.store.update_run(run_id, apply_fail)
        payload: dict[str, Any] = {"error_code": error_code, "failed_stage": stage, "retryable": retryable}
        if error_details:
            payload["error_details"] = error_details
        self._clear_run_llm_budget(run_id)
        await self._publish(
            run_id,
            EventType.RUN_FAILED,
            payload,
        )
        await self._publish(
            run_id,
            EventType.RUN_FINALIZED,
            {"final_status": RunStatus.FAILED.value, "from_stage": stage, "reason": error_code},
        )

    def _normalize_citations(self, citations: list[str], rag_source_ids: list[str], slide_no: int) -> list[str]:
        normalized = [item for item in citations if item]
        if normalized:
            return list(dict.fromkeys(normalized))
        if not rag_source_ids:
            return []
        first = rag_source_ids[(slide_no - 1) % len(rag_source_ids)]
        second = rag_source_ids[slide_no % len(rag_source_ids)] if len(rag_source_ids) > 1 else first
        return list(dict.fromkeys([first, second]))

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
        outline_structured_output=settings.outline_structured_output,
        sanitize_think_tags=settings.llm_sanitize_think_tags,
        json_repair_retry=settings.llm_json_repair_retry,
    )
    return RunOrchestrator(
        store=RunStore(base_dir=base_dir),
        artifacts_base=artifacts_dir,
        templates_base=templates_dir,
        llm_client=llm_client,
        settings=settings,
    )


















