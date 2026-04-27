from __future__ import annotations

from service.run.slide_candidate_reporting import (
    build_candidate_generated_payload,
    build_candidate_selection_entry,
    build_failure_diagnostics_payload,
    build_gate_counts,
    build_quality_entry,
    build_quality_gate_completed_payload,
    build_quality_gate_entry,
    build_selection_completed_payload,
)


def test_build_gate_counts_should_stay_deterministic() -> None:
    counts = build_gate_counts(
        blocking=["a", "b"],
        high_risk=["c"],
        warnings=["d", "e", "f"],
    )
    assert counts == {"blocking": 2, "high_risk": 1, "warnings": 3}


def test_candidate_payload_builders_should_use_generic_gate_shape() -> None:
    variant = {"mode": "scratch_llm_js", "round": 2}
    generated = build_candidate_generated_payload(
        slide_no=3,
        repair_round=2,
        quality_score=76,
        passed=False,
        blocking=["preview compile failed"],
        high_risk=["title font too small"],
        warnings=["minor note"],
        variant=variant,
        preview_mode="full",
        error="bad compile",
        phase="candidate.preview",
    )
    assert generated["candidate"] == 1
    assert generated["hard_issue_count"] == 2
    assert generated["preview_mode"] == "full"
    assert generated["error"] == "bad compile"
    assert generated["gate"] == {"blocking": 1, "high_risk": 1, "warnings": 1}

    selection_entry = build_candidate_selection_entry(
        slide_no=3,
        repair_round=2,
        quality_score=76,
        passed=True,
        degraded=True,
        blocking=[],
        high_risk=["title font too small"],
        variant=variant,
        preview_mode="full",
    )
    assert selection_entry["selected_degraded"] is True
    assert selection_entry["candidates"][0]["preview_mode"] == "full"

    completed = build_selection_completed_payload(
        slide_no=3,
        repair_round=2,
        quality_score=76,
        passed=True,
        degraded=True,
        variant=variant,
    )
    assert completed["selected_candidate"] == 1
    assert completed["degraded"] is True


def test_quality_payload_builders_should_keep_hard_only_gate_contract() -> None:
    entry = build_quality_gate_entry(
        slide_no=4,
        repair_round=3,
        visual_policy="auto",
        quality_score=88,
        blocking=["preview compile failed"],
        high_risk=["title font too small"],
        warnings=["minor note"],
        repair_directives=["fix preview", "increase title size"],
        passed=False,
    )
    assert entry["gate_mode"] == "hard_only_v2"
    assert entry["threshold"] == 0
    assert entry["hard_issues"] == ["preview compile failed", "title font too small"]
    assert entry["repair_directives"] == ["fix preview", "increase title size"]

    completed = build_quality_gate_completed_payload(
        slide_no=4,
        repair_round=3,
        quality_score=88,
        passed=False,
        blocking=["preview compile failed"],
        high_risk=["title font too small"],
        warnings=["minor note"],
    )
    assert completed["hard_issue_count"] == 2
    assert completed["gate"] == {"blocking": 1, "high_risk": 1, "warnings": 1}

    quality_entry = build_quality_entry(
        slide_no=4,
        round_passed=3,
        last_major_issues=["preview compile failed"],
        last_warnings=["title font too small"],
        engine="agentic_v2",
        quality_score=88,
        visual_policy="auto",
        selected_variant={"mode": "scratch_llm_js"},
        degraded_accept=True,
        preview_text="hello" * 100,
        repair_directives=["fix preview", "increase title size"] * 8,
    )
    assert quality_entry["preview_text_excerpt"] == ("hello" * 100)[:300]
    assert len(quality_entry["repair_directives"]) == 8
    assert quality_entry["degraded_accept"] is True


def test_failure_diagnostics_payload_should_project_context_fields() -> None:
    payload = build_failure_diagnostics_payload(
        slide_no=2,
        repair_round=1,
        phase="candidate.preview",
        context={
            "error_class": "TypeError",
            "stderr_excerpt": "bad call",
            "error_location": {"line": 12},
        },
        repair_directives=["use legal API only", "keep w/h > 0"],
    )
    assert payload["candidate"] == 1
    assert payload["error_type"] == "TypeError"
    assert payload["stderr_excerpt"] == "bad call"
    assert payload["error_location"] == {"line": 12}
    assert payload["repair_hint"] == ["use legal API only", "keep w/h > 0"]
