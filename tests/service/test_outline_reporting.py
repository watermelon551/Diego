from __future__ import annotations

from service.run.outline_reporting import (
    build_outline_rag_degraded_payload,
    build_outline_repair_completed_payload,
    build_outline_repair_failed_payload,
    build_outline_repair_started_payload,
    build_plan_completed_payload,
    build_research_completed_payload,
    build_requirements_analyzed_payload,
)


def test_outline_reporting_payloads_should_stay_deterministic() -> None:
    requirements_report = {
        "page_count_fixed": 4,
        "style_preset": "executive",
        "style_reference_name": "clean",
        "effective_template_style": "clean",
        "style_intent": "clear",
        "content_source_mode": "rag_first",
        "image_source_mode": "mixed",
        "audience": "leaders",
        "purpose": "decision",
        "tone": "concise",
        "design_intent": {
            "palette_name": "teal",
            "style_recipe": "grid",
            "visual_strategy": "diagram_first",
            "density": "medium",
            "style_dna_id": "dna-1",
            "style_signature": "sig-1",
            "layout_family": "editorial",
            "density_profile": "balanced",
        },
    }
    rag_retrieval = {"mode": "selected_files", "hit_count": 2, "degraded": False}

    assert build_requirements_analyzed_payload(
        requirements_report=requirements_report,
        target_slide_count=5,
        rag_retrieval=rag_retrieval,
    ) == {
        "page_count_fixed": 4,
        "style_preset": "executive",
        "style_reference_name": "clean",
        "effective_template_style": "clean",
        "style_intent": "clear",
        "content_source_mode": "rag_first",
        "image_source_mode": "mixed",
        "audience": "leaders",
        "purpose": "decision",
        "tone": "concise",
        "palette_name": "teal",
        "style_recipe": "grid",
        "visual_strategy": "diagram_first",
        "density": "medium",
        "style_dna_id": "dna-1",
        "style_signature": "sig-1",
        "layout_family": "editorial",
        "density_profile": "balanced",
        "rag_mode": "selected_files",
        "rag_hit_count": 2,
        "rag_degraded": False,
    }
    assert build_outline_repair_started_payload(
        attempt=2,
        phase="generate",
        error_category="format",
        error_details=["missing nodes"],
    ) == {
        "attempt": 2,
        "phase": "generate",
        "error_category": "format",
        "error_details": ["missing nodes"],
    }
    assert build_outline_repair_failed_payload(
        attempt=1,
        phase="critique",
        error_category="schema",
        error_details=["missing bullets"],
    ) == {
        "attempt": 1,
        "phase": "critique",
        "error_category": "schema",
        "error_details": ["missing bullets"],
    }
    assert build_outline_repair_completed_payload(
        attempt=1,
        phase="critique",
        fallback_used=True,
    ) == {
        "attempt": 1,
        "phase": "critique",
        "fallback_used": True,
    }


def test_outline_reporting_rag_and_completion_payloads_should_remain_generic() -> None:
    assert build_outline_rag_degraded_payload(
        target_slide_count=4,
        top_k=6,
        enabled=False,
        error_code="STRATUMIND_REQUEST_ERROR",
        status_code=503,
        retryable=True,
        reason="failed",
        details={"reason": "network"},
    ) == {
        "mode": "project_all",
        "selected_file_count": 0,
        "top_k": 6,
        "enabled": False,
        "hit_count": 0,
        "degraded": True,
        "degrade_reason": "retrieval_error",
        "error_code": "STRATUMIND_REQUEST_ERROR",
        "status_code": 503,
        "retryable": True,
        "reason": "failed",
        "details": {"reason": "network"},
    }
    assert build_research_completed_payload(
        requirements_report={"audience": "ops", "purpose": "teach", "tone": "plain"},
        rag_retrieval={"hit_count": 3, "mode": "project_all"},
    ) == {
        "audience": "ops",
        "purpose": "teach",
        "tone": "plain",
        "rag_hit_count": 3,
        "rag_mode": "project_all",
    }
    assert build_plan_completed_payload(
        section_count=5,
        palette_name="teal",
        style_name="editorial",
        style_dna_id="dna-2",
        title_font="A",
        body_font="B",
        theme={"bg": "#fff"},
    ) == {
        "sections": 5,
        "palette": "teal",
        "style": "editorial",
        "style_dna_id": "dna-2",
        "fonts": {"title": "A", "body": "B"},
        "theme": {"bg": "#fff"},
    }
