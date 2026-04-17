from __future__ import annotations

import time
import traceback
from typing import Any

from ...design.skill_profile import enforce_layout_variety
from ...design.style_catalog import STYLE_PRESET_AUTO
from ...llm import LLMTimeoutError, OutlineFormatError
from ...models import EventType, OutlineDocument, OutlineHistoryEntry, RunRecord, RunStatus
from ...infra.store import now_iso
from ...rag import StratumindSearchError


class OutlineFlowService:
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator

    async def execute(self, run_id: str) -> None:
        orch = self.orch
        started = time.perf_counter()
        run = await orch.store.get_run(run_id)
        if run is None:
            return
        try:
            requested_template_style = orch._requested_template_style(run)
            await orch._publish(
                run_id,
                EventType.REQUIREMENTS_ANALYZING_STARTED,
                {
                    "target_slide_count": run.input.target_slide_count,
                    "project_id": run.input.project_id,
                    "has_rag": bool(run.input.rag_source_ids),
                },
            )
            selected_sources = [item for item in run.input.rag_source_ids if str(item).strip()]
            try:
                rag_context_snippets, rag_retrieval = await orch._retrieve_outline_rag_context(run_id=run_id, run=run)
            except StratumindSearchError as exc:
                if selected_sources:
                    await orch._fail_run(
                        run_id,
                        "OUTLINE_DRAFTING",
                        "OUTLINE_RAG_RETRIEVAL_FAILED",
                        retryable=exc.retryable,
                        error_details={
                            "error_code": exc.code,
                            "status_code": exc.status_code,
                            "reason": exc.message,
                            "details": exc.details or {},
                        },
                    )
                    return
                rag_context_snippets = []
                rag_retrieval = {
                    "mode": "project_all",
                    "selected_file_count": 0,
                    "top_k": orch._rag_query_top_k(target_slide_count=run.input.target_slide_count),
                    "enabled": bool(getattr(orch.rag_client, "enabled", False)),
                    "hit_count": 0,
                    "degraded": True,
                    "degrade_reason": "retrieval_error",
                    "error_code": exc.code,
                    "status_code": exc.status_code,
                    "retryable": exc.retryable,
                    "reason": exc.message,
                    "details": exc.details or {},
                }
            if selected_sources and not rag_context_snippets:
                error_code = (
                    "OUTLINE_RAG_UNAVAILABLE"
                    if not bool(rag_retrieval.get("enabled", True))
                    else "OUTLINE_RAG_NO_MATCH_FOR_SELECTED_SOURCES"
                )
                await orch._fail_run(
                    run_id,
                    "OUTLINE_DRAFTING",
                    error_code,
                    retryable=False,
                    error_details={
                        "project_id": run.input.project_id,
                        "topic": run.input.topic,
                        "selected_file_ids": selected_sources,
                        "retrieval": rag_retrieval,
                    },
                )
                return
            try:
                base_research = await orch._call_outline_with_timeout_retry(
                    run_id=run_id,
                    phase="requirements.analyze",
                    action=lambda: orch.llm_client.generate_research_brief(
                        topic=run.input.topic,
                        project_id=run.input.project_id,
                        rag_source_ids=run.input.rag_source_ids,
                        rag_context_snippets=rag_context_snippets,
                        template_style=requested_template_style,
                        target_slide_count=run.input.target_slide_count,
                    ),
                )
            except Exception:
                base_research = orch._fallback_research_brief(
                    topic=run.input.topic,
                    template_style=requested_template_style,
                    target_slide_count=run.input.target_slide_count,
                )
            design_intent: dict[str, Any] = {}
            try:
                design_intent = await orch._call_outline_with_timeout_retry(
                    run_id=run_id,
                    phase="requirements.design_intent",
                    action=lambda: orch.llm_client.generate_design_intent(
                        topic=run.input.topic,
                        template_style=requested_template_style,
                        target_slide_count=run.input.target_slide_count,
                        research_brief=base_research,
                    ),
                )
            except Exception:
                design_intent = {}
            requirements_report = orch._compose_requirements_report(
                run=run,
                research_brief=base_research,
                design_intent=design_intent,
                rag_context_snippets=rag_context_snippets,
                rag_retrieval=rag_retrieval,
            )
            requirements_report = orch._apply_style_preset_to_requirements(run=run, report=requirements_report)
            effective_template_style = str(requirements_report.get("effective_template_style", "")).strip() or run.input.template_style
            await orch.store.update_run(run_id, lambda r: setattr(r, "research_report", requirements_report))
            design_intent_payload = requirements_report.get("design_intent", {}) if isinstance(requirements_report.get("design_intent", {}), dict) else {}
            requirements_payload = {
                "page_count_fixed": requirements_report.get("page_count_fixed", run.input.target_slide_count),
                "style_preset": requirements_report.get("style_preset", STYLE_PRESET_AUTO),
                "style_reference_name": requirements_report.get("style_reference_name", ""),
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
                "style_dna_id": design_intent_payload.get("style_dna_id", ""),
                "style_signature": design_intent_payload.get("style_signature", ""),
                "layout_family": design_intent_payload.get("layout_family", ""),
                "density_profile": design_intent_payload.get("density_profile", ""),
                "rag_mode": rag_retrieval.get("mode", ""),
                "rag_hit_count": rag_retrieval.get("hit_count", 0),
                "rag_degraded": rag_retrieval.get("degraded", False),
            }
            await orch._publish(run_id, EventType.REQUIREMENTS_ANALYZING_COMPLETED, requirements_payload)
            await orch._publish(run_id, EventType.REQUIREMENTS_ANALYZED, requirements_payload)

            async def on_token(token: str) -> None:
                await orch._publish(run_id, EventType.OUTLINE_TOKEN, {"token": token})
            outline: OutlineDocument | None = None
            repair_attempts = max(1, orch.llm_max_retries)
            previous_response = ""
            error_category = ""
            error_details: list[str] = []

            for attempt in range(1, repair_attempts + 2):
                try:
                    if attempt == 1:
                        outline = await orch._call_outline_with_timeout_retry(
                            run_id=run_id,
                            phase="outline.generate",
                            action=lambda: orch.llm_client.generate_outline(
                                topic=run.input.topic,
                                project_id=run.input.project_id,
                                rag_source_ids=run.input.rag_source_ids,
                                rag_context_snippets=rag_context_snippets,
                                template_style=effective_template_style,
                                target_slide_count=run.input.target_slide_count,
                                on_token=on_token,
                            ),
                        )
                    else:
                        await orch._publish(
                            run_id,
                            EventType.OUTLINE_REPAIR_STARTED,
                            {
                                "attempt": attempt - 1,
                                "phase": "generate",
                                "error_category": error_category,
                                "error_details": error_details,
                            },
                        )
                        outline = await orch._call_outline_with_timeout_retry(
                            run_id=run_id,
                            phase="outline.repair.generate",
                            action=lambda: orch.llm_client.repair_outline(
                                topic=run.input.topic,
                                project_id=run.input.project_id,
                                rag_source_ids=run.input.rag_source_ids,
                                rag_context_snippets=rag_context_snippets,
                                template_style=effective_template_style,
                                target_slide_count=run.input.target_slide_count,
                                previous_response=previous_response,
                                error_category=error_category,
                                error_details=error_details,
                            ),
                        )
                        await orch._publish(
                            run_id,
                            EventType.OUTLINE_REPAIR_COMPLETED,
                            {"attempt": attempt - 1, "phase": "generate"},
                        )
                    break
                except OutlineFormatError as fmt_err:
                    previous_response = fmt_err.raw_response
                    error_category = fmt_err.category
                    error_details = list(fmt_err.details)
                    await orch._publish(
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
                        await orch._fail_run(
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
                await orch._fail_run(
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
                outline = await orch._call_outline_with_timeout_retry(
                    run_id=run_id,
                    phase="outline.critique",
                    action=lambda: orch.llm_client.critique_outline(
                        topic=run.input.topic,
                        template_style=effective_template_style,
                        target_slide_count=run.input.target_slide_count,
                        outline=outline,
                    ),
                )
            except OutlineFormatError as fmt_err:
                await orch._publish(
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
                    await orch._publish(
                        run_id,
                        EventType.OUTLINE_REPAIR_STARTED,
                        {
                            "attempt": 1,
                            "phase": "critique",
                            "error_category": fmt_err.category,
                            "error_details": list(fmt_err.details),
                        },
                    )
                    outline = await orch._call_outline_with_timeout_retry(
                        run_id=run_id,
                        phase="outline.repair.critique",
                        action=lambda: orch.llm_client.repair_outline(
                            topic=run.input.topic,
                            project_id=run.input.project_id,
                            rag_source_ids=run.input.rag_source_ids,
                            rag_context_snippets=rag_context_snippets,
                            template_style=effective_template_style,
                            target_slide_count=run.input.target_slide_count,
                            previous_response=fmt_err.raw_response,
                            error_category=f"critique_{fmt_err.category}",
                            error_details=list(fmt_err.details),
                        ),
                    )
                    await orch._publish(
                        run_id,
                        EventType.OUTLINE_REPAIR_COMPLETED,
                        {"attempt": 1, "phase": "critique"},
                    )
                except OutlineFormatError:
                    outline = base_outline
                    await orch._publish(
                        run_id,
                        EventType.OUTLINE_REPAIR_COMPLETED,
                        {"attempt": 1, "phase": "critique", "fallback_used": True},
                    )
            style_dna_id = ""
            if isinstance(requirements_report.get("design_intent", {}), dict):
                style_dna_id = str(requirements_report.get("design_intent", {}).get("style_dna_id", "")).strip()
            enforce_layout_variety(
                nodes=outline.nodes,
                seed=f"{run.input.topic}|{effective_template_style}|{run_id}",
                style_dna_id=style_dna_id or None,
            )
            design = orch._resolve_design_profile(topic=run.input.topic, template_style=effective_template_style, requirements_report=requirements_report)

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

            await orch.store.update_run(run_id, apply_outline)
            await orch._publish(run_id, EventType.OUTLINE_COMPLETED, {"version": outline.version, "sections": len(outline.nodes)})
            await orch._publish(
                run_id,
                EventType.RESEARCH_COMPLETED,
                {
                    "audience": requirements_report.get("audience", ""),
                    "purpose": requirements_report.get("purpose", ""),
                    "tone": requirements_report.get("tone", ""),
                    "rag_hit_count": rag_retrieval.get("hit_count", 0),
                    "rag_mode": rag_retrieval.get("mode", ""),
                },
            )
            await orch._publish(
                run_id,
                EventType.PLAN_COMPLETED,
                {
                    "sections": len(outline.nodes),
                    "palette": design.palette_name,
                    "style": design.style.name,
                    "style_dna_id": style_dna_id,
                    "fonts": {"title": design.title_font, "body": design.body_font},
                    "theme": design.theme,
                },
            )
        except LLMTimeoutError as exc:
            await orch._fail_run(
                run_id,
                "OUTLINE_DRAFTING",
                "OUTLINE_LLM_TIMEOUT",
                retryable=True,
                error_details={
                    "phase": exc.phase,
                    "attempts": exc.attempts,
                    "reason": orch._exception_reason(exc),
                    "error_type": type(exc).__name__,
                    "provider_mode": orch.settings.llm_api_style,
                },
            )
        except Exception as exc:
            reason = str(exc).strip() or repr(exc)
            await orch._fail_run(
                run_id,
                "OUTLINE_DRAFTING",
                "OUTLINE_LLM_ERROR",
                retryable=True,
                error_details={
                    "reason": reason,
                    "error_type": type(exc).__name__,
                    "provider_mode": orch.settings.llm_api_style,
                    "traceback": traceback.format_exc(limit=4),
                },
            )

