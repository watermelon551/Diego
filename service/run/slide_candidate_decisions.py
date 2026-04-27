from __future__ import annotations


def resolve_round_limits(*, max_slide_repair_rounds: int) -> tuple[int, int]:
    soft_round_limit = max(1, int(max_slide_repair_rounds))
    hard_round_limit = soft_round_limit + 2
    return soft_round_limit, hard_round_limit


def should_accept_degraded_after_build_failure(
    *,
    repair_round: int,
    soft_round_limit: int,
    has_best_js: bool,
    best_compile_ok: bool,
) -> bool:
    return (
        repair_round >= soft_round_limit
        and has_best_js
        and best_compile_ok
    )


def should_accept_candidate_result(
    *,
    needs_repair: bool,
    degraded_notes: list[str],
) -> tuple[bool, bool]:
    if needs_repair:
        return False, False
    return True, bool(degraded_notes)


def has_visual_policy_blocker(issues: list[str]) -> bool:
    return any("visual_policy violation" in str(item).lower() for item in issues)


def should_raise_visual_policy_unsatisfied(
    *,
    repair_round: int,
    soft_round_limit: int,
    issues: list[str],
) -> bool:
    return repair_round >= soft_round_limit and has_visual_policy_blocker(issues)


def should_accept_degraded_after_quality_gate(
    *,
    repair_round: int,
    soft_round_limit: int,
    best_compile_ok: bool,
) -> bool:
    return repair_round >= soft_round_limit and best_compile_ok


def should_raise_rounds_exhausted(*, repair_round: int, hard_round_limit: int) -> bool:
    return repair_round >= hard_round_limit


def is_missing_output(*, round_passed: int, output_exists: bool) -> bool:
    return round_passed == 0 or not output_exists


def build_rounds_exhausted_reason(
    *,
    soft_round_limit: int,
    hard_round_limit: int,
) -> str:
    return (
        f"failed after {hard_round_limit} rounds "
        f"(base={soft_round_limit}, extra=2)"
    )
