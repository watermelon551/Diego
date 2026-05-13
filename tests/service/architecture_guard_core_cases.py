from __future__ import annotations

import re
from pathlib import Path

from tests.service.architecture_guard_support import ROOT, iter_py_files


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
        for path in iter_py_files(base):
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
    for path in iter_py_files(service_root):
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
        "service/run/slide_scene/__init__.py": "slide scene package entry point intentionally carries the public parser surface",
        "service/llm/client.py": "provider client and parsing compatibility surface intentionally centralized",
        "service/llm/mock.py": "mock provider now covers both ppt and longform capability surfaces",
    }
    exempt_over_300 = {
        "service/run/services/compile_service.py",
        "service/run/services/quality_repair_service.py",
        "service/run/slide_preview.py",
        "service/run/flows/scratch_flow.py",
        "service/templates/asset_search_mixin.py",
        "service/llm/mock.py",
        "service/llm/types.py",
        "service/config.py",
        "service/application/slides.py",
        "service/api/app.py",
        "service/run/agentic_slide_generation.py",
    }
    violations: list[str] = []
    for path in iter_py_files(ROOT / "service"):
        rel = path.relative_to(ROOT).as_posix()
        lines = path.read_text(encoding="utf-8").count("\n") + 1
        if lines > 500 and rel not in exempt_over_500:
            violations.append(f"{rel} is {lines} lines and has no >500 exemption")
        elif lines > 300 and rel not in exempt_over_500 and rel not in exempt_over_300:
            violations.append(f"{rel} is {lines} lines and has no >300 exemption")
    assert not violations, "Core file size guard violations found:\n" + "\n".join(violations)


