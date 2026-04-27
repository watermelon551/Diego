from __future__ import annotations

from typing import Any

from ..design.style_catalog import STYLE_PRESET_AUTO


def build_outline_rag_degraded_payload(
    *,
    target_slide_count: int,
    top_k: int,
    enabled: bool,
    error_code: str,
    status_code: int | None,
    retryable: bool,
    reason: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "mode": "project_all",
        "selected_file_count": 0,
        "top_k": top_k,
        "enabled": enabled,
        "hit_count": 0,
        "degraded": True,
        "degrade_reason": "retrieval_error",
        "error_code": error_code,
        "status_code": status_code,
        "retryable": retryable,
        "reason": reason,
        "details": details,
    }


def build_requirements_analyzed_payload(
    *,
    requirements_report: dict[str, Any],
    target_slide_count: int,
    rag_retrieval: dict[str, Any],
) -> dict[str, Any]:
    design_intent_payload = (
        requirements_report.get("design_intent", {})
        if isinstance(requirements_report.get("design_intent", {}), dict)
        else {}
    )
    return {
        "page_count_fixed": requirements_report.get("page_count_fixed", target_slide_count),
        "style_preset": requirements_report.get("style_preset", STYLE_PRESET_AUTO),
        "style_reference_name": requirements_report.get("style_reference_name", ""),
        "effective_template_style": requirements_report.get("effective_template_style", ""),
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


def build_outline_repair_started_payload(
    *,
    attempt: int,
    phase: str,
    error_category: str,
    error_details: list[str],
) -> dict[str, Any]:
    return {
        "attempt": attempt,
        "phase": phase,
        "error_category": error_category,
        "error_details": list(error_details),
    }


def build_outline_repair_failed_payload(
    *,
    attempt: int,
    phase: str,
    error_category: str,
    error_details: list[str],
) -> dict[str, Any]:
    return build_outline_repair_started_payload(
        attempt=attempt,
        phase=phase,
        error_category=error_category,
        error_details=error_details,
    )


def build_outline_repair_completed_payload(
    *,
    attempt: int,
    phase: str,
    fallback_used: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "attempt": attempt,
        "phase": phase,
    }
    if fallback_used:
        payload["fallback_used"] = True
    return payload


def build_research_completed_payload(
    *,
    requirements_report: dict[str, Any],
    rag_retrieval: dict[str, Any],
) -> dict[str, Any]:
    return {
        "audience": requirements_report.get("audience", ""),
        "purpose": requirements_report.get("purpose", ""),
        "tone": requirements_report.get("tone", ""),
        "rag_hit_count": rag_retrieval.get("hit_count", 0),
        "rag_mode": rag_retrieval.get("mode", ""),
    }


def build_plan_completed_payload(
    *,
    section_count: int,
    palette_name: str,
    style_name: str,
    style_dna_id: str,
    title_font: str,
    body_font: str,
    theme: dict[str, Any],
) -> dict[str, Any]:
    return {
        "sections": section_count,
        "palette": palette_name,
        "style": style_name,
        "style_dna_id": style_dna_id,
        "fonts": {"title": title_font, "body": body_font},
        "theme": theme,
    }
