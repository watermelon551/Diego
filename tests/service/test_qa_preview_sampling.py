from __future__ import annotations

from pathlib import Path

from service.run.qa_preview_sampling import (
    PreviewCandidateRef,
    decide_preview_check,
    should_sample_unchanged_preview,
)


def test_decide_preview_check_should_skip_when_static_issues_exist() -> None:
    decision = decide_preview_check(
        verification_cycles=1,
        has_static_issues=True,
        slide_path=Path("slide-01.js"),
        slide_no=1,
        checksum="abc",
        unchanged_preview=True,
        cached_preview_issues=["cached"],
    )
    assert decision.should_preview is False
    assert decision.preview_issues == []
    assert decision.queued_candidate is None


def test_decide_preview_check_should_preview_on_first_cycle_or_changed_hash() -> None:
    first_cycle = decide_preview_check(
        verification_cycles=0,
        has_static_issues=False,
        slide_path=Path("slide-01.js"),
        slide_no=1,
        checksum="abc",
        unchanged_preview=True,
        cached_preview_issues=["cached"],
    )
    assert first_cycle.should_preview is True
    assert first_cycle.preview_issues == []

    changed = decide_preview_check(
        verification_cycles=2,
        has_static_issues=False,
        slide_path=Path("slide-02.js"),
        slide_no=2,
        checksum="def",
        unchanged_preview=False,
        cached_preview_issues=["cached"],
    )
    assert changed.should_preview is True
    assert changed.queued_candidate is None


def test_decide_preview_check_should_queue_unchanged_candidate_with_cached_issues() -> None:
    decision = decide_preview_check(
        verification_cycles=2,
        has_static_issues=False,
        slide_path=Path("slide-03.js"),
        slide_no=3,
        checksum="ghi",
        unchanged_preview=True,
        cached_preview_issues=["cached-a", "cached-b"],
    )
    assert decision.should_preview is False
    assert decision.preview_issues == ["cached-a", "cached-b"]
    assert decision.queued_candidate == PreviewCandidateRef(
        path=Path("slide-03.js"),
        slide_no=3,
        checksum="ghi",
    )


def test_should_sample_unchanged_preview_should_require_no_preview_runs_and_candidates() -> None:
    assert should_sample_unchanged_preview(
        verification_cycles=1,
        preview_runs=0,
        unchanged_preview_candidates=[PreviewCandidateRef(Path("a"), 1, "x")],
    )
    assert not should_sample_unchanged_preview(
        verification_cycles=0,
        preview_runs=0,
        unchanged_preview_candidates=[PreviewCandidateRef(Path("a"), 1, "x")],
    )
    assert not should_sample_unchanged_preview(
        verification_cycles=1,
        preview_runs=1,
        unchanged_preview_candidates=[PreviewCandidateRef(Path("a"), 1, "x")],
    )
    assert not should_sample_unchanged_preview(
        verification_cycles=1,
        preview_runs=0,
        unchanged_preview_candidates=[],
    )