def test_llm_module_layout_should_remain_explicit_and_decomposed() -> None:
    llm_dir = ROOT / "service" / "llm"
    required_files = {
        "client.py",
        "client_protocol.py",
        "content_primitives_client.py",
        "format_errors.py",
        "mock.py",
        "mock_outline_generation_mixin.py",
        "mock_longform_content_mixin.py",
        "mock_slide_generation_mixin.py",
        "mock_slide_spec_mixin.py",
        "transport.py",
        "response_formats.py",
        "outline_prompt_client.py",
        "longform_planning_client.py",
        "longform_drafting_client.py",
        "slide_codegen_client.py",
        "slide_spec_client.py",
        "slide_types.py",
        "slide_response_parsers.py",
        "outline_normalization.py",
        "parsing.py",
        "types.py",
    }
    existing_files = {path.name for path in llm_dir.glob("*.py")}
    missing = sorted(required_files - existing_files)
    assert not missing, f"service/llm missing expected explicit modules: {missing}"

    forbidden_names = {"helpers.py", "utils.py", "common.py", "misc.py"}
    found_forbidden = sorted(forbidden_names & existing_files)
    assert not found_forbidden, (
        "service/llm should not regress into vague dumping-ground modules: "
        + ", ".join(found_forbidden)
    )

    client_path = llm_dir / "client.py"
    client_text = client_path.read_text(encoding="utf-8")
    client_lines = client_text.count("\n") + 1
    assert client_lines <= 120, "service/llm/client.py should remain a thin facade"
    for marker in [
        "LLMTransportMixin",
        "LLMStructuredOutputMixin",
        "LLMOutlinePromptMixin",
        "LLMLongFormPlanningMixin",
        "LLMLongFormDraftingMixin",
        "LLMSlideCodegenMixin",
        "LLMSlideSpecMixin",
    ]:
        assert marker in client_text, f"service/llm/client.py missing {marker}"

    mock_path = llm_dir / "mock.py"
    mock_text = mock_path.read_text(encoding="utf-8")
    mock_lines = mock_text.count("\n") + 1
    assert mock_lines <= 80, "service/llm/mock.py should remain a thin facade"
    for marker in [
        "MockOutlineGenerationMixin",
        "MockLongFormContentMixin",
        "MockSlideGenerationMixin",
        "MockSlideSpecMixin",
    ]:
        assert marker in mock_text, f"service/llm/mock.py missing {marker}"

    types_path = llm_dir / "types.py"
    types_text = types_path.read_text(encoding="utf-8")
    types_lines = types_text.count("\n") + 1
    assert types_lines <= 60, "service/llm/types.py should remain a thin facade"
    for marker in [
        "from .client_protocol import",
        "from .format_errors import",
        "from .slide_types import",
        "__all__",
    ]:
        assert marker in types_text, f"service/llm/types.py missing {marker}"

    mock_longform_path = llm_dir / "mock_longform_content_mixin.py"
    mock_longform_text = mock_longform_path.read_text(encoding="utf-8")
    mock_longform_lines = mock_longform_text.count("\n") + 1
    assert mock_longform_lines <= 40, (
        "service/llm/mock_longform_content_mixin.py should remain a thin facade"
    )
    for marker in [
        "MockLongFormPlanningMixin",
        "MockLongFormDraftingMixin",
        "MockStructuredContentGenerationMixin",
    ]:
        assert marker in mock_longform_text, (
            "service/llm/mock_longform_content_mixin.py missing " + marker
        )

    mock_longform_runtime_dir = llm_dir / "mock_longform_runtime"
    required_mock_longform_runtime_files = {
        "__init__.py",
        "planning_mixin.py",
        "drafting_mixin.py",
        "structured_generation_mixin.py",
    }
    existing_mock_longform_runtime_files = {
        path.name for path in mock_longform_runtime_dir.glob("*.py")
    }
    missing_mock_longform_runtime = sorted(
        required_mock_longform_runtime_files - existing_mock_longform_runtime_files
    )
    assert not missing_mock_longform_runtime, (
        "service/llm/mock_longform_runtime missing expected mock longform modules: "
        f"{missing_mock_longform_runtime}"
    )

    protocol_dir = llm_dir / "protocols"
    required_protocol_files = {
        "__init__.py",
        "base.py",
        "client.py",
        "content.py",
        "outline.py",
        "slide.py",
    }
    existing_protocol_files = {path.name for path in protocol_dir.glob("*.py")}
    missing_protocols = sorted(required_protocol_files - existing_protocol_files)
    assert not missing_protocols, (
        "service/llm/protocols missing expected capability protocol modules: "
        f"{missing_protocols}"
    )

    protocol_facade_path = llm_dir / "client_protocol.py"
    protocol_facade_text = protocol_facade_path.read_text(encoding="utf-8")
    protocol_facade_lines = protocol_facade_text.count("\n") + 1
    assert protocol_facade_lines <= 40, (
        "service/llm/client_protocol.py should remain a thin compatibility facade"
    )
    for marker in ["from .protocols import", "__all__"]:
        assert marker in protocol_facade_text, (
            f"service/llm/client_protocol.py missing {marker}"
        )

    transport_path = llm_dir / "transport.py"
    transport_text = transport_path.read_text(encoding="utf-8")
    transport_lines = transport_text.count("\n") + 1
    assert transport_lines <= 50, "service/llm/transport.py should remain a thin facade"
    for marker in [
        "LLMJsonRepairMixin",
        "LLMOpenAIChatTextMixin",
        "LLMOpenAIStreamMixin",
        "LLMAnthropicTransportMixin",
        "LLMResponseTextMixin",
    ]:
        assert marker in transport_text, f"service/llm/transport.py missing {marker}"

    transport_runtime_dir = llm_dir / "transport_runtime"
    required_transport_runtime_files = {
        "__init__.py",
        "json_repair_mixin.py",
        "chat_text_mixin.py",
        "stream_mixin.py",
        "anthropic_mixin.py",
        "response_text_mixin.py",
    }
    existing_transport_runtime_files = {
        path.name for path in transport_runtime_dir.glob("*.py")
    }
    missing_transport_runtime = sorted(
        required_transport_runtime_files - existing_transport_runtime_files
    )
    assert not missing_transport_runtime, (
        "service/llm/transport_runtime missing expected transport modules: "
        f"{missing_transport_runtime}"
    )

    outline_prompt_path = llm_dir / "outline_prompt_client.py"
    outline_prompt_text = outline_prompt_path.read_text(encoding="utf-8")
    outline_prompt_lines = outline_prompt_text.count("\n") + 1
    assert outline_prompt_lines <= 40, (
        "service/llm/outline_prompt_client.py should remain a thin facade"
    )
    for marker in [
        "LLMOutlineRequirementsMixin",
        "LLMOutlinePlanningMixin",
    ]:
        assert marker in outline_prompt_text, (
            "service/llm/outline_prompt_client.py missing " + marker
        )

    outline_runtime_dir = llm_dir / "outline_runtime"
    required_outline_runtime_files = {
        "__init__.py",
        "requirements_mixin.py",
        "planning_mixin.py",
    }
    existing_outline_runtime_files = {
        path.name for path in outline_runtime_dir.glob("*.py")
    }
    missing_outline_runtime = sorted(
        required_outline_runtime_files - existing_outline_runtime_files
    )
    assert not missing_outline_runtime, (
        "service/llm/outline_runtime missing expected outline modules: "
        f"{missing_outline_runtime}"
    )

    outline_normalization_path = llm_dir / "outline_normalization.py"
    outline_normalization_text = outline_normalization_path.read_text(encoding="utf-8")
    outline_normalization_lines = outline_normalization_text.count("\n") + 1
    assert outline_normalization_lines <= 40, (
        "service/llm/outline_normalization.py should remain a thin facade"
    )
    for marker in [
        "LLMOutlineDocumentNormalizationMixin",
        "LLMLongFormNormalizationMixin",
        "def _normalize_layout_hint",
    ]:
        assert marker in outline_normalization_text, (
            "service/llm/outline_normalization.py missing " + marker
        )

    normalization_runtime_dir = llm_dir / "normalization_runtime"
    required_normalization_runtime_files = {
        "__init__.py",
        "outline_mixin.py",
        "longform_mixin.py",
    }
    existing_normalization_runtime_files = {
        path.name for path in normalization_runtime_dir.glob("*.py")
    }
    missing_normalization_runtime = sorted(
        required_normalization_runtime_files - existing_normalization_runtime_files
    )
    assert not missing_normalization_runtime, (
        "service/llm/normalization_runtime missing expected normalization modules: "
        f"{missing_normalization_runtime}"
    )

    longform_planning_path = llm_dir / "longform_planning_client.py"
    longform_planning_text = longform_planning_path.read_text(encoding="utf-8")
    longform_planning_lines = longform_planning_text.count("\n") + 1
    assert longform_planning_lines <= 40, (
        "service/llm/longform_planning_client.py should remain a thin facade"
    )
    for marker in [
        "LLMLongFormRequirementsMixin",
        "LLMLongFormPlanGenerationMixin",
        "LLMLongFormPlanRevisionMixin",
    ]:
        assert marker in longform_planning_text, (
            "service/llm/longform_planning_client.py missing " + marker
        )

    longform_planning_runtime_dir = llm_dir / "longform_planning_runtime"
    required_longform_planning_runtime_files = {
        "__init__.py",
        "requirements_mixin.py",
        "plan_generation_mixin.py",
        "plan_revision_mixin.py",
    }
    existing_longform_planning_runtime_files = {
        path.name for path in longform_planning_runtime_dir.glob("*.py")
    }
    missing_longform_planning_runtime = sorted(
        required_longform_planning_runtime_files
        - existing_longform_planning_runtime_files
    )
    assert not missing_longform_planning_runtime, (
        "service/llm/longform_planning_runtime missing expected planning modules: "
        f"{missing_longform_planning_runtime}"
    )


