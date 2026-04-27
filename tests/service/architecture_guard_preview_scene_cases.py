from __future__ import annotations

from tests.service.architecture_guard_support import ROOT


def test_preview_and_scene_helpers_should_not_drift_back_into_orchestrator() -> None:
    orchestrator_text = (ROOT / "service" / "run" / "orchestrator.py").read_text(
        encoding="utf-8"
    )
    preview_runtime_text = (
        ROOT / "service" / "run" / "preview_runtime_mixin.py"
    ).read_text(encoding="utf-8")
    slide_preview_text = (ROOT / "service" / "run" / "slide_preview.py").read_text(
        encoding="utf-8"
    )
    preview_qa_text = (ROOT / "service" / "run" / "preview_qa.py").read_text(
        encoding="utf-8"
    )
    preview_quality_runtime_text = (
        ROOT / "service" / "run" / "preview_quality" / "runtime_mixin.py"
    ).read_text(encoding="utf-8")
    preview_quality_qa_text = (
        ROOT / "service" / "run" / "preview_quality" / "preview_qa.py"
    ).read_text(encoding="utf-8")
    preview_runtime_init_text = (
        ROOT / "service" / "run" / "preview_quality" / "preview_runtime" / "__init__.py"
    ).read_text(encoding="utf-8")
    preview_runtime_markitdown_text = (
        ROOT / "service" / "run" / "preview_quality" / "preview_runtime" / "markitdown_runtime.py"
    ).read_text(encoding="utf-8")
    preview_runtime_failure_text = (
        ROOT / "service" / "run" / "preview_quality" / "preview_runtime" / "process_failure.py"
    ).read_text(encoding="utf-8")
    preview_runtime_execution_text = (
        ROOT / "service" / "run" / "preview_quality" / "preview_runtime" / "qa_execution.py"
    ).read_text(encoding="utf-8")
    slide_preview_runtime_init_text = (
        ROOT / "service" / "run" / "slide_preview_runtime" / "__init__.py"
    ).read_text(encoding="utf-8")
    slide_preview_runtime_payloads_text = (
        ROOT / "service" / "run" / "slide_preview_runtime" / "payloads.py"
    ).read_text(encoding="utf-8")
    slide_preview_runtime_bundle_text = (
        ROOT / "service" / "run" / "slide_preview_runtime" / "bundle.py"
    ).read_text(encoding="utf-8")
    slide_preview_runtime_pagevra_text = (
        ROOT / "service" / "run" / "slide_preview_runtime" / "pagevra_runtime.py"
    ).read_text(encoding="utf-8")
    slide_scene_text = (ROOT / "service" / "run" / "slide_scene" / "__init__.py").read_text(
        encoding="utf-8"
    )
    app_slides_text = (ROOT / "service" / "application" / "slides.py").read_text(
        encoding="utf-8"
    )
    app_preview_text = (
        ROOT / "service" / "application" / "slide_preview_application_mixin.py"
    ).read_text(encoding="utf-8")
    app_scene_text = (
        ROOT / "service" / "application" / "slide_scene_application_mixin.py"
    ).read_text(encoding="utf-8")
    app_preview_runtime_text = (
        ROOT / "service" / "application" / "slides_runtime" / "preview_mixin.py"
    ).read_text(encoding="utf-8")
    app_scene_runtime_text = (
        ROOT / "service" / "application" / "slides_runtime" / "scene_mixin.py"
    ).read_text(encoding="utf-8")

    assert "def build_slide_preview_payload" in slide_preview_text
    assert "def build_placeholder_preview" in slide_preview_text
    assert "def build_preview_runner_js" in slide_preview_text
    assert "render_slide_via_pagevra_runtime" in slide_preview_text
    assert "build_slide_preview_payload" in slide_preview_runtime_init_text
    assert "build_single_slide_compile_bundle" in slide_preview_runtime_init_text
    assert "def build_slide_preview_payload" in slide_preview_runtime_payloads_text
    assert "def build_placeholder_preview" in slide_preview_runtime_payloads_text
    assert "def build_single_slide_compile_bundle" in slide_preview_runtime_bundle_text
    assert "def render_slide_via_pagevra_runtime" in slide_preview_runtime_pagevra_text
    assert "def markitdown_check" in preview_runtime_markitdown_text
    assert "def markitdown_extract" in preview_runtime_markitdown_text
    assert "def summarize_process_failure" in preview_runtime_failure_text
    assert "def run_slide_preview_qa_with_text" in preview_runtime_execution_text
    assert "from .preview_runtime import (" in preview_quality_qa_text
    assert "from .markitdown_runtime import markitdown_check, markitdown_extract" in preview_runtime_init_text
    assert "from .preview_quality.preview_qa import (" in preview_qa_text
    assert "from .preview_quality.runtime_mixin import RunPreviewRuntimeMixin" in preview_runtime_text
    assert "def scene_to_outline_node" in slide_scene_text
    assert "def _build_slide_preview_payload" not in orchestrator_text
    assert "def _build_preview_runner_js" not in orchestrator_text
    assert "def _scene_to_outline_node" not in orchestrator_text
    for wrapper in [
        "def _markitdown_check",
        "def _markitdown_extract",
        "def _summarize_process_failure",
        "def _run_slide_preview_qa_with_text",
    ]:
        assert (
            wrapper in orchestrator_text
            or wrapper in preview_runtime_text
            or wrapper in preview_quality_runtime_text
        ), (
            "thin preview/runtime wrappers may remain in orchestrator or explicit run-owned mixins, "
            f"but {wrapper} should delegate into service/run preview modules"
        )
    assert "SlidePreviewApplicationMixin" in app_slides_text
    assert "SlideSceneApplicationMixin" in app_slides_text
    assert "SlidePreviewApplicationMixin" in app_preview_text
    assert "SlideSceneApplicationMixin" in app_scene_text
    assert "build_slide_preview_payload" in app_preview_runtime_text
    assert "scene_to_outline_node" in app_scene_runtime_text


