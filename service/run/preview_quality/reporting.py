from __future__ import annotations

from typing import Any, Callable


def resolve_qa_history(
    *, previous_report: dict[str, Any]
) -> tuple[int, dict[str, Any]]:
    verification_cycles = int(previous_report.get("verification_cycles", 0))
    preview_cache_in = (
        previous_report.get("preview_cache", {})
        if isinstance(previous_report.get("preview_cache", {}), dict)
        else {}
    )
    return verification_cycles, preview_cache_in


def build_preview_cache_entry(
    *,
    checksum: str,
    issues: list[str],
    checked: bool,
    sampled: bool = False,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "hash": checksum,
        "issues": list(issues),
        "checked": checked,
    }
    if sampled:
        entry["sampled"] = True
    return entry


def merge_sampled_preview_cache_entry(
    *,
    checksum: str,
    cached_issues: list[str],
    sample_issues: list[str],
) -> dict[str, Any]:
    return build_preview_cache_entry(
        checksum=checksum,
        issues=list(cached_issues) + list(sample_issues),
        checked=True,
        sampled=True,
    )


def build_qa_report(
    *,
    deduped_issues: list[str],
    verification_cycles: int,
    preview_cache_out: dict[str, Any],
    split_qa_issues_by_slide: Callable[
        [list[str]], tuple[dict[int, list[str]], list[str]]
    ],
) -> dict[str, Any]:
    issues_by_slide, global_issues = split_qa_issues_by_slide(deduped_issues)
    return {
        "passed": not deduped_issues,
        "issues": list(deduped_issues),
        "issues_by_slide": {
            str(k): v for k, v in sorted(issues_by_slide.items(), key=lambda x: x[0])
        },
        "global_issues": global_issues,
        "verification_cycles": verification_cycles,
        "preview_cache": preview_cache_out,
    }