def test_run_module_layout_should_avoid_vague_dumping_grounds() -> None:
    run_dir = ROOT / "service" / "run"
    forbidden_names = {"helpers.py", "utils.py", "common.py", "misc.py"}
    found = sorted(path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*.py") if path.name in forbidden_names)
    assert not found, (
        "service/run should keep explicit ownership instead of vague dumping-ground modules: "
        + ", ".join(found)
    )

    run_dir = ROOT / "service" / "run"
    required_run_files = {
        "slide_generation_primitives_mixin.py",
        "slide_generation_plan_adapter_mixin.py",
        "slide_generation_render_adapter_mixin.py",
    }
    existing_run_files = {path.name for path in run_dir.glob("*.py")}
    missing_run_files = sorted(required_run_files - existing_run_files)
    assert not missing_run_files, (
        "service/run missing expected slide generation adapter modules: "
        + ", ".join(missing_run_files)
    )

    primitives_text = (run_dir / "slide_generation_primitives_mixin.py").read_text(
        encoding="utf-8"
    )
    primitives_lines = primitives_text.count("\n") + 1
    assert primitives_lines <= 120, (
        "service/run/slide_generation_primitives_mixin.py should remain a thin generation facade"
    )
    for marker in [
        "SlideGenerationPlanAdapterMixin",
        "SlideGenerationRenderAdapterMixin",
        "def _generate_skill_slide",
        "def _generate_agentic_slide",
    ]:
        assert marker in primitives_text, (
            "service/run/slide_generation_primitives_mixin.py missing " + marker
        )


def test_content_module_layout_should_remain_explicit_and_split_by_runtime_role() -> None:
    content_dir = ROOT / "service" / "content"
    required_files = {
        "service.py",
        "run_lifecycle_mixin.py",
        "plan_runtime_mixin.py",
        "plan_confirm_mixin.py",
        "plan_requirements_mixin.py",
        "plan_generation_mixin.py",
        "draft_runtime_mixin.py",
        "draft_generation_mixin.py",
        "draft_revision_mixin.py",
        "draft_shape_mixin.py",
        "retrieval_runtime_mixin.py",
        "structured_generation_mixin.py",
    }
    existing_files = {path.name for path in content_dir.glob("*.py")}
    missing = sorted(required_files - existing_files)
    assert not missing, f"service/content missing expected explicit modules: {missing}"

    forbidden_names = {"helpers.py", "utils.py", "common.py", "misc.py"}
    found_forbidden = sorted(forbidden_names & existing_files)
    assert not found_forbidden, (
        "service/content should not regress into vague dumping-ground modules: "
        + ", ".join(found_forbidden)
    )

    service_path = content_dir / "service.py"
    service_text = service_path.read_text(encoding="utf-8")
    service_lines = service_text.count("\n") + 1
    assert service_lines <= 80, "service/content/service.py should remain a thin facade"
    for marker in [
        "ContentRunLifecycleMixin",
        "ContentPlanRuntimeMixin",
        "ContentDraftRuntimeMixin",
        "ContentRetrievalRuntimeMixin",
        "StructuredContentGenerationMixin",
    ]:
        assert marker in service_text, f"service/content/service.py missing {marker}"

    plan_text = (content_dir / "plan_runtime_mixin.py").read_text(encoding="utf-8")
    plan_lines = plan_text.count("\n") + 1
    assert plan_lines <= 80, (
        "service/content/plan_runtime_mixin.py should remain a thin orchestration facade"
    )
    for marker in [
        "ContentPlanConfirmMixin",
        "ContentPlanRequirementsMixin",
        "ContentPlanGenerationMixin",
    ]:
        assert marker in plan_text, (
            "service/content/plan_runtime_mixin.py missing " + marker
        )

    draft_text = (content_dir / "draft_runtime_mixin.py").read_text(encoding="utf-8")
    draft_lines = draft_text.count("\n") + 1
    assert draft_lines <= 80, (
        "service/content/draft_runtime_mixin.py should remain a thin orchestration facade"
    )
    for marker in [
        "ContentDraftRevisionMixin",
        "ContentDraftGenerationMixin",
        "ContentDraftShapeMixin",
    ]:
        assert marker in draft_text, (
            "service/content/draft_runtime_mixin.py missing " + marker
        )

    required_runtime_packages = {
        "planning_runtime": {
            "__init__.py",
            "confirm_mixin.py",
            "generation_mixin.py",
            "requirements_mixin.py",
        },
        "drafting_runtime": {
            "__init__.py",
            "generation_mixin.py",
            "revision_mixin.py",
            "shape_mixin.py",
        },
        "structured_runtime": {
            "__init__.py",
            "generation_mixin.py",
        },
    }
    for package_name, required_package_files in required_runtime_packages.items():
        package_dir = content_dir / package_name
        existing_package_files = {path.name for path in package_dir.glob("*.py")}
        missing_package = sorted(required_package_files - existing_package_files)
        assert not missing_package, (
            f"service/content/{package_name} missing expected package modules: "
            f"{missing_package}"
        )

    facade_expectations = {
        "plan_confirm_mixin.py": "from .planning_runtime.confirm_mixin import ContentPlanConfirmMixin",
        "plan_generation_mixin.py": "from .planning_runtime.generation_mixin import ContentPlanGenerationMixin",
        "plan_requirements_mixin.py": "from .planning_runtime.requirements_mixin import ContentPlanRequirementsMixin",
        "draft_generation_mixin.py": "from .drafting_runtime.generation_mixin import ContentDraftGenerationMixin",
        "draft_revision_mixin.py": "from .drafting_runtime.revision_mixin import ContentDraftRevisionMixin",
        "draft_shape_mixin.py": "from .drafting_runtime.shape_mixin import ContentDraftShapeMixin",
        "structured_generation_mixin.py": "from .structured_runtime.generation_mixin import StructuredContentGenerationMixin",
    }
    for file_name, marker in facade_expectations.items():
        facade_text = (content_dir / file_name).read_text(encoding="utf-8")
        facade_lines = facade_text.count("\n") + 1
        assert facade_lines <= 20, (
            f"service/content/{file_name} should remain a thin facade"
        )
        assert marker in facade_text, f"service/content/{file_name} missing {marker}"

    contracts_dir = content_dir / "contracts"
    required_contract_files = {"__init__.py", "requests.py", "results.py"}
    existing_contract_files = {path.name for path in contracts_dir.glob("*.py")}
    missing_contracts = sorted(required_contract_files - existing_contract_files)
    assert not missing_contracts, (
        "service/content/contracts missing expected content contract modules: "
        f"{missing_contracts}"
    )


def test_api_module_layout_should_remain_transport_focused() -> None:
    api_dir = ROOT / "service" / "api"
    required_files = {
        "app.py",
        "runtime_context.py",
        "ppt_routes.py",
        "content_routes.py",
    }
    existing_files = {path.name for path in api_dir.glob("*.py")}
    missing = sorted(required_files - existing_files)
    assert not missing, f"service/api missing expected transport modules: {missing}"

    forbidden_names = {"helpers.py", "utils.py", "common.py", "misc.py"}
    found_forbidden = sorted(forbidden_names & existing_files)
    assert not found_forbidden, (
        "service/api should not regress into vague dumping-ground modules: "
        + ", ".join(found_forbidden)
    )

    app_text = (api_dir / "app.py").read_text(encoding="utf-8")
    app_lines = app_text.count("\n") + 1
    assert app_lines <= 80, "service/api/app.py should remain a thin assembly facade"
    for marker in [
        "register_ppt_routes",
        "register_content_routes",
        "build_app_lifespan",
    ]:
        assert marker in app_text, f"service/api/app.py missing {marker}"


def test_design_catalog_module_layout_should_remain_explicit() -> None:
    design_dir = ROOT / "service" / "design"
    required_files = {
        "style_selection.py",
    }
    existing_files = {path.name for path in design_dir.glob("*.py")}
    missing = sorted(required_files - existing_files)
    assert not missing, f"service/design missing expected style catalog modules: {missing}"

    catalog_dir = design_dir / "style_catalog"
    required_catalog_files = {
        "__init__.py",
        "data.py",
        "shared.py",
        "instructional.py",
        "expressive.py",
        "selection.py",
    }
    existing_catalog_files = {path.name for path in catalog_dir.glob("*.py")}
    missing_catalog = sorted(required_catalog_files - existing_catalog_files)
    assert not missing_catalog, (
        "service/design/style_catalog missing expected package modules: "
        f"{missing_catalog}"
    )

    catalog_text = (catalog_dir / "__init__.py").read_text(encoding="utf-8")
    catalog_lines = catalog_text.count("\n") + 1
    assert catalog_lines <= 80, "service/design/style_catalog/__init__.py should remain a thin facade"
    for marker in [
        "from .data import",
        "from .selection import",
        "__all__",
    ]:
        assert marker in catalog_text, (
            "service/design/style_catalog/__init__.py missing " + marker
        )


def test_template_module_layout_should_remain_explicit() -> None:
    templates_dir = ROOT / "service" / "templates"
    required_files = {
        "asset_search_mixin.py",
        "asset_query_planning_mixin.py",
        "asset_provider_search_mixin.py",
        "asset_resolution_mixin.py",
        "template_ops_mixin.py",
        "template_structure_rebuild.py",
    }
    existing_files = {path.name for path in templates_dir.glob("*.py")}
    missing = sorted(required_files - existing_files)
    assert not missing, f"service/templates missing expected explicit modules: {missing}"

    forbidden_names = {"helpers.py", "utils.py", "common.py", "misc.py"}
    found_forbidden = sorted(forbidden_names & existing_files)
    assert not found_forbidden, (
        "service/templates should not regress into vague dumping-ground modules: "
        + ", ".join(found_forbidden)
    )

    asset_search_text = (templates_dir / "asset_search_mixin.py").read_text(encoding="utf-8")
    asset_search_lines = asset_search_text.count("\n") + 1
    assert asset_search_lines <= 160, "service/templates/asset_search_mixin.py should remain a thin facade"
    for marker in [
        "AssetQueryPlanningMixin",
        "AssetProviderSearchMixin",
        "AssetResolutionMixin",
    ]:
        assert marker in asset_search_text, (
            "service/templates/asset_search_mixin.py missing " + marker
        )

    structure_text = (templates_dir / "template_structure_rebuild.py").read_text(
        encoding="utf-8"
    )
    structure_lines = structure_text.count("\n") + 1
    assert structure_lines <= 160, (
        "service/templates/template_structure_rebuild.py should remain a thin facade"
    )
    for marker in [
        "_TemplateStructureRebuilder",
        "TemplateStructureDocumentMixin",
        "TemplateStructureSupportMixin",
        "def rebuild_template_structure",
        "def parse_xml_attrs",
    ]:
        assert marker in structure_text, (
            "service/templates/template_structure_rebuild.py missing " + marker
        )

    structure_dir = templates_dir / "template_structure"
    required_structure_files = {"__init__.py", "document.py", "support.py"}
    existing_structure_files = {path.name for path in structure_dir.glob("*.py")}
    missing_structure = sorted(required_structure_files - existing_structure_files)
    assert not missing_structure, (
        "service/templates/template_structure missing expected package modules: "
        f"{missing_structure}"
    )

    editing_dir = templates_dir / "template_editing"
    required_editing_files = {
        "__init__.py",
        "asset_rewrite.py",
        "chart_rewrite.py",
        "layout_reflow.py",
        "ops_mixin.py",
        "slot_mapping.py",
        "xml_rewrite.py",
    }
    existing_editing_files = {path.name for path in editing_dir.glob("*.py")}
    missing_editing = sorted(required_editing_files - existing_editing_files)
    assert not missing_editing, (
        "service/templates/template_editing missing expected package modules: "
        f"{missing_editing}"
    )

    ops_text = (templates_dir / "template_ops_mixin.py").read_text(encoding="utf-8")
    ops_lines = ops_text.count("\n") + 1
    assert ops_lines <= 40, "service/templates/template_ops_mixin.py should remain a thin facade"
    assert "from .template_editing import TemplateOpsMixin" in ops_text, (
        "service/templates/template_ops_mixin.py should delegate into the template_editing package"
    )

    editing_ops_dir = editing_dir / "ops"
    required_editing_ops_files = {
        "__init__.py",
        "structure_runtime_mixin.py",
        "semantic_rewrite_mixin.py",
    }
    existing_editing_ops_files = {path.name for path in editing_ops_dir.glob("*.py")}
    missing_editing_ops = sorted(
        required_editing_ops_files - existing_editing_ops_files
    )
    assert not missing_editing_ops, (
        "service/templates/template_editing/ops missing expected package modules: "
        f"{missing_editing_ops}"
    )

    editing_ops_facade_text = (editing_dir / "ops_mixin.py").read_text(encoding="utf-8")
    assert "from .ops import TemplateOpsMixin" in editing_ops_facade_text, (
        "service/templates/template_editing/ops_mixin.py should delegate into the ops package"
    )


def test_run_service_module_layout_should_remain_explicit() -> None:
    services_dir = ROOT / "service" / "run" / "services"
    required_files = {
        "compile_service.py",
        "compile_template_runtime_mixin.py",
        "compile_template_apply_mixin.py",
        "compile_template_candidate_extraction_mixin.py",
        "quality_repair_service.py",
        "slide_regeneration_service.py",
        "slide_regeneration_task_mixin.py",
        "slide_regeneration_preview_mixin.py",
        "slide_regeneration_scratch_mixin.py",
        "slide_regeneration_compile_mixin.py",
    }
    existing_files = {path.name for path in services_dir.glob("*.py")}
    missing = sorted(required_files - existing_files)
    assert not missing, f"service/run/services missing expected explicit modules: {missing}"

    service_path = services_dir / "quality_repair_service.py"
    service_text = service_path.read_text(encoding="utf-8")
    service_lines = service_text.count("\n") + 1
    assert service_lines <= 80, (
        "service/run/services/quality_repair_service.py should remain a thin facade"
    )
    for marker in [
        "CompileTemplateRuntimeMixin",
        "CompileTemplateApplyMixin",
        "CompileTemplateCandidateExtractionMixin",
    ]:
        assert marker in (services_dir / "compile_service.py").read_text(encoding="utf-8"), (
            "service/run/services/compile_service.py missing " + marker
        )

    quality_repair_dir = services_dir / "quality_repair"
    required_quality_repair_files = {
        "__init__.py",
        "cycles_mixin.py",
        "scratch_revision_mixin.py",
        "slide_candidate_parsing_mixin.py",
    }
    existing_quality_repair_files = {
        path.name for path in quality_repair_dir.glob("*.py")
    }
    missing_quality_repair = sorted(
        required_quality_repair_files - existing_quality_repair_files
    )
    assert not missing_quality_repair, (
        "service/run/services/quality_repair missing expected package modules: "
        f"{missing_quality_repair}"
    )

    quality_repair_init_text = (quality_repair_dir / "__init__.py").read_text(
        encoding="utf-8"
    )
    for marker in [
        "QualityRepairCyclesMixin",
        "QualityScratchRevisionMixin",
        "QualitySlideCandidateParsingMixin",
    ]:
        assert marker in quality_repair_init_text, (
            "service/run/services/quality_repair/__init__.py missing " + marker
        )

    scratch_revision_dir = quality_repair_dir / "scratch_revision"
    required_scratch_revision_files = {
        "__init__.py",
        "agentic_mixin.py",
        "agentic_iteration_mixin.py",
        "agentic_request_mixin.py",
        "agentic_slide_plan_mixin.py",
        "agentic_js_finalize_mixin.py",
        "standard_mixin.py",
    }
    existing_scratch_revision_files = {
        path.name for path in scratch_revision_dir.glob("*.py")
    }
    missing_scratch_revision = sorted(
        required_scratch_revision_files - existing_scratch_revision_files
    )
    assert not missing_scratch_revision, (
        "service/run/services/quality_repair/scratch_revision missing expected package modules: "
        f"{missing_scratch_revision}"
    )

    scratch_revision_facade_text = (
        quality_repair_dir / "scratch_revision_mixin.py"
    ).read_text(encoding="utf-8")
    assert "from .scratch_revision import QualityScratchRevisionMixin" in (
        scratch_revision_facade_text
    ), (
        "service/run/services/quality_repair/scratch_revision_mixin.py should delegate into the scratch_revision package"
    )

    agentic_mixin_text = (scratch_revision_dir / "agentic_mixin.py").read_text(
        encoding="utf-8"
    )
    agentic_mixin_lines = agentic_mixin_text.count("\n") + 1
    assert agentic_mixin_lines <= 40, (
        "service/run/services/quality_repair/scratch_revision/agentic_mixin.py should remain a thin facade"
    )
    for marker in [
        "AgenticScratchRevisionIterationMixin",
        "AgenticScratchRevisionRequestMixin",
        "AgenticScratchRevisionSlidePlanMixin",
        "AgenticScratchRevisionJsFinalizeMixin",
    ]:
        assert marker in agentic_mixin_text, (
            "service/run/services/quality_repair/scratch_revision/agentic_mixin.py missing "
            + marker
        )

    slide_regen_text = (services_dir / "slide_regeneration_service.py").read_text(
        encoding="utf-8"
    )
    slide_regen_lines = slide_regen_text.count("\n") + 1
    assert slide_regen_lines <= 80, (
        "service/run/services/slide_regeneration_service.py should remain a thin facade"
    )
    for marker in [
        "SlideRegenerationTaskMixin",
        "SlideRegenerationPreviewMixin",
        "SlideRegenerationScratchMixin",
        "SlideRegenerationCompileMixin",
    ]:
        assert marker in slide_regen_text, (
            "service/run/services/slide_regeneration_service.py missing " + marker
        )

    scratch_regen_facade_text = (
        services_dir / "slide_regeneration_scratch_mixin.py"
    ).read_text(encoding="utf-8")
    scratch_regen_facade_lines = scratch_regen_facade_text.count("\n") + 1
    assert scratch_regen_facade_lines <= 40, (
        "service/run/services/slide_regeneration_scratch_mixin.py should remain a thin facade"
    )
    for marker in [
        "SlideRegenerationScratchRuntimeMixin",
        "SlideRegenerationAgenticScratchMixin",
        "SlideRegenerationReviewedScratchMixin",
        "SlideRegenerationScratchFinalizeMixin",
    ]:
        assert marker in scratch_regen_facade_text, (
            "service/run/services/slide_regeneration_scratch_mixin.py missing "
            + marker
        )

    scratch_regen_dir = services_dir / "slide_regeneration_scratch"
    required_scratch_regen_files = {
        "__init__.py",
        "runtime_mixin.py",
        "agentic_mixin.py",
        "review_mixin.py",
        "finalize_mixin.py",
    }
    existing_scratch_regen_files = {
        path.name for path in scratch_regen_dir.glob("*.py")
    }
    missing_scratch_regen = sorted(
        required_scratch_regen_files - existing_scratch_regen_files
    )
    assert not missing_scratch_regen, (
        "service/run/services/slide_regeneration_scratch missing expected package modules: "
        f"{missing_scratch_regen}"
    )


def test_outline_flow_module_layout_should_remain_explicit() -> None:
    flows_dir = ROOT / "service" / "run" / "flows"
    required_files = {
        "outline_flow.py",
        "outline_flow_errors.py",
        "outline_requirements_mixin.py",
        "outline_generation_mixin.py",
        "outline_finalize_mixin.py",
        "scratch_flow.py",
        "scratch_slide_batch_mixin.py",
        "scratch_compile_mixin.py",
        "template_flow.py",
    }
    existing_files = {path.name for path in flows_dir.glob("*.py")}
    missing = sorted(required_files - existing_files)
    assert not missing, f"service/run/flows missing expected outline modules: {missing}"

    flow_text = (flows_dir / "outline_flow.py").read_text(encoding="utf-8")
    flow_lines = flow_text.count("\n") + 1
    assert flow_lines <= 120, "service/run/flows/outline_flow.py should remain a thin stage facade"
    for marker in [
        "OutlineRequirementsMixin",
        "OutlineGenerationMixin",
        "OutlineFinalizeMixin",
        "self._prepare_outline_requirements",
        "self._draft_outline",
        "self._finalize_outline",
    ]:
        assert marker in flow_text, f"service/run/flows/outline_flow.py missing {marker}"

    scratch_text = (flows_dir / "scratch_flow.py").read_text(encoding="utf-8")
    scratch_lines = scratch_text.count("\n") + 1
    assert scratch_lines <= 120, "service/run/flows/scratch_flow.py should remain a thin stage facade"
    for marker in [
        "ScratchSlideBatchMixin",
        "ScratchCompileMixin",
        "self._generate_slide_batch",
        "self._mark_compile_started",
        "self._compile_scratch_run",
    ]:
        assert marker in scratch_text, f"service/run/flows/scratch_flow.py missing {marker}"

    template_text = (flows_dir / "template_flow.py").read_text(encoding="utf-8")
    template_lines = template_text.count("\n") + 1
    assert template_lines <= 120, (
        "service/run/flows/template_flow.py should remain a thin stage facade"
    )
    for marker in [
        "TemplateFlowPreflightMixin",
        "TemplateFlowPrepareMixin",
        "TemplateFlowApplyCompileMixin",
        "TemplateFlowPreviewFinalizeMixin",
        "async def execute",
    ]:
        assert marker in template_text, f"service/run/flows/template_flow.py missing {marker}"

    template_runtime_dir = flows_dir / "template_flow_runtime"
    required_template_runtime_files = {
        "__init__.py",
        "preflight_mixin.py",
        "template_prepare_mixin.py",
        "apply_compile_mixin.py",
        "preview_finalize_mixin.py",
    }
    existing_template_runtime_files = {
        path.name for path in template_runtime_dir.glob("*.py")
    }
    missing_template_runtime = sorted(
        required_template_runtime_files - existing_template_runtime_files
    )
    assert not missing_template_runtime, (
        "service/run/flows/template_flow_runtime missing expected package modules: "
        f"{missing_template_runtime}"
    )


def test_run_engine_module_layout_should_remain_explicit() -> None:
    engines_dir = ROOT / "service" / "run" / "engines"
    required_files = {
        "compile_engine.py",
        "compile_script_bundle_mixin.py",
        "compile_local_runtime_mixin.py",
        "compile_pagevra_runtime_mixin.py",
    }
    existing_files = {path.name for path in engines_dir.glob("*.py")}
    missing = sorted(required_files - existing_files)
    assert not missing, f"service/run/engines missing expected compile modules: {missing}"

    compile_text = (engines_dir / "compile_engine.py").read_text(encoding="utf-8")
    compile_lines = compile_text.count("\n") + 1
    assert compile_lines <= 120, (
        "service/run/engines/compile_engine.py should remain a thin compile facade"
    )
    for marker in [
        "CompileScriptBundleMixin",
        "CompileLocalRuntimeMixin",
        "CompilePagevraRuntimeMixin",
        "self._ensure_compile_script",
        "self._compile_scratch_local",
        "self._compile_scratch_via_pagevra",
    ]:
        assert marker in compile_text, (
            "service/run/engines/compile_engine.py missing " + marker
        )


def test_model_contract_module_layout_should_remain_explicit() -> None:
    models_dir = ROOT / "service" / "models"
    required_files = {
        "contracts.py",
        "contracts_shared.py",
        "contracts_content.py",
        "contracts_ppt.py",
        "contracts_runtime.py",
    }
    existing_files = {path.name for path in models_dir.glob("*.py")}
    missing = sorted(required_files - existing_files)
    assert not missing, f"service/models missing expected contract modules: {missing}"

    forbidden_names = {"helpers.py", "utils.py", "common.py", "misc.py"}
    found_forbidden = sorted(forbidden_names & existing_files)
    assert not found_forbidden, (
        "service/models should not regress into vague dumping-ground modules: "
        + ", ".join(found_forbidden)
    )

    facade_path = models_dir / "contracts.py"
    facade_text = facade_path.read_text(encoding="utf-8")
    facade_lines = facade_text.count("\n") + 1
    assert facade_lines <= 140, "service/models/contracts.py should remain a thin facade"
    for marker in [
        "from .contracts_content import",
        "from .contracts_ppt import",
        "from .contracts_runtime import",
        "from .contracts_shared import",
        "__all__",
    ]:
        assert marker in facade_text, f"service/models/contracts.py missing {marker}"

    content_facade_path = models_dir / "contracts_content.py"
    content_facade_text = content_facade_path.read_text(encoding="utf-8")
    content_facade_lines = content_facade_text.count("\n") + 1
    assert content_facade_lines <= 80, (
        "service/models/contracts_content.py should remain a thin compatibility facade"
    )
    for marker in ["from ..content.contracts import", "__all__"]:
        assert marker in content_facade_text, (
            f"service/models/contracts_content.py missing {marker}"
        )


def test_application_runs_module_layout_should_remain_explicit() -> None:
    application_dir = ROOT / "service" / "application"
    runs_path = application_dir / "runs.py"
    runs_text = runs_path.read_text(encoding="utf-8")
    runs_lines = runs_text.count("\n") + 1
    assert runs_lines <= 40, "service/application/runs.py should remain a thin facade"
    for marker in [
        "RunApplicationRuntimeMixin",
        "RunApplicationDetailMixin",
        "RunApplicationOutlineConfirmMixin",
    ]:
        assert marker in runs_text, f"service/application/runs.py missing {marker}"

    runs_runtime_dir = application_dir / "runs_runtime"
    required_runs_runtime_files = {
        "__init__.py",
        "detail_mixin.py",
        "outline_confirm_mixin.py",
        "runtime_mixin.py",
    }
    existing_runs_runtime_files = {
        path.name for path in runs_runtime_dir.glob("*.py")
    }
    missing_runs_runtime = sorted(
        required_runs_runtime_files - existing_runs_runtime_files
    )
    assert not missing_runs_runtime, (
        "service/application/runs_runtime missing expected runs modules: "
        f"{missing_runs_runtime}"
    )


def test_store_module_layout_should_remain_explicit() -> None:
    infra_dir = ROOT / "service" / "infra"
    required_files = {
        "store.py",
        "store_memory.py",
        "store_postgres.py",
        "store_support.py",
    }
    existing_files = {path.name for path in infra_dir.glob("*.py")}
    missing = sorted(required_files - existing_files)
    assert not missing, f"service/infra missing expected store modules: {missing}"

    store_text = (infra_dir / "store.py").read_text(encoding="utf-8")
    store_lines = store_text.count("\n") + 1
    assert store_lines <= 40, "service/infra/store.py should remain a thin facade"
    for marker in [
        "from .store_memory import RunStore",
        "from .store_postgres import PostgresRunStore",
        "from .store_support import now_iso",
        "__all__",
    ]:
        assert marker in store_text, f"service/infra/store.py missing {marker}"

    postgres_store_text = (infra_dir / "store_postgres.py").read_text(encoding="utf-8")
    postgres_store_lines = postgres_store_text.count("\n") + 1
    assert postgres_store_lines <= 40, (
        "service/infra/store_postgres.py should remain a thin facade"
    )
    for marker in [
        "PostgresStoreRuntimeMixin",
        "PostgresRunRecordsMixin",
        "PostgresTemplateRecordsMixin",
    ]:
        assert marker in postgres_store_text, (
            "service/infra/store_postgres.py missing " + marker
        )

    postgres_store_dir = infra_dir / "postgres_store"
    required_postgres_store_files = {
        "__init__.py",
        "runtime_mixin.py",
        "run_records_mixin.py",
        "template_records_mixin.py",
        "schema_migrations.py",
    }
    existing_postgres_store_files = {
        path.name for path in postgres_store_dir.glob("*.py")
    }
    missing_postgres_store = sorted(
        required_postgres_store_files - existing_postgres_store_files
    )
    assert not missing_postgres_store, (
        "service/infra/postgres_store missing expected package modules: "
        f"{missing_postgres_store}"
    )
