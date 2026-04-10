from __future__ import annotations

import asyncio
import html
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from .config import Settings, load_settings
from .llm_client import (
    GeneratedSlide,
    LLMClient,
    LLMEmptyResponseError,
    LLMTimeoutError,
    OpenAICompatibleLLMClient,
    OutlineFormatError,
    SlideSpec,
)
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
from .skill_profile import PALETTES, FONT_PAIRS, STYLE_RECIPES, DesignProfile, StyleRecipe, allowed_layouts_for, choose_design_profile, enforce_layout_variety
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


class SlideGenerationError(RuntimeError):
    def __init__(
        self,
        *,
        slide_no: int,
        phase: str,
        reason: str,
        round_no: int | None = None,
        candidate: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.slide_no = slide_no
        self.phase = phase
        self.reason = reason.strip() if reason else "slide generation failed"
        self.round_no = round_no
        self.candidate = candidate
        self.details = dict(details or {})
        message = f"slide {slide_no} {phase}: {self.reason}"
        super().__init__(message)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "slide_no": self.slide_no,
            "phase": self.phase,
            "reason": self.reason,
        }
        if self.round_no is not None:
            payload["round"] = self.round_no
        if self.candidate is not None:
            payload["candidate"] = self.candidate
        if self.details:
            payload["details"] = self.details
        return payload


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


@dataclass
class JsLayoutBox:
    element_type: str
    x: float
    y: float
    w: float
    h: float
    text_expr: str = ""
    options_raw: str = ""
    font_size: float | None = None
    align: str | None = None
    bold: bool | None = None
    fit: str | None = None

    @property
    def area(self) -> float:
        return self.w * self.h


