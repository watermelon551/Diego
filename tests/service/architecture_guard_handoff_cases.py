from __future__ import annotations

from tests.service.architecture_guard_support import ROOT


def test_minimal_consumer_shape_note_should_keep_consumer_pressure_lightweight() -> None:
    path = ROOT / "docs" / "MINIMAL_CONSUMER_SHAPE_NOTE.md"
    text = path.read_text(encoding="utf-8").lower()
    assert "generic consumer" in text
    assert "explicit failure information" in text
    assert "shell routing or controller glue" in text
    forbidden = [
        "integration test harness",
        "fake shell",
        "workbench implementation",
        "teaching_document",
        "knowledge_mindmap",
        "interactive_quick_quiz",
        "interactive_games",
        "demonstration_animations",
        "speaker_notes",
    ]
    for term in forbidden:
        assert term not in text, f"MINIMAL_CONSUMER_SHAPE_NOTE.md should not contain {term!r}"


def test_handoff_notes_should_keep_generic_handoff_boundary() -> None:
    note_paths = [
        ROOT / "docs" / "PILOT_PRESSURE_SUMMARY_NOTE.md",
        ROOT / "docs" / "HANDOFF_SHAPE_EVALUATION_NOTE.md",
        ROOT / "docs" / "CONSUMER_BOUNDARY_TABLE.md",
        ROOT / "docs" / "CROSS_CONSUMER_PRIMITIVE_ASSESSMENT.md",
        ROOT / "docs" / "HANDOFF_BACKLOG_NOTE.md",
    ]
    forbidden = [
        "teaching_document",
        "knowledge_mindmap",
        "interactive_quick_quiz",
        "interactive_games",
        "demonstration_animations",
        "speaker_notes",
        "markdown as primary truth in diego",
        "compile ownership in diego",
    ]
    required_markers = [
        "consumer-side",
        "content_blocks_v1",
        "compile/export",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in note_paths)
    for term in forbidden:
        assert term not in combined, f"handoff notes should not contain {term!r}"
    for marker in required_markers:
        assert marker in combined, f"handoff notes missing {marker!r}"


def test_owner_track_notes_should_keep_owner_purity_and_canon_caution() -> None:
    note_paths = [
        ROOT / "docs" / "OWNER_REALITY_CLASSIFICATION_NOTE.md",
        ROOT / "docs" / "NEXT_PRIMITIVE_SURFACE_NOTE.md",
        ROOT / "docs" / "OWNER_ACCEPTANCE_NOTE.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in note_paths)
    forbidden = [
        "teaching_document",
        "knowledge_mindmap",
        "interactive_quick_quiz",
        "interactive_games",
        "demonstration_animations",
        "speaker_notes",
        "fake artifact",
    ]
    required_markers = [
        "generation result",
        "structured draft output",
        "provisional but valid",
        "thin shell consumption",
        "compile/export",
    ]
    for term in forbidden:
        assert term not in combined, f"owner track notes should not contain {term!r}"
    for marker in required_markers:
        assert marker in combined, f"owner track notes missing {marker!r}"