def test_slide_scene_module_layout_should_remain_explicit() -> None:
    run_dir = ROOT / "service" / "run"
    slide_preview_text = (run_dir / "slide_preview.py").read_text(encoding="utf-8")
    required_files = {
        "background_runtime_mixin.py",
        "preview_runtime_mixin.py",
        "preview_qa.py",
        "qa_preview_sampling.py",
        "qa_reporting.py",
        "qa_static_checks.py",
        "qa_mode_execution.py",
        "qa_runtime.py",
    }
    existing_files = {path.name for path in run_dir.glob("*.py")}
    missing = sorted(required_files - existing_files)
    assert not missing, f"service/run missing expected slide scene modules: {missing}"

    preview_quality_dir = run_dir / "preview_quality"
    required_preview_quality_files = {
        "__init__.py",
        "runtime_mixin.py",
        "preview_qa.py",
        "sampling.py",
        "reporting.py",
        "static_checks.py",
        "mode_execution.py",
        "runtime.py",
    }
    existing_preview_quality_files = {
        path.name for path in preview_quality_dir.glob("*.py")
    }
    missing_preview_quality = sorted(
        required_preview_quality_files - existing_preview_quality_files
    )
    assert not missing_preview_quality, (
        "service/run/preview_quality missing expected package modules: "
        f"{missing_preview_quality}"
    )

    preview_runtime_dir = preview_quality_dir / "preview_runtime"
    required_preview_runtime_files = {
        "__init__.py",
        "markitdown_runtime.py",
        "process_failure.py",
        "qa_execution.py",
    }
    existing_preview_runtime_files = {
        path.name for path in preview_runtime_dir.glob("*.py")
    }
    missing_preview_runtime = sorted(
        required_preview_runtime_files - existing_preview_runtime_files
    )
    assert not missing_preview_runtime, (
        "service/run/preview_quality/preview_runtime missing expected package modules: "
        f"{missing_preview_runtime}"
    )

    preview_qa_facade_text = (preview_quality_dir / "preview_qa.py").read_text(
        encoding="utf-8"
    )
    assert "from .preview_runtime import (" in preview_qa_facade_text

    slide_preview_runtime_dir = run_dir / "slide_preview_runtime"
    required_slide_preview_runtime_files = {
        "__init__.py",
        "payloads.py",
        "bundle.py",
        "pagevra_runtime.py",
    }
    existing_slide_preview_runtime_files = {
        path.name for path in slide_preview_runtime_dir.glob("*.py")
    }
    missing_slide_preview_runtime = sorted(
        required_slide_preview_runtime_files - existing_slide_preview_runtime_files
    )
    assert not missing_slide_preview_runtime, (
        "service/run/slide_preview_runtime missing expected package modules: "
        f"{missing_slide_preview_runtime}"
    )

    slide_preview_lines = slide_preview_text.count("\n") + 1
    assert slide_preview_lines <= 90, "service/run/slide_preview.py should remain a thin facade"

    slide_scene_dir = run_dir / "slide_scene"
    required_scene_files = {
        "__init__.py",
        "types.py",
        "js_parsing.py",
        "bindings.py",
        "config_bindings.py",
        "variable_bindings.py",
        "text_bindings.py",
        "image_bindings.py",
    }
    existing_scene_files = {path.name for path in slide_scene_dir.glob("*.py")}
    missing_scene = sorted(required_scene_files - existing_scene_files)
    assert not missing_scene, (
        "service/run/slide_scene missing expected package modules: "
        f"{missing_scene}"
    )

    scene_parsing_dir = slide_scene_dir / "parsing"
    required_scene_parsing_files = {
        "__init__.py",
        "scanning.py",
        "values.py",
    }
    existing_scene_parsing_files = {
        path.name for path in scene_parsing_dir.glob("*.py")
    }
    missing_scene_parsing = sorted(
        required_scene_parsing_files - existing_scene_parsing_files
    )
    assert not missing_scene_parsing, (
        "service/run/slide_scene/parsing missing expected package modules: "
        f"{missing_scene_parsing}"
    )

    scene_js_parsing_text = (slide_scene_dir / "js_parsing.py").read_text(
        encoding="utf-8"
    )
    scene_js_parsing_lines = scene_js_parsing_text.count("\n") + 1
    assert scene_js_parsing_lines <= 40, (
        "service/run/slide_scene/js_parsing.py should remain a thin facade"
    )

    application_dir = ROOT / "service" / "application"
    required_application_files = {
        "slides.py",
        "slide_preview_application_mixin.py",
        "slide_scene_application_mixin.py",
        "slide_regeneration_application_mixin.py",
    }
    existing_application_files = {path.name for path in application_dir.glob("*.py")}
    missing_application = sorted(required_application_files - existing_application_files)
    assert not missing_application, (
        "service/application missing expected slide application modules: "
        f"{missing_application}"
    )

    slides_runtime_dir = application_dir / "slides_runtime"
    required_slides_runtime_files = {
        "__init__.py",
        "preview_mixin.py",
        "scene_mixin.py",
        "regeneration_mixin.py",
    }
    existing_slides_runtime_files = {
        path.name for path in slides_runtime_dir.glob("*.py")
    }
    missing_slides_runtime = sorted(
        required_slides_runtime_files - existing_slides_runtime_files
    )
    assert not missing_slides_runtime, (
        "service/application/slides_runtime missing expected package modules: "
        f"{missing_slides_runtime}"
    )

    for file_name, marker in {
        "slide_preview_application_mixin.py": "from .slides_runtime.preview_mixin import SlidePreviewApplicationMixin",
        "slide_scene_application_mixin.py": "from .slides_runtime.scene_mixin import SlideSceneApplicationMixin",
        "slide_regeneration_application_mixin.py": "from .slides_runtime.regeneration_mixin import SlideRegenerationApplicationMixin",
    }.items():
        facade_text = (application_dir / file_name).read_text(encoding="utf-8")
        facade_lines = facade_text.count("\n") + 1
        assert facade_lines <= 20, (
            f"service/application/{file_name} should remain a thin facade"
        )
        assert marker in facade_text, (
            f"service/application/{file_name} missing {marker}"
        )
