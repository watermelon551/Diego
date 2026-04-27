from __future__ import annotations

import re

from tests.service.architecture_guard_support import ROOT, iter_py_files


def test_structured_content_primitives_should_not_absorb_renderer_or_export_tooling() -> None:
    targets = [
        ROOT / "docs" / "STRUCTURED_CONTENT_PRIMITIVE_TAXONOMY.md",
        ROOT / "docs" / "GENERIC_PRIMITIVE_BACKLOG_NOTE.md",
        ROOT / "docs" / "PRIMITIVE_CANONIZATION_NOTE.md",
        ROOT / "docs" / "NEXT_PRIMITIVE_SURFACE_NOTE.md",
        ROOT / "docs" / "OWNER_ACCEPTANCE_NOTE.md",
        ROOT / "service" / "content",
        ROOT / "service" / "application" / "content.py",
    ]
    forbidden = [
        "gif",
        "pptx",
        "rive",
        "remotion",
        "pagevra",
        "demonstration_animations",
        "animation_card",
        "animation card",
    ]
    violations: list[str] = []
    for target in targets:
        paths = list(iter_py_files(target)) if target.is_dir() else [target]
        for path in paths:
            text = path.read_text(encoding="utf-8").lower()
            for term in forbidden:
                if term in text:
                    rel = path.relative_to(ROOT).as_posix()
                    violations.append(f"{rel} contains renderer/export ontology term {term!r}")
    assert not violations, (
        "Structured-content primitive ownership absorbed renderer/export terms:\n"
        + "\n".join(violations)
    )


def test_interaction_schema_review_note_should_keep_boundary_conservative() -> None:
    path = ROOT / "docs" / "INTERACTION_SCHEMA_PRIMITIVE_BOUNDARY_REVIEW_NOTE.md"
    text = path.read_text(encoding="utf-8").lower()
    required = [
        "current status",
        "do not promote yet",
        "sequence_or_script_plan",
        "algorithm_trace",
        "process_trace",
        "remaining pressure samples required",
        "forbidden ownership",
        "gif",
        "pptx step deck",
        "html preview",
        "rive",
        "remotion",
        "pagevra materialization",
    ]
    forbidden = [
        "mindmap",
        "quiz",
        "teaching_document",
        "knowledge_mindmap",
        "interactive_quick_quiz",
        "neo",
        "spectra",
        "public api now",
        "stable final api",
    ]
    for marker in required:
        assert marker in text, f"interaction schema note missing {marker!r}"
    for term in forbidden:
        assert term not in text, f"interaction schema note should not contain {term!r}"


def test_structured_generation_fixtures_should_use_generic_language_only() -> None:
    path = ROOT / "tests" / "fixtures" / "structured_generation_samples.json"
    text = path.read_text(encoding="utf-8").lower()
    required = [
        "longform_draft",
        "structure_expansion",
        "item_generation",
        "sequence_or_script_plan",
        "algorithm_trace",
        "process_trace",
        "content_blocks_v1",
        "revision_targets",
    ]
    forbidden = [
        "teaching_document",
        "knowledge_mindmap",
        "interactive_quick_quiz",
        "demonstration_animations",
        "interactive_games",
        "speaker_notes",
        "pagevra",
        "ourograph",
        "rive",
        "remotion",
        "gif",
        "pptx_step_deck",
        "html_preview",
        "shell",
        "workbench",
    ]
    for marker in required:
        assert marker in text, f"fixture file missing {marker!r}"
    for term in forbidden:
        pattern = r"(?<![a-z0-9_])" + re.escape(term) + r"(?![a-z0-9_])"
        assert not re.search(pattern, text), f"fixture file should not contain {term!r}"
