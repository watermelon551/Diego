from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _iter_py_files(base: Path):
    for path in base.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def test_legacy_shims_should_use_explicit_exports() -> None:
    shim_files = [
        ROOT / "service" / "app.py",
        ROOT / "service" / "orchestrator.py",
        ROOT / "service" / "llm_client.py",
        ROOT / "service" / "store.py",
        ROOT / "service" / "skill_profile.py",
        ROOT / "service" / "style_catalog.py",
    ]
    for path in shim_files:
        text = path.read_text(encoding="utf-8")
        assert "import *" not in text, f"{path} should not use wildcard exports"


def test_layer_boundaries_should_not_have_forbidden_imports() -> None:
    checks: list[tuple[Path, list[str]]] = [
        (
            ROOT / "service" / "api",
            [
                r"from\s+\.\.(templates|slides|design)\b",
                r"from\s+service\.(templates|slides|design)\b",
            ],
        ),
        (
            ROOT / "service" / "design",
            [
                r"from\s+\.\.(run|api|templates|slides)\b",
                r"from\s+service\.(run|api|templates|slides)\b",
            ],
        ),
        (
            ROOT / "service" / "models",
            [
                r"from\s+\.\.(run|api|templates|slides)\b",
                r"from\s+service\.(run|api|templates|slides)\b",
            ],
        ),
        (
            ROOT / "service" / "infra",
            [
                r"from\s+\.\.(api|run|slides|templates)\b",
                r"from\s+service\.(api|run|slides|templates)\b",
            ],
        ),
    ]
    violations: list[str] = []
    for base, patterns in checks:
        for path in _iter_py_files(base):
            text = path.read_text(encoding="utf-8")
            for pattern in patterns:
                if re.search(pattern, text):
                    rel = path.relative_to(ROOT).as_posix()
                    violations.append(f"{rel} matches forbidden pattern: {pattern}")
    assert not violations, "Forbidden imports found:\n" + "\n".join(violations)


def test_runtime_kernel_and_engines_should_keep_explicit_boundaries() -> None:
    checks: list[tuple[Path, list[str]]] = [
        (
            ROOT / "service" / "run" / "kernel.py",
            [
                r"from\s+\.\.(app|orchestrator|llm_client|store)\b",
                r"from\s+service\.(app|orchestrator|llm_client|store)\b",
            ],
        ),
        (
            ROOT / "service" / "run" / "engines" / "template_engine.py",
            [
                r"from\s+.+scratch_engine\b",
            ],
        ),
        (
            ROOT / "service" / "run" / "engines" / "scratch_engine.py",
            [
                r"from\s+.+template_engine\b",
            ],
        ),
        (
            ROOT / "service" / "run" / "engines" / "quality_engine.py",
            [
                r"RunStatus",
                r"setattr\(.*status",
                r"status\s*=",
            ],
        ),
    ]
    violations: list[str] = []
    for path, patterns in checks:
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            if re.search(pattern, text):
                rel = path.relative_to(ROOT).as_posix()
                violations.append(f"{rel} matches forbidden pattern: {pattern}")
    assert not violations, "Runtime boundary violations found:\n" + "\n".join(violations)


def test_internal_service_modules_should_not_import_legacy_shims() -> None:
    service_root = ROOT / "service"
    shim_roots = {
        service_root / "app.py",
        service_root / "orchestrator.py",
        service_root / "llm_client.py",
        service_root / "store.py",
        service_root / "skill_profile.py",
        service_root / "style_catalog.py",
        service_root / "_compat.py",
        service_root / "__init__.py",
    }
    patterns = [
        r"from\s+\.{2,}(app|orchestrator|llm_client|store|skill_profile|style_catalog)\s+import\b",
        r"from\s+service\.(app|orchestrator|llm_client|store|skill_profile|style_catalog)\s+import\b",
        r"import\s+service\.(app|orchestrator|llm_client|store|skill_profile|style_catalog)\b",
    ]
    violations: list[str] = []
    for path in _iter_py_files(service_root):
        if path in shim_roots:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            if re.search(pattern, text):
                rel = path.relative_to(ROOT).as_posix()
                violations.append(f"{rel} matches forbidden pattern: {pattern}")
    assert not violations, "Legacy shim imports found in internal modules:\n" + "\n".join(violations)


