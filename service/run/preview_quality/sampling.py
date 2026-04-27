from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PreviewCandidateRef:
    path: Path
    slide_no: int
    checksum: str


@dataclass(frozen=True)
class PreviewDecision:
    should_preview: bool
    preview_issues: list[str]
    queued_candidate: PreviewCandidateRef | None = None


def decide_preview_check(
    *,
    verification_cycles: int,
    has_static_issues: bool,
    slide_path: Path,
    slide_no: int,
    checksum: str,
    unchanged_preview: bool,
    cached_preview_issues: list[str],
) -> PreviewDecision:
    if has_static_issues:
        return PreviewDecision(
            should_preview=False,
            preview_issues=[],
            queued_candidate=None,
        )
    should_preview = verification_cycles == 0 or not unchanged_preview
    if should_preview:
        return PreviewDecision(
            should_preview=True,
            preview_issues=[],
            queued_candidate=None,
        )
    return PreviewDecision(
        should_preview=False,
        preview_issues=list(cached_preview_issues),
        queued_candidate=PreviewCandidateRef(
            path=slide_path,
            slide_no=slide_no,
            checksum=checksum,
        ),
    )


def should_sample_unchanged_preview(
    *,
    verification_cycles: int,
    preview_runs: int,
    unchanged_preview_candidates: list[PreviewCandidateRef],
) -> bool:
    return (
        verification_cycles > 0
        and preview_runs == 0
        and bool(unchanged_preview_candidates)
    )
