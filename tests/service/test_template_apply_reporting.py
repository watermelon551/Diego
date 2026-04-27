from __future__ import annotations

from service.run.template_apply_reporting import (
    build_chart_truth_checked_payload,
    build_slot_mapping_completed_payload,
    build_slot_mapping_entry,
    build_template_chart_report,
    build_template_fidelity_payload,
    build_template_layout_completed_payload,
    build_template_layout_report,
    build_template_mapping_report,
)


def test_template_apply_reporting_builders_should_stay_deterministic() -> None:
    slots = [
        {"slot_type": "title", "required": True, "mapped": True},
        {"slot_type": "unknown", "required": True, "mapped": False},
    ]
    mapping_entry = build_slot_mapping_entry(slide_no=2, slots=slots)
    assert build_template_mapping_report() == {
        "mode": "template",
        "slides": [],
        "unmapped_required": [],
        "passed": True,
    }
    assert build_template_chart_report() == {
        "slides": [],
        "passed": True,
    }
    assert build_template_layout_report() == {
        "slides": [],
        "passed": True,
    }
    assert mapping_entry == {
        "slide_no": 2,
        "slot_count": 2,
        "mapped_count": 1,
        "missing_required": [{"slot_type": "unknown", "required": True, "mapped": False}],
        "slots": slots,
    }
    assert build_slot_mapping_completed_payload(mapping_entry) == {
        "slide_no": 2,
        "mapped_count": 1,
        "slot_count": 2,
        "missing_required": [{"slot_type": "unknown", "required": True, "mapped": False}],
    }


def test_template_apply_reporting_event_payloads_should_normalize_counts() -> None:
    layout_entry = {
        "slide_no": 3,
        "box_count": "4",
        "moved_count": 2,
        "issues_before_count": "1",
        "issues_after_count": 0,
        "fidelity_score": "87",
        "passed": 1,
    }
    assert build_template_layout_completed_payload(layout_entry) == {
        "slide_no": 3,
        "box_count": 4,
        "moved_count": 2,
        "issues_before_count": 1,
        "issues_after_count": 0,
        "passed": True,
    }
    assert build_template_fidelity_payload(layout_entry) == {
        "slide_no": 3,
        "fidelity_score": 87,
        "passed": True,
    }
    assert build_chart_truth_checked_payload(
        slide_no=3,
        chart_entry={"has_verified_data": True, "mode": "grounded", "source": "rag"},
    ) == {
        "slide_no": 3,
        "has_verified_data": True,
        "mode": "grounded",
        "source": "rag",
    }