def test_core_files_should_respect_size_guards() -> None:
    exempt_over_500 = {
        "service/run/orchestrator.py": "transition facade while legacy helper methods are still migrating",
        "service/slides/js_quality_mixin.py": "legacy quality logic migration in progress",
        "service/templates/template_ops_mixin.py": "legacy template logic migration in progress",
        "service/run/slide_scene.py": "editable slide scene parsing and transform migration is still consolidated here",
        "service/design/style_catalog.py": "catalog data and normalization rules intentionally centralized",
        "service/llm/client.py": "provider client and parsing compatibility surface intentionally centralized",
        "service/llm/mock.py": "mock provider now covers both ppt and longform capability surfaces",
        "service/content/service.py": "longform orchestration is intentionally centralized for the first host-agnostic cut",
        "service/models/contracts.py": "shared contract surface now includes both ppt and longform capability families",
    }
    exempt_over_300 = {
        "service/run/flows/outline_flow.py",
        "service/run/services/compile_service.py",
        "service/run/services/quality_repair_service.py",
        "service/run/slide_preview.py",
        "service/run/flows/scratch_flow.py",
        "service/templates/asset_search_mixin.py",
        "service/design/skill_profile.py",
        "service/models/contracts.py",
        "service/content/service.py",
        "service/llm/mock.py",
        "service/llm/types.py",
        "service/config.py",
        "service/infra/store.py",
        "service/application/slides.py",
        "service/api/app.py",
    }
    violations: list[str] = []
    for path in _iter_py_files(ROOT / "service"):
        rel = path.relative_to(ROOT).as_posix()
        lines = path.read_text(encoding="utf-8").count("\n") + 1
        if lines > 500 and rel not in exempt_over_500:
            violations.append(f"{rel} is {lines} lines and has no >500 exemption")
        elif lines > 300 and rel not in exempt_over_500 and rel not in exempt_over_300:
            violations.append(f"{rel} is {lines} lines and has no >300 exemption")
    assert not violations, "Core file size guard violations found:\n" + "\n".join(violations)


def test_docs_should_describe_generation_and_external_compile_boundary() -> None:
    checks = {
        ROOT / "README.md": [
            "Diego 负责生成",
            "外部 compile provider 负责渲染/编译/导出",
            "Pagevra` 是当前支持的 provider 之一",
            "host-agnostic 的 long-form drafting primitive",
        ],
        ROOT / "docs" / "PROJECT_GOALS.md": [
            "compile bundle",
            "不依赖特定上游系统实现细节",
            "source-aware long-form drafting",
        ],
        ROOT / "docs" / "ARCHITECTURE.md": [
            "generation truth",
            "external compile provider",
            "drafting truth",
        ],
    }
    missing: list[str] = []
    for path, patterns in checks.items():
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            if pattern not in text:
                missing.append(f"{path.relative_to(ROOT).as_posix()} missing {pattern!r}")
    assert not missing, "Docs boundary contract drift found:\n" + "\n".join(missing)


def test_capability_note_should_keep_generic_structure_language() -> None:
    path = ROOT / "docs" / "CAPABILITY_NOTES.md"
    text = path.read_text(encoding="utf-8").lower()
    assert "source-conditioned structure expansion" in text
    assert "do not add public api" in text
    forbidden = [
        "knowledge_mindmap",
        "studio-card",
        "graph editor",
        "node anchor",
        "neo",
        "spectra",
    ]
    for term in forbidden:
        assert term not in text


