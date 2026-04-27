from __future__ import annotations

from service.run.qa_reporting import (
    build_preview_cache_entry,
    build_qa_report,
    merge_sampled_preview_cache_entry,
    resolve_qa_history,
)


def test_resolve_qa_history_should_extract_cycles_and_preview_cache() -> None:
    cycles, cache = resolve_qa_history(
        previous_report={
            "verification_cycles": 2,
            "preview_cache": {"slide-01.js": {"hash": "abc"}},
        }
    )
    assert cycles == 2
    assert cache == {"slide-01.js": {"hash": "abc"}}

    cycles, cache = resolve_qa_history(previous_report={"preview_cache": []})
    assert cycles == 0
    assert cache == {}


def test_preview_cache_entry_helpers_should_stay_deterministic() -> None:
    entry = build_preview_cache_entry(
        checksum="abc123",
        issues=["issue-a"],
        checked=False,
    )
    assert entry == {
        "hash": "abc123",
        "issues": ["issue-a"],
        "checked": False,
    }

    sampled = merge_sampled_preview_cache_entry(
        checksum="abc123",
        cached_issues=["old"],
        sample_issues=["new"],
    )
    assert sampled == {
        "hash": "abc123",
        "issues": ["old", "new"],
        "checked": True,
        "sampled": True,
    }


def test_build_qa_report_should_project_slide_and_global_issues() -> None:
    report = build_qa_report(
        deduped_issues=[
            "slide-02.js: missing required page badge position",
            "markitdown qa failed",
        ],
        verification_cycles=1,
        preview_cache_out={"slide-02.js": {"hash": "h1"}},
        split_qa_issues_by_slide=lambda issues: (
            {2: ["missing required page badge position"]},
            ["markitdown qa failed"],
        ),
    )
    assert report["passed"] is False
    assert report["issues"] == [
        "slide-02.js: missing required page badge position",
        "markitdown qa failed",
    ]
    assert report["issues_by_slide"] == {"2": ["missing required page badge position"]}
    assert report["global_issues"] == ["markitdown qa failed"]
    assert report["verification_cycles"] == 1
    assert report["preview_cache"] == {"slide-02.js": {"hash": "h1"}}
