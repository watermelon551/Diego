from __future__ import annotations

from pathlib import Path

from service.models import VisualPolicy
from service.run.slide_candidate_review import review_agentic_candidate_quality


def test_review_agentic_candidate_quality_should_skip_preview_on_fatal_contract() -> None:
    preview_called = {"value": False}

    async def run_preview(**_kwargs):
        preview_called["value"] = True
        return [], "", {}

    def validate(js_code: str, **_kwargs):
        assert js_code == "candidate-js"
        return ["missing export contract"]

    def build_failure_context(**kwargs):
        return {"phase": kwargs["phase"], "issues": kwargs["issues"]}

    import asyncio

    result = asyncio.run(
        review_agentic_candidate_quality(
            run_id="run-1",
            slide_no=1,
            repair_round=1,
            candidate_path=Path("/tmp/slide-01.js"),
            js_code="candidate-js",
            page_type="content",
            visual_policy=VisualPolicy.AUTO,
            slide_plan={},
            compile_failure_markers=("missing export contract",),
            validate_slide_js_contract=validate,
            run_slide_preview_qa_with_text=run_preview,
            dedupe_preserve_order=lambda items: list(dict.fromkeys(items)),
            classify_slide_issues=lambda issues: {
                "blocking": list(issues),
                "high_risk": [],
                "warnings": [],
            },
            local_quality_score=lambda *, classified: 76,
            build_local_repair_directives=lambda *, classified: ["fix contract"],
            build_slide_failure_context=build_failure_context,
        )
    )
    assert preview_called["value"] is False
    assert result.preview_mode == "skip_contract_failure"
    assert result.preview_issues == ["preview skipped due to fatal contract issue"]
    assert result.needs_repair is True
    assert result.failure_phase == "candidate.contract"
    assert result.failure_context == {
        "phase": "candidate.contract",
        "issues": [
            "missing export contract",
            "preview skipped due to fatal contract issue",
        ],
    }


def test_review_agentic_candidate_quality_should_capture_preview_failure_context() -> None:
    async def run_preview(**_kwargs):
        return ["preview compile failed: bad call"], "preview text", {"stderr": "boom"}

    def build_failure_context(**kwargs):
        return {
            "phase": kwargs["phase"],
            "diagnostics": kwargs["diagnostics"],
            "issues": kwargs["issues"],
        }

    import asyncio

    result = asyncio.run(
        review_agentic_candidate_quality(
            run_id="run-2",
            slide_no=2,
            repair_round=3,
            candidate_path=Path("/tmp/slide-02.js"),
            js_code="candidate-js",
            page_type="content",
            visual_policy=VisualPolicy.AUTO,
            slide_plan={},
            compile_failure_markers=("preview compile failed",),
            validate_slide_js_contract=lambda _js_code, **_kwargs: [],
            run_slide_preview_qa_with_text=run_preview,
            dedupe_preserve_order=lambda items: list(dict.fromkeys(items)),
            classify_slide_issues=lambda issues: {
                "blocking": list(issues),
                "high_risk": ["title font too small"],
                "warnings": ["minor note"],
            },
            local_quality_score=lambda *, classified: 54,
            build_local_repair_directives=lambda *, classified: ["fix preview"],
            build_slide_failure_context=build_failure_context,
        )
    )
    assert result.preview_mode == "full"
    assert result.preview_text == "preview text"
    assert result.compile_ok is False
    assert result.needs_repair is True
    assert result.failure_phase == "candidate.preview"
    assert result.failure_context["diagnostics"]["preview_mode"] == "full"
    assert result.failure_context["diagnostics"]["attempt"] == 3
    assert result.failure_context["diagnostics"]["gate_summary"] == {
        "blocking": 1,
        "high_risk": 1,
        "warnings": 1,
    }