def test_generic_primitive_notes_should_remain_capability_shaped() -> None:
    note_paths = [
        ROOT / "docs" / "GENERIC_PRIMITIVE_REFERENCE_NOTE.md",
        ROOT / "docs" / "GENERIC_PRIMITIVE_BACKLOG_NOTE.md",
        ROOT / "docs" / "GENERIC_PRIMITIVE_BOUNDARY_NOTE.md",
        ROOT / "docs" / "GENERIC_PRIMITIVE_NEXT_STEPS.md",
        ROOT / "docs" / "INTERACTION_SCHEMA_PRIMITIVE_BOUNDARY_REVIEW_NOTE.md",
        ROOT / "docs" / "PRIMITIVE_CANONIZATION_NOTE.md",
        ROOT / "docs" / "STRUCTURED_GENERATION_PRIMITIVE_STATUS_NOTE.md",
        ROOT / "docs" / "MINIMAL_CONSUMER_SHAPE_NOTE.md",
        ROOT / "docs" / "PILOT_PRESSURE_SUMMARY_NOTE.md",
        ROOT / "docs" / "HANDOFF_SHAPE_EVALUATION_NOTE.md",
        ROOT / "docs" / "CONSUMER_BOUNDARY_TABLE.md",
        ROOT / "docs" / "CROSS_CONSUMER_PRIMITIVE_ASSESSMENT.md",
        ROOT / "docs" / "HANDOFF_BACKLOG_NOTE.md",
        ROOT / "docs" / "OWNER_REALITY_CLASSIFICATION_NOTE.md",
        ROOT / "docs" / "NEXT_PRIMITIVE_SURFACE_NOTE.md",
        ROOT / "docs" / "OWNER_ACCEPTANCE_NOTE.md",
        ROOT / "docs" / "STRUCTURED_CONTENT_PRIMITIVE_TAXONOMY.md",
    ]
    forbidden = [
        "teaching_document",
        "knowledge_mindmap",
        "interactive_quick_quiz",
        "interactive_games",
        "demonstration_animations",
        "speaker_notes",
        "studio-card",
        "neo",
        "spectra",
    ]
    expected_markers = {
        "GENERIC_PRIMITIVE_REFERENCE_NOTE.md": ["artifact-first", "host-agnostic"],
        "GENERIC_PRIMITIVE_BACKLOG_NOTE.md": [
            "source-conditioned long-form drafting",
            "structure_expansion",
            "item_generation",
            "draft_package",
            "promising but premature",
            "keep in shell/workflow for now",
            "provisional but valid",
            "canonical now",
            "provisional implementation",
            "active pressure",
        ],
        "GENERIC_PRIMITIVE_BOUNDARY_NOTE.md": [
            "capability-shaped",
            "generic generation contracts",
            "formal artifact truth",
            "host workflow state",
        ],
        "GENERIC_PRIMITIVE_NEXT_STEPS.md": [
            "source-conditioned long-form drafting",
            "source-conditioned structure expansion",
        ],
        "INTERACTION_SCHEMA_PRIMITIVE_BOUNDARY_REVIEW_NOTE.md": [
            "interaction schema",
            "do not promote yet",
            "sequence_or_script_plan",
            "algorithm_trace",
            "state",
            "transition",
            "checkpoint",
            "trace",
            "forbidden ownership",
        ],
        "PRIMITIVE_CANONIZATION_NOTE.md": [
            "/v1/content/runs",
            "/v1/content/runs/prompt",
            "provisional but valid",
            "source-conditioned long-form drafting",
            "generic content-object output",
            "draft_package",
            "structure_expansion",
            "item_generation",
            "what diego already owns cleanly",
            "generation result",
            "structured draft output",
            "sequence_or_script_plan",
        ],
        "STRUCTURED_GENERATION_PRIMITIVE_STATUS_NOTE.md": [
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
        ],
        "MINIMAL_CONSUMER_SHAPE_NOTE.md": [
            "generic consumer",
            "content_blocks_v1",
            "explicit lifecycle state",
            "does not expect diego to own",
        ],
        "PILOT_PRESSURE_SUMMARY_NOTE.md": [
            "document-style pilot pressure",
            "consumer translation",
            "formatting and artifact projection responsibility should remain consumer-side",
        ],
        "HANDOFF_SHAPE_EVALUATION_NOTE.md": [
            "content blocks",
            "sectioned long-form draft",
            "source-conditioned draft package",
            "promising but premature",
        ],
        "CONSUMER_BOUNDARY_TABLE.md": [
            "markdown formatting",
            "document compile/export",
            "artifact persistence and formal state",
            "shell orchestration semantics",
        ],
        "CROSS_CONSUMER_PRIMITIVE_ASSESSMENT.md": [
            "long-form document-style consumer",
            "item-oriented consumer",
            "structure-oriented consumer",
            "hidden consumer modes inside diego",
        ],
        "HANDOFF_BACKLOG_NOTE.md": [
            "do now",
            "wait for more pressure",
            "do not do",
            "do not make diego emit markdown as primary truth",
        ],
        "OWNER_REALITY_CLASSIFICATION_NOTE.md": [
            "canonical now",
            "provisional but valid",
            "experimental or sample-only",
            "legacy or not to carry forward",
            "content_blocks_v1",
        ],
        "NEXT_PRIMITIVE_SURFACE_NOTE.md": [
            "source-conditioned draft package",
            "accepted input concepts",
            "returned output concepts",
            "failure and validation expectations",
            "what remains outside diego",
        ],
        "OWNER_ACCEPTANCE_NOTE.md": [
            "ready for later thin shell consumption",
            "/v1/content/runs",
            "provisional but valid",
            "must not be consumed as stable yet",
            "draft_package",
            "structure_expansion",
            "item_generation",
        ],
        "STRUCTURED_CONTENT_PRIMITIVE_TAXONOMY.md": [
            "source-conditioned structured",
            "generation_result",
            "generic_content_object_output",
            "retrieval_conditioned_input",
            "draft_package",
            "structure_expansion",
            "item_generation",
            "sequence_or_script_plan",
            "provisional but valid",
            "provisional implementation",
            "active pressure",
        ],
    }
    for path in note_paths:
        text = path.read_text(encoding="utf-8").lower()
        for term in forbidden:
            assert term not in text, f"{path.name} should not contain {term!r}"
        for marker in expected_markers[path.name]:
            assert marker in text, f"{path.name} missing {marker!r}"


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


