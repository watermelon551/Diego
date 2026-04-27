from __future__ import annotations

from tests.service.architecture_guard_support import ROOT


def test_structured_content_notes_should_keep_new_primitives_provisional() -> None:
    note_paths = [
        ROOT / "docs" / "STRUCTURED_CONTENT_PRIMITIVE_TAXONOMY.md",
        ROOT / "docs" / "GENERIC_PRIMITIVE_BACKLOG_NOTE.md",
        ROOT / "docs" / "PRIMITIVE_CANONIZATION_NOTE.md",
        ROOT / "docs" / "OWNER_ACCEPTANCE_NOTE.md",
    ]
    for path in note_paths:
        text = path.read_text(encoding="utf-8").lower()
        assert "structure_expansion" in text
        assert "item_generation" in text
        assert "provisional" in text


def test_structured_generation_status_note_should_keep_status_map_explicit() -> None:
    path = ROOT / "docs" / "STRUCTURED_GENERATION_PRIMITIVE_STATUS_NOTE.md"
    text = path.read_text(encoding="utf-8").lower()
    required = [
        "canonical now",
        "provisional but valid",
        "active pressure",
        "later backlog",
        "do not own",
        "content_blocks_v1",
        "draft_package",
        "structure_expansion",
        "item_generation",
        "sequence_or_script_plan",
        "interaction_schema",
        "algorithm_trace",
        "process_trace",
    ]
    forbidden = [
        "teaching_document",
        "knowledge_mindmap",
        "interactive_quick_quiz",
        "demonstration_animations",
        "interactive_games",
        "speaker_notes",
    ]
    for marker in required:
        assert marker in text, f"status note missing {marker!r}"
    for term in forbidden:
        assert term not in text, f"status note should not contain {term!r}"


def test_primitive_canonization_note_should_be_unambiguous_and_generic() -> None:
    path = ROOT / "docs" / "PRIMITIVE_CANONIZATION_NOTE.md"
    text = path.read_text(encoding="utf-8").lower()
    assert "/v1/content/runs" in text
    assert "/v1/content/runs/prompt" in text
    assert "provisional but valid" in text
    assert "source-conditioned long-form drafting" in text
    assert "content_blocks_v1" in text
    assert "draft_package" in text
    assert "structure_expansion" in text
    assert "item_generation" in text
    assert "what is not settled yet" in text
    forbidden = [
        "teaching_document",
        "knowledge_mindmap",
        "interactive_quick_quiz",
        "interactive_games",
        "demonstration_animations",
        "speaker_notes",
        "neo",
        "spectra",
    ]
    for term in forbidden:
        assert term not in text, f"PRIMITIVE_CANONIZATION_NOTE.md should not contain {term!r}"


def test_structured_content_taxonomy_should_keep_non_ppt_axis_generic() -> None:
    path = ROOT / "docs" / "STRUCTURED_CONTENT_PRIMITIVE_TAXONOMY.md"
    text = path.read_text(encoding="utf-8").lower()
    required = [
        "source-conditioned structured",
        "not as product modes",
        "draft_package",
        "structure_expansion",
        "item_generation",
        "sequence_or_script_plan",
        "interaction_schema",
        "/v1/content/runs",
        "provisional but valid",
        "active pressure",
        "does not freeze a new wire format",
        "do not make diego emit markdown as primary truth",
    ]
    forbidden = [
        "teaching_document",
        "knowledge_mindmap",
        "interactive_quick_quiz",
        "interactive_games",
        "demonstration_animations",
        "speaker_notes",
        "/v1/mindmap",
        "/v1/quiz",
        "/v1/teaching-document",
        "diego owns formal artifact",
        "diego owns shell",
    ]
    for marker in required:
        assert marker in text, f"taxonomy missing {marker!r}"
    for term in forbidden:
        assert term not in text, f"taxonomy should not contain {term!r}"


def test_provisional_and_canonical_markers_should_remain_honest_across_status_docs() -> None:
    canon = (ROOT / "docs" / "PRIMITIVE_CANONIZATION_NOTE.md").read_text(
        encoding="utf-8"
    ).lower()
    status = (ROOT / "docs" / "STRUCTURED_GENERATION_PRIMITIVE_STATUS_NOTE.md").read_text(
        encoding="utf-8"
    ).lower()
    assert "content_blocks_v1" in canon and "canonical" in status
    assert "draft_package" in canon and "provisional but valid" in status
    assert "/v1/content/runs" in canon and "provisional but valid" in canon
    assert "sequence_or_script_plan" in status and "active pressure" in status
    assert "stable public api" not in status
