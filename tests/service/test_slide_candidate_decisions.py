from __future__ import annotations

from service.run.slide_candidate_decisions import (
    build_rounds_exhausted_reason,
    has_visual_policy_blocker,
    is_missing_output,
    resolve_round_limits,
    should_accept_candidate_result,
    should_accept_degraded_after_build_failure,
    should_accept_degraded_after_quality_gate,
    should_raise_rounds_exhausted,
    should_raise_visual_policy_unsatisfied,
)


def test_resolve_round_limits_should_keep_soft_plus_two_rule() -> None:
    assert resolve_round_limits(max_slide_repair_rounds=0) == (1, 3)
    assert resolve_round_limits(max_slide_repair_rounds=2) == (2, 4)


def test_build_failure_and_quality_acceptance_should_follow_round_policy() -> None:
    assert should_accept_degraded_after_build_failure(
        repair_round=2,
        soft_round_limit=2,
        has_best_js=True,
        best_compile_ok=True,
    )
    assert not should_accept_degraded_after_build_failure(
        repair_round=1,
        soft_round_limit=2,
        has_best_js=True,
        best_compile_ok=True,
    )
    assert should_accept_degraded_after_quality_gate(
        repair_round=2,
        soft_round_limit=2,
        best_compile_ok=True,
    )
    assert not should_accept_degraded_after_quality_gate(
        repair_round=2,
        soft_round_limit=2,
        best_compile_ok=False,
    )


def test_candidate_acceptance_should_distinguish_clean_vs_degraded_success() -> None:
    assert should_accept_candidate_result(
        needs_repair=True,
        degraded_notes=[],
    ) == (False, False)
    assert should_accept_candidate_result(
        needs_repair=False,
        degraded_notes=[],
    ) == (True, False)
    assert should_accept_candidate_result(
        needs_repair=False,
        degraded_notes=["title font too small"],
    ) == (True, True)


def test_visual_policy_and_exhaustion_checks_should_stay_explicit() -> None:
    issues = ["visual_policy violation: media_required needs addImage()"]
    assert has_visual_policy_blocker(issues)
    assert should_raise_visual_policy_unsatisfied(
        repair_round=2,
        soft_round_limit=2,
        issues=issues,
    )
    assert not should_raise_visual_policy_unsatisfied(
        repair_round=1,
        soft_round_limit=2,
        issues=issues,
    )
    assert should_raise_rounds_exhausted(repair_round=4, hard_round_limit=4)
    assert not should_raise_rounds_exhausted(repair_round=3, hard_round_limit=4)


def test_missing_output_and_reason_helpers_should_stay_deterministic() -> None:
    assert is_missing_output(round_passed=0, output_exists=True)
    assert is_missing_output(round_passed=2, output_exists=False)
    assert not is_missing_output(round_passed=2, output_exists=True)
    assert (
        build_rounds_exhausted_reason(
            soft_round_limit=2,
            hard_round_limit=4,
        )
        == "failed after 4 rounds (base=2, extra=2)"
    )