def test_content_surface_should_keep_generic_endpoint_and_model_naming() -> None:
    api_text = (ROOT / "service" / "api" / "app.py").read_text(encoding="utf-8").lower()
    contract_text = (ROOT / "service" / "models" / "contracts.py").read_text(
        encoding="utf-8"
    ).lower()

    forbidden_endpoints = [
        "/v1/mindmap/",
        "/v1/quiz/",
        "/v1/teaching-document/",
        "/v1/knowledge-mindmap/",
        "/v1/interactive-quick-quiz/",
    ]
    forbidden_model_names = [
        "class mindmap",
        "class quiz",
        "class teachingdocument",
        "class knowledgemindmap",
        "class interactivequickquiz",
    ]

    for term in forbidden_endpoints:
        assert term not in api_text, f"content api should not contain {term!r}"
    for term in forbidden_model_names:
        assert term not in contract_text, f"contracts should not contain {term!r}"


def test_item_generation_contract_should_keep_generic_revision_ready_fields() -> None:
    text = (ROOT / "service" / "models" / "contracts.py").read_text(encoding="utf-8")
    item_start = text.index("class GeneratedItem")
    item_segment = text[item_start : item_start + 800]
    result_start = text.index("class ItemGenerationResult")
    result_segment = text[result_start : result_start + 500]
    assert "expected_response" in item_segment
    assert "expected_response_hints" in item_segment
    assert "revision_targets" in result_segment
    forbidden = [
        "grading",
        "score",
        "exam",
        "classroom assessment",
        "quiz",
        "preview",
        "export",
        "docx",
        "html",
    ]
    lowered = (item_segment + result_segment).lower()
    for term in forbidden:
        assert term not in lowered, f"item generation contract should not contain {term!r}"


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
        paths = list(_iter_py_files(target)) if target.is_dir() else [target]
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


def test_compile_provider_default_should_not_point_to_external_service() -> None:
    text = (ROOT / "service" / "config.py").read_text(encoding="utf-8")
    assert 'compile_provider: str = "none"' in text
    assert 'os.getenv("COMPILE_PROVIDER", "none")' in text
    assert 'pagevra_preview_enabled: bool = False' in text
    assert 'pagevra_preview_enabled=_env_bool("PAGEVRA_PREVIEW_ENABLED", False)' in text


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
        paths = list(_iter_py_files(target)) if target.is_dir() else [target]
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
        paths = list(_iter_py_files(target)) if target.is_dir() else [target]
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
    text = (ROOT / "service" / "models" / "contracts.py").read_text(encoding="utf-8")
    snippets = [
        "class LongFormRunRequest",
        "class LongFormPlanSection",
        "class LongFormDraftSection",
        "class LongFormDraft",
    ]
    for snippet in snippets:
        start = text.index(snippet)
        segment = text[start : start + 700]
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
    text = (ROOT / "service" / "models" / "contracts.py").read_text(encoding="utf-8")
    request_start = text.index("class LongFormRunRequest")
    request_segment = text[request_start : request_start + 1200]
    draft_start = text.index("class LongFormDraft")
    draft_segment = text[draft_start : draft_start + 800]
    assert "output_format_hint" not in request_segment
    assert 'content_schema: Literal["content_blocks_v1"] = "content_blocks_v1"' in draft_segment
    assert "markdown" not in draft_segment