SLIDE_WIDTH_EMU = 9_144_000
SLIDE_HEIGHT_EMU = 5_143_500
SLIDE_WIDTH_IN = 10.0
SLIDE_HEIGHT_IN = 5.625

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
        self._llm_request_gate = threading.BoundedSemaphore(self.llm_request_concurrency)
        self._timeout_lock = threading.Lock()
        self._timeout_streak = 0
        self._run_budget_lock = threading.Lock()
        self._run_llm_call_counts: dict[str, int] = {}
        self._run_llm_call_limits: dict[str, int] = {}

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
    def _note_timeout(self) -> None:
        with self._timeout_lock:
            self._timeout_streak = min(100, self._timeout_streak + 1)

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
            int(target_slide_count) * (max(1, self.max_slide_repair_rounds) * 4 + 6),
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
        for attempt in range(1, max_attempts + 1):
            acquired = False
            try:
                self._consume_run_llm_budget(run_id=run_id, phase=phase)
                acquired = await asyncio.to_thread(self._llm_request_gate.acquire, True, gate_timeout_sec)
                if not acquired:
                    raise TimeoutError("llm request concurrency gate timeout")
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
                if acquired:
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
        started = time.perf_counter()
        run = await self.store.get_run(run_id)
        if run is None:
            return
        try:
            await self._publish(
                run_id,
                EventType.REQUIREMENTS_ANALYZING_STARTED,
                {
                    "target_slide_count": run.input.target_slide_count,
                    "project_id": run.input.project_id,
                    "has_rag": bool(run.input.rag_source_ids),
                },
            )
            try:
                base_research = await self._call_outline_with_timeout_retry(
                    run_id=run_id,
                    phase="requirements.analyze",
                    action=lambda: self.llm_client.generate_research_brief(
                        topic=run.input.topic,
                        project_id=run.input.project_id,
                        rag_source_ids=run.input.rag_source_ids,
                        template_style=run.input.template_style,
                        target_slide_count=run.input.target_slide_count,
                    ),
                )
            except Exception:
                base_research = self._fallback_research_brief(
                    topic=run.input.topic,
                    template_style=run.input.template_style,
                    target_slide_count=run.input.target_slide_count,
                )
            design_intent: dict[str, Any] = {}
            try:
                design_intent = await self._call_outline_with_timeout_retry(
                    run_id=run_id,
                    phase="requirements.design_intent",
                    action=lambda: self.llm_client.generate_design_intent(
                        topic=run.input.topic,
                        template_style=run.input.template_style,
                        target_slide_count=run.input.target_slide_count,
                        research_brief=base_research,
                    ),
                )
            except Exception:
                design_intent = {}
            requirements_report = self._compose_requirements_report(
                run=run,
                research_brief=base_research,
                design_intent=design_intent,
            )
            effective_template_style = str(requirements_report.get("effective_template_style", "")).strip() or run.input.template_style
            await self.store.update_run(run_id, lambda r: setattr(r, "research_report", requirements_report))
            design_intent_payload = requirements_report.get("design_intent", {}) if isinstance(requirements_report.get("design_intent", {}), dict) else {}
            requirements_payload = {
                "page_count_fixed": requirements_report.get("page_count_fixed", run.input.target_slide_count),
                "effective_template_style": effective_template_style,
                "style_intent": requirements_report.get("style_intent", ""),
                "content_source_mode": requirements_report.get("content_source_mode", ""),
                "image_source_mode": requirements_report.get("image_source_mode", ""),
                "audience": requirements_report.get("audience", ""),
                "purpose": requirements_report.get("purpose", ""),
                "tone": requirements_report.get("tone", ""),
                "palette_name": design_intent_payload.get("palette_name", ""),
                "style_recipe": design_intent_payload.get("style_recipe", ""),
                "visual_strategy": design_intent_payload.get("visual_strategy", ""),
                "density": design_intent_payload.get("density", ""),
            }
            await self._publish(run_id, EventType.REQUIREMENTS_ANALYZING_COMPLETED, requirements_payload)
            await self._publish(run_id, EventType.REQUIREMENTS_ANALYZED, requirements_payload)

            async def on_token(token: str) -> None:
                await self._publish(run_id, EventType.OUTLINE_TOKEN, {"token": token})
            outline: OutlineDocument | None = None
            repair_attempts = max(1, self.llm_max_retries)
            previous_response = ""
            error_category = ""
            error_details: list[str] = []

            for attempt in range(1, repair_attempts + 2):
                try:
                    if attempt == 1:
                        outline = await self._call_outline_with_timeout_retry(
                            run_id=run_id,
                            phase="outline.generate",
                            action=lambda: self.llm_client.generate_outline(
                                topic=run.input.topic,
                                project_id=run.input.project_id,
                                rag_source_ids=run.input.rag_source_ids,
                                template_style=effective_template_style,
                                target_slide_count=run.input.target_slide_count,
                                on_token=on_token,
                            ),
                        )
                    else:
                        await self._publish(
                            run_id,
                            EventType.OUTLINE_REPAIR_STARTED,
                            {
                                "attempt": attempt - 1,
                                "phase": "generate",
                                "error_category": error_category,
                                "error_details": error_details,
                            },
                        )
                        outline = await self._call_outline_with_timeout_retry(
                            run_id=run_id,
                            phase="outline.repair.generate",
                            action=lambda: self.llm_client.repair_outline(
                                topic=run.input.topic,
                                project_id=run.input.project_id,
                                rag_source_ids=run.input.rag_source_ids,
                                template_style=effective_template_style,
                                target_slide_count=run.input.target_slide_count,
                                previous_response=previous_response,
                                error_category=error_category,
                                error_details=error_details,
                            ),
                        )
                        await self._publish(
                            run_id,
                            EventType.OUTLINE_REPAIR_COMPLETED,
                            {"attempt": attempt - 1, "phase": "generate"},
                        )
                    break
                except OutlineFormatError as fmt_err:
                    previous_response = fmt_err.raw_response
                    error_category = fmt_err.category
                    error_details = list(fmt_err.details)
                    await self._publish(
                        run_id,
                        EventType.OUTLINE_REPAIR_FAILED,
                        {
                            "attempt": attempt,
                            "phase": "generate",
                            "error_category": error_category,
                            "error_details": error_details,
                        },
                    )
                    if attempt >= repair_attempts + 1:
                        await self._fail_run(
                            run_id,
                            "OUTLINE_DRAFTING",
                            "OUTLINE_REPAIR_EXHAUSTED",
                            retryable=True,
                            error_details={
                                "attempts": attempt,
                                "error_category": error_category,
                                "error_details": error_details,
                            },
                        )
                        return
                    continue
            if outline is None:
                await self._fail_run(
                    run_id,
                    "OUTLINE_DRAFTING",
                    "OUTLINE_REPAIR_EXHAUSTED",
                    retryable=True,
                    error_details={
                        "attempts": repair_attempts + 1,
                        "error_category": error_category,
                        "error_details": error_details,
                    },
                )
                return
            base_outline = outline
            try:
                outline = await self._call_outline_with_timeout_retry(
                    run_id=run_id,
                    phase="outline.critique",
                    action=lambda: self.llm_client.critique_outline(
                        topic=run.input.topic,
                        template_style=effective_template_style,
                        target_slide_count=run.input.target_slide_count,
                        outline=outline,
                    ),
                )
            except OutlineFormatError as fmt_err:
                await self._publish(
                    run_id,
                    EventType.OUTLINE_REPAIR_FAILED,
                    {
                        "attempt": 1,
                        "phase": "critique",
                        "error_category": fmt_err.category,
                        "error_details": list(fmt_err.details),
                    },
                )
                try:
                    await self._publish(
                        run_id,
                        EventType.OUTLINE_REPAIR_STARTED,
                        {
                            "attempt": 1,
                            "phase": "critique",
                            "error_category": fmt_err.category,
                            "error_details": list(fmt_err.details),
                        },
                    )
                    outline = await self._call_outline_with_timeout_retry(
                        run_id=run_id,
                        phase="outline.repair.critique",
                        action=lambda: self.llm_client.repair_outline(
                            topic=run.input.topic,
                            project_id=run.input.project_id,
                            rag_source_ids=run.input.rag_source_ids,
                            template_style=effective_template_style,
                            target_slide_count=run.input.target_slide_count,
                            previous_response=fmt_err.raw_response,
                            error_category=f"critique_{fmt_err.category}",
                            error_details=list(fmt_err.details),
                        ),
                    )
                    await self._publish(
                        run_id,
                        EventType.OUTLINE_REPAIR_COMPLETED,
                        {"attempt": 1, "phase": "critique"},
                    )
                except OutlineFormatError:
                    outline = base_outline
                    await self._publish(
                        run_id,
                        EventType.OUTLINE_REPAIR_COMPLETED,
                        {"attempt": 1, "phase": "critique", "fallback_used": True},
                    )
            enforce_layout_variety(nodes=outline.nodes, seed=f"{run.input.topic}|{effective_template_style}|{run_id}")
            design = self._resolve_design_profile(topic=run.input.topic, template_style=effective_template_style, requirements_report=requirements_report)

            def apply_outline(r: RunRecord) -> None:
                r.outline = outline
                r.research_report = requirements_report
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
                    "audience": requirements_report.get("audience", ""),
                    "purpose": requirements_report.get("purpose", ""),
                    "tone": requirements_report.get("tone", ""),
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
        except LLMTimeoutError as exc:
            await self._fail_run(
                run_id,
                "OUTLINE_DRAFTING",
                "OUTLINE_LLM_TIMEOUT",
                retryable=True,
                error_details={
                    "phase": exc.phase,
                    "attempts": exc.attempts,
                    "reason": self._exception_reason(exc),
                    "error_type": type(exc).__name__,
                    "provider_mode": self.settings.llm_api_style,
                },
            )
        except Exception as exc:
            reason = str(exc).strip() or repr(exc)
            await self._fail_run(
                run_id,
                "OUTLINE_DRAFTING",
                "OUTLINE_LLM_ERROR",
                retryable=True,
                error_details={
                    "reason": reason,
                    "error_type": type(exc).__name__,
                    "provider_mode": self.settings.llm_api_style,
                    "traceback": traceback.format_exc(limit=4),
                },
            )

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
        self._init_run_llm_budget(run_id=run_id, target_slide_count=run.input.target_slide_count)
        if run.input.visual_policy == VisualPolicy.MEDIA_REQUIRED and self.settings.asset_provider == "none":
            await self._fail_run(run_id, "SLIDES_GENERATING", "VISUAL_POLICY_UNSATISFIED", retryable=False)
            return
        effective_template_style = self._resolved_template_style(run)
        design = self._resolve_design_profile(topic=run.input.topic, template_style=effective_template_style, requirements_report=run.research_report if isinstance(run.research_report, dict) else {})

        artifact_dir = Path(run.artifact_dir)
        slides_dir = artifact_dir / "slides"
        output_dir = slides_dir / "output"
        imgs_dir = slides_dir / "imgs"
        slides_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        imgs_dir.mkdir(parents=True, exist_ok=True)

        slide_start = time.perf_counter()
        sem = asyncio.Semaphore(min(5, self.slide_concurrency, self.llm_request_concurrency))

        async def generate_one(slide_no: int, node: OutlineNode) -> None:
            async with sem:
                await self._publish(run_id, EventType.SLIDE_STARTED, {"slide_no": slide_no, "page_type": node.page_type.value})
                try:
                    artifact = await self._generate_skill_slide(run_id=run_id, slide_no=slide_no, node=node, design=design)
                except VisualPolicyUnsatisfiedError:
                    raise
                except SlideGenerationError:
                    raise
                except Exception as exc:
                    raise SlideGenerationError(
                        slide_no=slide_no,
                        phase="slide.pipeline",
                        reason=self._exception_reason(exc),
                        details={"error_type": type(exc).__name__},
                    ) from exc

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
        failures: list[dict[str, Any]] = []
        for item in results:
            if not isinstance(item, Exception):
                continue
            if isinstance(item, SlideGenerationError):
                payload = item.to_payload()
            else:
                payload = {
                    "slide_no": 0,
                    "phase": "slides.batch",
                    "reason": self._exception_reason(item),
                    "details": {"error_type": type(item).__name__},
                }
            failures.append(payload)
            await self._publish(run_id, EventType.SLIDE_FAILED, payload)
        if failures:
            await self._fail_run(
                run_id,
                "SLIDES_GENERATING",
                "SLIDE_LLM_ERROR",
                retryable=True,
                error_details={
                    "failure_count": len(failures),
                    "first_failure": failures[0],
                    "failures": failures[:8],
                },
            )
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
        self._clear_run_llm_budget(run_id)

    async def _generate_from_template(self, run_id: str) -> None:
        run = await self.store.get_run(run_id)
        assert run is not None and run.outline is not None
        self._init_run_llm_budget(run_id=run_id, target_slide_count=run.input.target_slide_count)
        effective_template_style = self._resolved_template_style(run)
        design = self._resolve_design_profile(topic=run.input.topic, template_style=effective_template_style, requirements_report=run.research_report if isinstance(run.research_report, dict) else {})
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
        self._clear_run_llm_budget(run_id)

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
        effective_template_style = self._resolved_template_style(run)
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
                reviewed = await self._call_llm_with_timeout_retry(
                    run_id=run_id,
                    phase=f"template.slide.{idx}.review",
                    action=lambda: self.llm_client.review_slide(
                        topic=run.input.topic,
                        template_style=effective_template_style,
                        slide_no=idx,
                        target_slide_count=run.input.target_slide_count,
                        outline_node=base_node,
                        candidate=candidate,
                        rule_violations=forced_issues or run.qa_report.get("issues", []),
                    ),
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
                rule_violations = self._check_slide_content_rules(candidate, node)
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
        issues: list[str] = []
        selected_repair_directives: list[str] = []
        selected_llm_issues: list[str] = []
        selected_preview_text = ""
        llm_score = 0
        round_passed = 0
        degraded_accept = False
        gate_threshold = 80

        best_js = ""
        best_generated: GeneratedSlide | None = None
        best_chart_plan: ChartPlan | None = None
        best_citations: list[str] = []
        best_variant: dict[str, Any] = {}
        current_spec: SlideSpec | None = None
        fatal_round_streak = 0

        for repair_round in range(1, self.max_slide_repair_rounds + 1):
            variant = {
                "mode": "spec_single",
                "round": repair_round,
                "layout_anchor": str(slide_plan.get("layout", "")),
                "seed": f"s{slide_no}-r{repair_round}-spec-single",
            }
            try:
                if repair_round == 1:
                    spec = await self._call_llm_with_timeout_retry(
                        run_id=run_id,
                        phase=f"slide.{slide_no}.round.{repair_round}.spec.generate",
                        action=lambda: self.llm_client.generate_slide_spec(
                            topic=run.input.topic,
                            template_style=effective_template_style,
                            slide_no=slide_no,
                            target_slide_count=run.input.target_slide_count,
                            outline_node=node,
                            rag_source_ids=run.input.rag_source_ids,
                            visual_policy=run.input.visual_policy,
                            slide_plan=slide_plan,
                            slide_brief=slide_brief,
                        ),
                    )
                    current_spec = spec
                    await self._publish(
                        run_id,
                        EventType.SLIDE_SPEC_GENERATED,
                        {
                            "slide_no": slide_no,
                            "round": repair_round,
                            "page_type": spec.page_type.value,
                            "layout_hint": spec.layout_hint,
                            "visual_kind": spec.visual_kind,
                            "bullet_count": len(spec.bullets),
                        },
                    )
                else:
                    if current_spec is None:
                        fallback_generated = best_generated or GeneratedSlide(
                            title=node.title,
                            bullets=list(node.bullets),
                            citations=[],
                            page_type=node.page_type,
                            layout_hint=node.layout_hint,
                        )
                        current_spec = self._slide_spec_from_generated(generated=fallback_generated, node=node)
                    spec = await self._call_llm_with_timeout_retry(
                        run_id=run_id,
                        phase=f"slide.{slide_no}.round.{repair_round}.spec.repair",
                        action=lambda: self.llm_client.repair_slide_spec(
                            topic=run.input.topic,
                            template_style=effective_template_style,
                            slide_no=slide_no,
                            target_slide_count=run.input.target_slide_count,
                            outline_node=node,
                            previous_spec=current_spec,
                            issues=issues,
                            repair_directives=selected_repair_directives,
                            visual_policy=run.input.visual_policy,
                            slide_plan=slide_plan,
                            slide_brief=slide_brief,
                        ),
                    )
                    current_spec = spec
                    await self._publish(
                        run_id,
                        EventType.SLIDE_SPEC_REPAIRED,
                        {
                            "slide_no": slide_no,
                            "round": repair_round,
                            "page_type": spec.page_type.value,
                            "layout_hint": spec.layout_hint,
                            "visual_kind": spec.visual_kind,
                            "bullet_count": len(spec.bullets),
                        },
                    )
            except Exception as exc:
                reason = self._exception_reason(exc)
                await self._publish(
                    run_id,
                    EventType.SLIDE_CANDIDATE_GENERATED,
                    {
                        "slide_no": slide_no,
                        "round": repair_round,
                        "candidate": 1,
                        "score": 0,
                        "passed": False,
                        "hard_issue_count": 1,
                        "llm_issue_count": 0,
                        "error": reason,
                        "phase": ("spec.generate" if repair_round == 1 else "spec.repair"),
                        "variant": variant,
                    },
                )
                if repair_round == 1:
                    try:
                        legacy_generated = await self._call_llm_with_timeout_retry(
                            run_id=run_id,
                            phase=f"slide.{slide_no}.round.{repair_round}.legacy.generate",
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
                        spec = self._slide_spec_from_generated(generated=legacy_generated, node=node)
                    except Exception:
                        spec = self._slide_spec_from_generated(
                            generated=GeneratedSlide(
                                title=node.title,
                                bullets=list(node.bullets),
                                citations=[],
                                page_type=node.page_type,
                                layout_hint=node.layout_hint,
                            ),
                            node=node,
                        )
                    current_spec = spec
                    await self._publish(
                        run_id,
                        EventType.SLIDE_SPEC_GENERATED,
                        {
                            "slide_no": slide_no,
                            "round": repair_round,
                            "fallback": "legacy_slide_content",
                            "page_type": spec.page_type.value,
                            "layout_hint": spec.layout_hint,
                            "visual_kind": spec.visual_kind,
                            "bullet_count": len(spec.bullets),
                        },
                    )
                else:
                    if current_spec is None:
                        current_spec = self._slide_spec_from_generated(
                            generated=GeneratedSlide(
                                title=node.title,
                                bullets=list(node.bullets),
                                citations=[],
                                page_type=node.page_type,
                                layout_hint=node.layout_hint,
                            ),
                            node=node,
                        )

            generated = self._generated_from_slide_spec(spec=current_spec, node=node)
            citations = self._normalize_citations(list(current_spec.citations), run.input.rag_source_ids, slide_no)
            generated.citations = citations

            chart_plan = self._build_chart_plan_from_bullets(
                node=OutlineNode(
                    title=generated.title,
                    bullets=list(generated.bullets),
                    page_type=node.page_type,
                    layout_hint=generated.layout_hint or node.layout_hint,
                ),
                source_refs=citations,
            )
            js_code = self._render_skill_slide_js(
                slide_no=slide_no,
                total=run.input.target_slide_count,
                node=node,
                generated=generated,
                design=design,
                chart_plan=chart_plan,
            )
            candidate_path = slides_dir / f"slide-{slide_no:02d}-cand-01.js"
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
            if fatal_contract:
                preview_mode = "skip_contract_failure"
                preview_issues.append("preview skipped due to fatal contract issue")
            else:
                preview_issues, preview_text = await self._run_slide_preview_qa_with_text(
                    run_id=run_id,
                    slide_js=candidate_path,
                    slide_no=slide_no,
                )
            hard_issues.extend(preview_issues)

            llm_eval_degraded = False
            try:
                llm_gate = await self._call_llm_with_timeout_retry(
                    run_id=run_id,
                    phase=f"slide.{slide_no}.round.{repair_round}.candidate.1.evaluate",
                    action=lambda: self.llm_client.evaluate_slide_quality(
                        topic=run.input.topic,
                        template_style=effective_template_style,
                        slide_no=slide_no,
                        target_slide_count=run.input.target_slide_count,
                        outline_node=node,
                        candidate_js=js_code,
                        preview_text=preview_text,
                        hard_issues=hard_issues,
                        visual_policy=run.input.visual_policy,
                        slide_brief=slide_brief,
                    ),
                )
            except LLMTimeoutError:
                llm_eval_degraded = True
                llm_gate = self._fallback_quality_gate(
                    hard_issues=hard_issues,
                    preview_text=preview_text,
                    candidate_js=js_code,
                )

            llm_score = int(llm_gate.get("score", 0))
            llm_issues = [str(item) for item in llm_gate.get("issues", [])]
            repair_directives = [str(item) for item in llm_gate.get("repair_directives", [])]
            issues_1 = list(hard_issues)
            if llm_score < gate_threshold:
                issues_1.append(f"quality score below threshold: {llm_score} < {gate_threshold}")
            issues_1.extend(llm_issues)
            issues_1 = self._dedupe_preserve_order(issues_1)
            candidate_eval_items: list[dict[str, Any]] = [
                {
                    "candidate": 1,
                    "mode": "spec_renderer",
                    "variant": variant,
                    "candidate_js": js_code,
                    "generated": generated,
                    "chart_plan": chart_plan,
                    "citations": list(citations),
                    "score": llm_score,
                    "hard_issues": list(hard_issues),
                    "llm_issues": list(llm_issues),
                    "repair_directives": list(repair_directives),
                    "issues": list(issues_1),
                    "passed": not issues_1,
                    "preview_text": preview_text,
                    "preview_mode": preview_mode,
                    "degraded": llm_eval_degraded,
                }
            ]
            await self._publish(
                run_id,
                EventType.SLIDE_CANDIDATE_GENERATED,
                {
                    "slide_no": slide_no,
                    "round": repair_round,
                    "candidate": 1,
                    "score": llm_score,
                    "passed": not issues_1,
                    "hard_issue_count": len(hard_issues),
                    "llm_issue_count": len(llm_issues),
                    "degraded": llm_eval_degraded,
                    "preview_mode": preview_mode,
                    "variant": variant,
                },
            )

            # Candidate 2: creative JS directly from LLM (recover high-ceiling generation).
            creative_variant = {
                "mode": "creative_js",
                "round": repair_round,
                "layout_anchor": str(slide_plan.get("layout", "")),
                "seed": f"s{slide_no}-r{repair_round}-creative",
            }
            creative_plan = dict(slide_plan)
            creative_plan["candidate_worker"] = 2
            creative_plan["variant"] = creative_variant
            creative_plan["repair_round"] = repair_round
            creative_plan["previous_issues"] = issues_1[:8]
            creative_citations = self._normalize_citations([], run.input.rag_source_ids, slide_no)
            creative_chart_plan = self._build_chart_plan_from_bullets(
                node=OutlineNode(
                    title=node.title,
                    bullets=list(node.bullets),
                    page_type=node.page_type,
                    layout_hint=node.layout_hint,
                ),
                source_refs=creative_citations,
            )
            try:
                if repair_round == 1:
                    creative_js = await self._call_llm_with_timeout_retry(
                        run_id=run_id,
                        phase=f"slide.{slide_no}.round.{repair_round}.candidate.2.build",
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
                            slide_plan=creative_plan,
                            slide_brief=slide_brief,
                        ),
                    )
                else:
                    creative_directives = list(repair_directives) + ["candidate mode=creative_js"]
                    creative_js = await self._call_llm_with_timeout_retry(
                        run_id=run_id,
                        phase=f"slide.{slide_no}.round.{repair_round}.candidate.2.repair",
                        action=lambda: self.llm_client.critique_slide_js(
                            topic=run.input.topic,
                            template_style=effective_template_style,
                            slide_no=slide_no,
                            target_slide_count=run.input.target_slide_count,
                            outline_node=node,
                            candidate_js=best_js or js_code,
                            issues=issues_1 if not issues else issues,
                            visual_policy=run.input.visual_policy,
                            slide_plan=creative_plan,
                            repair_directives=creative_directives,
                            preview_text=selected_preview_text or preview_text,
                            slide_brief=slide_brief,
                        ),
                    )
                creative_path = slides_dir / f"slide-{slide_no:02d}-cand-02.js"
                creative_path.write_text(creative_js, encoding="utf-8")
                hard_issues_2 = self._validate_slide_js_contract(
                    creative_js,
                    slide_no=slide_no,
                    page_type=node.page_type.value,
                    visual_policy=run.input.visual_policy,
                )
                fatal_contract_2 = any(
                    issue in {"missing export contract", "createSlide signature invalid", "createSlide must be synchronous"}
                    for issue in hard_issues_2
                )
                preview_mode_2 = "full"
                preview_text_2 = ""
                preview_issues_2: list[str] = []
                if fatal_contract_2:
                    preview_mode_2 = "skip_contract_failure"
                    preview_issues_2.append("preview skipped due to fatal contract issue")
                else:
                    preview_issues_2, preview_text_2 = await self._run_slide_preview_qa_with_text(
                        run_id=run_id,
                        slide_js=creative_path,
                        slide_no=slide_no,
                    )
                hard_issues_2.extend(preview_issues_2)
                llm_eval_degraded_2 = False
                try:
                    llm_gate_2 = await self._call_llm_with_timeout_retry(
                        run_id=run_id,
                        phase=f"slide.{slide_no}.round.{repair_round}.candidate.2.evaluate",
                        action=lambda: self.llm_client.evaluate_slide_quality(
                            topic=run.input.topic,
                            template_style=effective_template_style,
                            slide_no=slide_no,
                            target_slide_count=run.input.target_slide_count,
                            outline_node=node,
                            candidate_js=creative_js,
                            preview_text=preview_text_2,
                            hard_issues=hard_issues_2,
                            visual_policy=run.input.visual_policy,
                            slide_brief=slide_brief,
                        ),
                    )
                except LLMTimeoutError:
                    llm_eval_degraded_2 = True
                    llm_gate_2 = self._fallback_quality_gate(
                        hard_issues=hard_issues_2,
                        preview_text=preview_text_2,
                        candidate_js=creative_js,
                    )
                score_2 = int(llm_gate_2.get("score", 0))
                llm_issues_2 = [str(item) for item in llm_gate_2.get("issues", [])]
                repair_directives_2 = [str(item) for item in llm_gate_2.get("repair_directives", [])]
                issues_2 = list(hard_issues_2)
                if score_2 < gate_threshold:
                    issues_2.append(f"quality score below threshold: {score_2} < {gate_threshold}")
                issues_2.extend(llm_issues_2)
                issues_2 = self._dedupe_preserve_order(issues_2)
                candidate_eval_items.append(
                    {
                        "candidate": 2,
                        "mode": "creative_js",
                        "variant": creative_variant,
                        "candidate_js": creative_js,
                        "generated": None,
                        "chart_plan": creative_chart_plan,
                        "citations": list(creative_citations),
                        "score": score_2,
                        "hard_issues": list(hard_issues_2),
                        "llm_issues": list(llm_issues_2),
                        "repair_directives": list(repair_directives_2),
                        "issues": list(issues_2),
                        "passed": not issues_2,
                        "preview_text": preview_text_2,
                        "preview_mode": preview_mode_2,
                        "degraded": llm_eval_degraded_2,
                    }
                )
                await self._publish(
                    run_id,
                    EventType.SLIDE_CANDIDATE_GENERATED,
                    {
                        "slide_no": slide_no,
                        "round": repair_round,
                        "candidate": 2,
                        "score": score_2,
                        "passed": not issues_2,
                        "hard_issue_count": len(hard_issues_2),
                        "llm_issue_count": len(llm_issues_2),
                        "degraded": llm_eval_degraded_2,
                        "preview_mode": preview_mode_2,
                        "variant": creative_variant,
                    },
                )
                creative_path.unlink(missing_ok=True)
            except Exception as exc:
                await self._publish(
                    run_id,
                    EventType.SLIDE_CANDIDATE_GENERATED,
                    {
                        "slide_no": slide_no,
                        "round": repair_round,
                        "candidate": 2,
                        "score": 0,
                        "passed": False,
                        "hard_issue_count": 1,
                        "llm_issue_count": 0,
                        "error": self._exception_reason(exc),
                        "phase": "candidate.build",
                        "variant": creative_variant,
                    },
                )

            candidate_eval_items.sort(
                key=lambda item: (
                    len(item["hard_issues"]),
                    0 if item["passed"] else 1,
                    0 if not item.get("degraded", False) else 1,
                    -int(item["score"]),
                    len(item["issues"]),
                )
            )
            best = candidate_eval_items[0]
            llm_score = int(best["score"])
            issues = [str(x) for x in best["issues"]]
            selected_llm_issues = [str(x) for x in best["llm_issues"]]
            selected_repair_directives = [str(x) for x in best["repair_directives"]]
            selected_preview_text = str(best["preview_text"])
            best_js = str(best["candidate_js"])
            best_generated = best.get("generated")
            best_chart_plan = best.get("chart_plan")
            best_citations = [str(x) for x in best.get("citations", [])]
            best_variant = dict(best.get("variant", {}))
            await self._append_candidate_selection_entry(
                run_id=run_id,
                entry={
                    "slide_no": slide_no,
                    "round": repair_round,
                    "selected_candidate": int(best["candidate"]),
                    "selected_score": llm_score,
                    "selected_passed": bool(best["passed"]),
                    "selected_degraded": bool(best.get("degraded", False)),
                    "selected_variant": best_variant,
                    "degraded_accept": False,
                    "candidates": [{
                        "candidate": int(item["candidate"]),
                        "mode": str(item.get("mode", "")),
                        "variant": item.get("variant", {}),
                        "score": int(item["score"]),
                        "passed": bool(item["passed"]),
                        "degraded": bool(item.get("degraded", False)),
                        "hard_issue_count": len(item["hard_issues"]),
                        "llm_issue_count": len(item["llm_issues"]),
                        "preview_mode": item.get("preview_mode", "full"),
                    } for item in candidate_eval_items],
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
                    "passed": not issues,
                    "degraded": bool(best.get("degraded", False)),
                    "variant": best_variant,
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
                    "degraded": bool(best.get("degraded", False)),
                },
            )

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
            if self._issues_have_fatal_markers(issues):
                fatal_round_streak += 1
            else:
                fatal_round_streak = 0
            early_stop_rounds = min(self.slide_fatal_early_stop_rounds, self.max_slide_repair_rounds)
            if fatal_round_streak >= early_stop_rounds:
                if self.keep_failed_candidate_js and best_js:
                    self._persist_failed_candidate_js(
                        slides_dir=slides_dir,
                        slide_no=slide_no,
                        js_code=best_js,
                        round_no=repair_round,
                        issues=issues[:20],
                    )
                raise SlideGenerationError(
                    slide_no=slide_no,
                    phase="candidate.fatal_early_stop",
                    reason=f"fatal issues repeated for {fatal_round_streak} rounds",
                    round_no=repair_round,
                    details={"issues": issues[:20], "fatal_streak": fatal_round_streak},
                )

        if round_passed == 0:
            if any("visual_policy" in issue for issue in issues):
                raise VisualPolicyUnsatisfiedError(
                    f"slide {slide_no} violated visual policy={run.input.visual_policy.value}: {issues}"
                )
            critical_markers = (
                "missing export contract",
                "createSlide signature invalid",
                "createSlide must be synchronous",
                "preview compile failed",
                "preview pptx missing",
                "out of slide bounds",
            )
            has_critical = any(any(marker in issue for marker in critical_markers) for issue in issues)
            if not has_critical and best_js:
                slide_path.write_text(best_js, encoding="utf-8")
                round_passed = self.max_slide_repair_rounds
                degraded_accept = True
                await self._publish(
                    run_id,
                    EventType.SLIDE_REPAIR_COMPLETED,
                    {
                        "slide_no": slide_no,
                        "round": self.max_slide_repair_rounds,
                        "degraded_accept": True,
                        "issues": issues[:10],
                    },
                )
            else:
                if self.keep_failed_candidate_js and best_js:
                    self._persist_failed_candidate_js(
                        slides_dir=slides_dir,
                        slide_no=slide_no,
                        js_code=best_js,
                        round_no=self.max_slide_repair_rounds,
                        issues=issues[:20],
                    )
                raise SlideGenerationError(
                    slide_no=slide_no,
                    phase="candidate.rounds_exhausted",
                    reason=f"failed after {self.max_slide_repair_rounds} rounds",
                    round_no=self.max_slide_repair_rounds,
                    details={"issues": issues[:20]},
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
                "issues_last_round": issues,
                "engine": self.settings.generation_engine,
                "quality_score": llm_score,
                "visual_policy": run.input.visual_policy.value,
                "selected_variant": best_variant,
                "degraded_accept": degraded_accept,
                "preview_text_excerpt": selected_preview_text[:300],
                "repair_directives": selected_repair_directives[:8],
                "llm_issues": selected_llm_issues[:8],
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
        if "addGroup(" in js_code:
            issues.append("forbidden api detected: addGroup()")
        if re.search(r"addShape\(\s*['\"][a-zA-Z0-9_-]+['\"]", js_code):
            issues.append("addShape must use pres.shapes enum, not string literal")
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
        issues.extend(self._collect_js_style_issues(js_code=js_code, page_type=page_type))
        return self._dedupe_preserve_order(issues)

    def _issues_have_fatal_markers(self, issues: list[str]) -> bool:
        markers = (
            "missing export contract",
            "createSlide signature invalid",
            "createSlide must be synchronous",
            "preview compile failed",
            "preview pptx missing",
            "JSONDecodeError",
            "LLM_OUTPUT_NOT_EXECUTABLE",
        )
        for issue in issues:
            text = str(issue)
            if any(marker in text for marker in markers):
                return True
        return False

    def _persist_failed_candidate_js(
        self,
        *,
        slides_dir: Path,
        slide_no: int,
        js_code: str,
        round_no: int,
        issues: list[str],
    ) -> None:
        failed_dir = slides_dir / "failed"
        failed_dir.mkdir(parents=True, exist_ok=True)
        failed_js = failed_dir / f"slide-{slide_no:02d}-last.js"
        failed_meta = failed_dir / f"slide-{slide_no:02d}-last.meta.json"
        failed_js.write_text(js_code, encoding="utf-8")
        failed_meta.write_text(
            json.dumps(
                {
                    "slide_no": slide_no,
                    "round": round_no,
                    "issues": issues[:20],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _collect_js_style_issues(self, *, js_code: str, page_type: str) -> list[str]:
        issues: list[str] = []
        boxes = self._collect_js_layout_boxes(js_code)
        if not boxes:
            return issues

        major_boxes = [
            box
            for box in boxes
            if not self._is_js_page_badge_box(box)
            and (box.element_type in {"text", "image", "chart"} or box.area >= 0.45)
        ]
        margin_floor = 0.5 if page_type == "content" else 0.35

        for idx, box in enumerate(major_boxes, start=1):
            if box.x < -0.01 or box.y < -0.01 or box.x + box.w > SLIDE_WIDTH_IN + 0.01 or box.y + box.h > SLIDE_HEIGHT_IN + 0.01:
                issues.append(f"box-{idx} out of slide bounds")
                continue
            if page_type == "content":
                left = box.x
                top = box.y
                right = SLIDE_WIDTH_IN - (box.x + box.w)
                bottom = SLIDE_HEIGHT_IN - (box.y + box.h)
                lowered_expr = box.text_expr.lower()
                is_title_box = box.element_type == "text" and "slideconfig.title" in lowered_expr
                if is_title_box:
                    if min(left, right) < margin_floor - 0.03:
                        issues.append(f"box-{idx} horizontal margin too tight (<{margin_floor:.1f}in)")
                elif min(left, right, top, bottom) < margin_floor - 0.03:
                    issues.append(f"box-{idx} margin too tight (<{margin_floor:.1f}in)")

        for i in range(len(major_boxes)):
            for j in range(i + 1, len(major_boxes)):
                if self._is_js_intentional_container_overlap(major_boxes[i], major_boxes[j]):
                    continue
                overlap_ratio = self._js_box_overlap_ratio(major_boxes[i], major_boxes[j])
                if overlap_ratio >= 0.12:
                    issues.append(f"box-{i + 1} overlaps box-{j + 1} (ratio={overlap_ratio:.2f})")
                if page_type == "content":
                    gap = self._js_major_block_gap(major_boxes[i], major_boxes[j])
                    if gap is not None and 0 < gap < 0.22:
                        issues.append(f"box-{i + 1} and box-{j + 1} gap too tight ({gap:.2f}\" < 0.22\")")

        text_boxes = [box for box in boxes if box.element_type == "text" and not self._is_js_page_badge_box(box)]
        title_box = next((box for box in text_boxes if "slideconfig.title" in box.text_expr.lower()), None)
        body_font_sizes: list[float] = []
        for box in text_boxes:
            lowered_expr = box.text_expr.lower()
            looks_like_body = box.y >= 1.0 or any(token in lowered_expr for token in ("bullets", "rows", "item", "note", "takeaway"))
            if looks_like_body and box.font_size is not None:
                body_font_sizes.append(box.font_size)
            if page_type == "content" and looks_like_body:
                if (box.align or "").lower() == "center" and box.h >= 0.32:
                    issues.append("body text must be left-aligned (center detected)")
                if box.bold is True and (box.font_size is None or box.font_size <= 24):
                    issues.append("body text should not use bold")
                if box.w >= 1.2 and box.h >= 0.35 and (box.fit or "").lower() != "shrink":
                    issues.append("body text missing fit:'shrink'")

        if title_box is not None:
            if (title_box.fit or "").lower() != "shrink":
                issues.append("title missing fit:'shrink'")
            if title_box.font_size is not None:
                if title_box.font_size < 36:
                    issues.append(f"title font too small ({title_box.font_size:.0f} < 36)")
                if body_font_sizes and title_box.font_size < max(body_font_sizes) + 18:
                    issues.append("title/body size contrast too weak")

        return self._dedupe_preserve_order(issues)

    def _collect_js_layout_boxes(self, js_code: str) -> list[JsLayoutBox]:
        boxes: list[JsLayoutBox] = []
        for method in ("addText", "addShape", "addImage", "addChart"):
            for first_arg, options_raw in self._extract_slide_method_calls(js_code, method):
                x = self._parse_js_float_option(options_raw, "x")
                y = self._parse_js_float_option(options_raw, "y")
                w = self._parse_js_float_option(options_raw, "w")
                h = self._parse_js_float_option(options_raw, "h")
                if x is None or y is None or w is None or h is None or w <= 0 or h <= 0:
                    continue
                element_type = "text" if method == "addText" else ("shape" if method == "addShape" else ("image" if method == "addImage" else "chart"))
                boxes.append(
                    JsLayoutBox(
                        element_type=element_type,
                        x=x,
                        y=y,
                        w=w,
                        h=h,
                        text_expr=first_arg,
                        options_raw=options_raw,
                        font_size=self._parse_js_float_option(options_raw, "fontSize") if method == "addText" else None,
                        align=self._parse_js_string_option(options_raw, "align") if method == "addText" else None,
                        bold=self._parse_js_bool_option(options_raw, "bold") if method == "addText" else None,
                        fit=self._parse_js_string_option(options_raw, "fit") if method == "addText" else None,
                    )
                )
        return boxes

    def _extract_slide_method_calls(self, js_code: str, method: str) -> list[tuple[str, str]]:
        token = f"slide.{method}("
        calls: list[tuple[str, str]] = []
        cursor = 0
        while True:
            start = js_code.find(token, cursor)
            if start < 0:
                break
            open_idx = start + len(token) - 1
            close_idx = self._find_matching_delimiter(js_code, start_idx=open_idx, open_char="(", close_char=")")
            if close_idx < 0:
                cursor = start + len(token)
                continue
            args_raw = js_code[open_idx + 1 : close_idx]
            parts = self._split_top_level_args(args_raw)
            if len(parts) >= 2:
                calls.append((parts[0].strip(), parts[1].strip()))
            cursor = close_idx + 1
        return calls

    def _find_matching_delimiter(self, text: str, *, start_idx: int, open_char: str, close_char: str) -> int:
        depth = 0
        quote: str | None = None
        escape = False
        for idx in range(start_idx, len(text)):
            ch = text[idx]
            if quote is not None:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == quote:
                    quote = None
                continue
            if ch in {"'", '"', "`"}:
                quote = ch
                continue
            if ch == open_char:
                depth += 1
                continue
            if ch == close_char:
                depth -= 1
                if depth == 0:
                    return idx
        return -1

    def _split_top_level_args(self, raw_args: str) -> list[str]:
        parts: list[str] = []
        buf: list[str] = []
        depth_round = 0
        depth_curly = 0
        depth_square = 0
        quote: str | None = None
        escape = False

        for ch in raw_args:
            if quote is not None:
                buf.append(ch)
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == quote:
                    quote = None
                continue
            if ch in {"'", '"', "`"}:
                quote = ch
                buf.append(ch)
                continue
            if ch == "(":
                depth_round += 1
            elif ch == ")":
                depth_round = max(0, depth_round - 1)
            elif ch == "{":
                depth_curly += 1
            elif ch == "}":
                depth_curly = max(0, depth_curly - 1)
            elif ch == "[":
                depth_square += 1
            elif ch == "]":
                depth_square = max(0, depth_square - 1)
            elif ch == "," and depth_round == 0 and depth_curly == 0 and depth_square == 0:
                parts.append("".join(buf).strip())
                buf = []
                continue
            buf.append(ch)

        tail = "".join(buf).strip()
        if tail:
            parts.append(tail)
        return parts

    def _parse_js_float_option(self, options_raw: str, key: str) -> float | None:
        match = re.search(rf"\b{re.escape(key)}\s*:\s*(-?\d+(?:\.\d+)?)\b", options_raw)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    def _parse_js_string_option(self, options_raw: str, key: str) -> str | None:
        match = re.search(rf"\b{re.escape(key)}\s*:\s*(['\"])(.*?)\1", options_raw, flags=re.S)
        if not match:
            return None
        return match.group(2).strip()

    def _parse_js_bool_option(self, options_raw: str, key: str) -> bool | None:
        match = re.search(rf"\b{re.escape(key)}\s*:\s*(true|false)\b", options_raw)
        if not match:
            return None
        return match.group(1) == "true"

    def _is_js_page_badge_box(self, box: JsLayoutBox) -> bool:
        if box.x >= 9.1 and box.y >= 5.0 and box.w <= 0.7 and box.h <= 0.7:
            return True
        lowered = box.text_expr.lower()
        if "slideconfig.index" in lowered and box.w <= 0.8 and box.h <= 0.8:
            return True
        return False

    def _is_js_intentional_container_overlap(self, left: JsLayoutBox, right: JsLayoutBox) -> bool:
        if left.element_type == right.element_type:
            return False
        if "shape" not in {left.element_type, right.element_type}:
            return False
        container = left if left.element_type == "shape" else right
        inner = right if container is left else left
        tol = 0.08
        inside = (
            inner.x >= container.x - tol
            and inner.y >= container.y - tol
            and inner.x + inner.w <= container.x + container.w + tol
            and inner.y + inner.h <= container.y + container.h + tol
        )
        if not inside:
            return False
        if container.area <= 0:
            return False
        ratio = inner.area / container.area
        return 0.05 <= ratio <= 0.95

    def _js_box_overlap_ratio(self, left: JsLayoutBox, right: JsLayoutBox) -> float:
        x_overlap = max(0.0, min(left.x + left.w, right.x + right.w) - max(left.x, right.x))
        y_overlap = max(0.0, min(left.y + left.h, right.y + right.h) - max(left.y, right.y))
        if x_overlap <= 0 or y_overlap <= 0:
            return 0.0
        overlap_area = x_overlap * y_overlap
        min_area = min(left.area, right.area)
        if min_area <= 0:
            return 0.0
        return overlap_area / min_area

    def _js_major_block_gap(self, left: JsLayoutBox, right: JsLayoutBox) -> float | None:
        x_overlap = min(left.x + left.w, right.x + right.w) - max(left.x, right.x)
        y_overlap = min(left.y + left.h, right.y + right.h) - max(left.y, right.y)
        if x_overlap > 0:
            if left.y <= right.y:
                return max(0.0, right.y - (left.y + left.h))
            return max(0.0, left.y - (right.y + right.h))
        if y_overlap > 0:
            if left.x <= right.x:
                return max(0.0, right.x - (left.x + left.w))
            return max(0.0, left.x - (right.x + right.w))
        return None

    def _dedupe_preserve_order(self, issues: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in issues:
            key = item.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(key)
        return out

    def _fallback_quality_gate(self, *, hard_issues: list[str], preview_text: str, candidate_js: str) -> dict[str, Any]:
        score = 92 - len(hard_issues) * 15
        text = (preview_text or "").strip()
        lowered = candidate_js.lower()
        issues: list[str] = []
        directives: list[str] = []
        if len(text) < 20:
            score -= 18
            issues.append("preview text too short")
            directives.append("expand concrete natural-language copy")
        if re.search(r"(placeholder|lorem|ipsum|todo|xxxx)", lowered):
            score -= 25
            issues.append("placeholder-like code/text remains")
            directives.append("replace placeholders with natural language")
        score = max(0, min(100, int(score)))
        return {"score": score, "issues": issues, "repair_directives": directives}

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
            asset_bytes, ext = await asyncio.to_thread(
                self._fetch_slot_asset,
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
                    "    slide.addText((cp.note || 'Qualitative trend summary.').slice(0, 160), { x: 5.15, y: 1.92, w: 3.7, h: 1.0, fontSize: 13, fontFace: fonts.body, color: theme.secondary, bold: false, align: 'left', margin: 0, fit: 'shrink' });",
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
                page_type = page_type_match.group(1) if page_type_match else ""
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
                if idx > 1 and ("addPageBadge(pres, slide, theme" not in text or "x: 9.3, y: 5.1" not in text):
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
                layout_match = re.search(r"layoutHint:\s*['\"]([^'\"]+)['\"]", text)
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
        report = {
            "passed": not deduped_issues,
            "issues": deduped_issues,
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
        preview_file = slide_js.parent / f"slide-{slide_no:02d}-preview.pptx"
        preview_runner = slide_js.parent / f".preview-runner-{slide_no:02d}.js"
        preview_runner.write_text(
            self._build_preview_runner_js(slide_js_name=slide_js.name, preview_name=preview_file.name),
            encoding="utf-8",
        )
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["node", preview_runner.name],
                cwd=slide_js.parent,
                capture_output=True,
                text=True,
                check=False,
            )
        finally:
            preview_runner.unlink(missing_ok=True)
        if result.returncode != 0:
            reason, details = self._summarize_process_failure(stderr=result.stderr or "", stdout=result.stdout or "")
            issues.append(f"{slide_js.name}: preview compile failed: {reason}")
            if details:
                issues.append(f"{slide_js.name}: preview compile details: {details}")
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
        # Mandatory polish is an execution step, not a hard quality gate.
        # Even if qa_ok is False here, caller should continue into normal QA/repair flow.
        return True

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
        effective_template_style = self._resolved_template_style(run)
        if self._use_agentic_engine():
            for slide in sorted(run.slides, key=lambda x: x.slide_no):
                node = run.outline.nodes[slide.slide_no - 1]
                rule_issues = forced_issues or run.qa_report.get("issues", [])
                slide_plan = self._build_slide_plan(node=node, design=design, slide_no=slide.slide_no)
                slide_brief = self._build_slide_brief(run=run, node=node, slide_no=slide.slide_no, slide_plan=slide_plan)
                try:
                    revised_js = await self._call_llm_with_timeout_retry(
                        run_id=run_id,
                        phase=f"slide.{slide.slide_no}.polish.critic_js",
                        action=lambda: self.llm_client.critique_slide_js(
                            topic=run.input.topic,
                            template_style=effective_template_style,
                            slide_no=slide.slide_no,
                            target_slide_count=run.input.target_slide_count,
                            outline_node=node,
                            candidate_js=slide.js_code,
                            issues=[str(item) for item in rule_issues],
                            visual_policy=run.input.visual_policy,
                            slide_plan=slide_plan,
                            repair_directives=[str(item) for item in rule_issues],
                            slide_brief=slide_brief,
                        ),
                    )
                except Exception as exc:
                    await self._append_quality_entry(
                        run_id=run_id,
                        entry={
                            "slide_no": slide.slide_no,
                            "passed_round": 1,
                            "issues_last_round": [f"polish skipped: {self._exception_reason(exc)}"],
                            "engine": self.settings.generation_engine,
                            "repair_mode": "critic_js_skipped",
                        },
                    )
                    continue
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
            try:
                reviewed = await self._call_llm_with_timeout_retry(
                    run_id=run_id,
                    phase=f"slide.{slide.slide_no}.polish.review",
                    action=lambda: self.llm_client.review_slide(
                        topic=run.input.topic,
                        template_style=effective_template_style,
                        slide_no=slide.slide_no,
                        target_slide_count=run.input.target_slide_count,
                        outline_node=node,
                        candidate=candidate,
                        rule_violations=forced_issues or run.qa_report.get("issues", []),
                    ),
                )
            except Exception as exc:
                await self._append_quality_entry(
                    run_id=run_id,
                    entry={
                        "slide_no": slide.slide_no,
                        "passed_round": 1,
                        "issues_last_round": [f"polish skipped: {self._exception_reason(exc)}"],
                        "engine": self.settings.generation_engine,
                        "repair_mode": "review_skipped",
                    },
                )
                continue
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
            note="Qualitative trend view; quantitative values not supplied in source bullets.",
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




























