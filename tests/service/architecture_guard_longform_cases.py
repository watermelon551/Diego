from __future__ import annotations

from tests.service.architecture_guard_support import ROOT, iter_py_files


def test_longform_modules_and_docs_should_avoid_host_product_ontology() -> None:
    forbidden = [
        "spectra",
        "neo",
        "lesson_plan",
        "teaching document",
        "word_document",
        "studio-card",
        "card ontology",
    ]
    targets = [
        ROOT / "service" / "content",
        ROOT / "service" / "application" / "content.py",
        ROOT / "docs" / "ARCHITECTURE.md",
    ]
    violations: list[str] = []
    for target in targets:
        paths = list(iter_py_files(target)) if target.is_dir() else [target]
        for path in paths:
            text = path.read_text(encoding="utf-8").lower()
            for term in forbidden:
                if term in text:
                    rel = path.relative_to(ROOT).as_posix()
                    violations.append(f"{rel} contains forbidden term {term!r}")
    assert not violations, "Host/product ontology leaked into longform surface:\n" + "\n".join(violations)


def test_longform_surface_should_not_adopt_export_preview_compile_success_semantics() -> None:
    targets = [
        ROOT / "service" / "content",
        ROOT / "service" / "application" / "content.py",
        ROOT / "service" / "api" / "app.py",
    ]
    allowed_markers = {
        "preview": ["/v1/ppt/"],
        "docx": [],
        "export": [],
        "compile provider": [],
    }
    violations: list[str] = []
    for target in targets:
        paths = list(iter_py_files(target)) if target.is_dir() else [target]
        for path in paths:
            text = path.read_text(encoding="utf-8").lower()
            if "content/runs" not in text and "longform" not in text and "contentapplicationservice" not in text:
                continue
            for term, exceptions in allowed_markers.items():
                if term in text and not any(marker.lower() in text for marker in exceptions):
                    rel = path.relative_to(ROOT).as_posix()
                    violations.append(f"{rel} contains forbidden longform term {term!r}")
    assert not violations, "Longform boundary drift found:\n" + "\n".join(violations)


def test_longform_contracts_should_not_use_ppt_center_fields() -> None:
    segments = [
        (ROOT / "service" / "content" / "contracts" / "requests.py").read_text(
            encoding="utf-8"
        ),
        (ROOT / "service" / "content" / "contracts" / "results.py").read_text(
            encoding="utf-8"
        ),
    ]
    for segment in segments:
        assert "target_slide_count" not in segment
        assert "page_type" not in segment
        assert "layout_hint" not in segment
        assert "pptx_path" not in segment
        assert "compile_bundle" not in segment
        assert "compile_result" not in segment
        assert "preview" not in segment
        assert "export" not in segment
        assert "docx" not in segment


def test_longform_contracts_should_keep_generic_content_object_as_canonical_output() -> None:
    request_segment = (
        ROOT / "service" / "content" / "contracts" / "requests.py"
    ).read_text(encoding="utf-8")
    draft_segment = (
        ROOT / "service" / "content" / "contracts" / "results.py"
    ).read_text(encoding="utf-8")
    assert "output_format_hint" not in request_segment
    assert 'content_schema: Literal["content_blocks_v1"] = "content_blocks_v1"' in draft_segment
    assert "markdown" not in draft_segment
