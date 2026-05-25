from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

from service.models import (
    CreateRunRequest,
    GenerationMode,
    OutlineDocument,
    OutlineNode,
    RunRecord,
    RunStatus,
    SlideArtifact,
)
from service.run.engines import CompileEngine

from tests.support.runtime_helpers import make_settings


class _Store:
    def __init__(self, run: RunRecord) -> None:
        self.run = run

    async def get_run(self, run_id: str) -> RunRecord | None:
        return self.run if run_id == self.run.run_id else None


def test_compile_provider_pptd_builds_checked_project_and_pptx(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        command = " ".join(args)
        if "convert.sh" in command:
            output = tmp_path / "artifacts" / "r-pptd" / "slides" / "output" / "presentation.pptx"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"pptx")
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="Created", stderr="")
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="Checking presentation.pptd\nSummary: 0 errors, 0 warnings",
            stderr="",
        )

    run = RunRecord(
        run_id="r-pptd",
        trace_id="t-pptd",
        status=RunStatus.COMPILING,
        input=CreateRunRequest(
            topic="Data Link Layer",
            project_id="p-pptd",
            target_slide_count=2,
            generation_mode=GenerationMode.SCRATCH,
        ),
        artifact_dir=str(tmp_path / "artifacts" / "r-pptd"),
        outline=OutlineDocument(
            version=1,
            summary="network courseware",
            nodes=[
                OutlineNode(title="Data Link Layer", bullets=["Framing", "Error control"]),
                OutlineNode(title="Sliding Window", bullets=["ACK", "Retransmission"]),
            ],
        ),
        slides=[
            SlideArtifact(slide_no=1, js_code="", status="ready"),
            SlideArtifact(slide_no=2, js_code="", status="ready"),
        ],
    )
    runtime = SimpleNamespace(
        settings=make_settings(
            compile_provider="pptd",
            pptd_skill_dir=str(tmp_path / "pptx-skill"),
            pptd_runner_image="debian:bookworm-slim",
            pptd_runner_timeout_sec=30.0,
        ),
        store=_Store(run),
        subprocess=SimpleNamespace(run=fake_run),
    )
    engine = CompileEngine(runtime)
    slides_dir = tmp_path / "artifacts" / "r-pptd" / "slides"

    result = asyncio.run(
        engine.compile_scratch_run(
            run_id="r-pptd",
            slides_dir=slides_dir,
            slide_count=2,
            theme={"primary": "#2563eb"},
        )
    )

    assert result.ok is True
    assert result.provider == "pptd"
    assert result.requested_provider == "pptd"
    assert result.pptx_path == slides_dir / "output" / "presentation.pptx"
    assert (slides_dir / "pptd" / "presentation.pptd").is_file()
    assert (slides_dir / "pptd" / "pages" / "slide-01.page").is_file()
    assert "Data Link Layer" in (slides_dir / "pptd" / "pages" / "slide-01.page").read_text(
        encoding="utf-8"
    )
    assert len(calls) == 2
    assert "check.sh" in " ".join(calls[0])
    assert "convert.sh" in " ".join(calls[1])


def test_compile_provider_pptd_builds_pagevra_bundle_without_legacy_scene_entrypoint(
    tmp_path: Path,
) -> None:
    def fake_run(args, **_kwargs):
        if "convert.sh" in " ".join(args):
            output = tmp_path / "artifacts" / "r-pptd" / "slides" / "output" / "presentation.pptx"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"pptx")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    run = RunRecord(
        run_id="r-pptd",
        trace_id="t-pptd",
        status=RunStatus.COMPILING,
        input=CreateRunRequest(
            topic="Data Link Layer",
            project_id="p-pptd",
            target_slide_count=1,
            generation_mode=GenerationMode.SCRATCH,
        ),
        artifact_dir=str(tmp_path / "artifacts" / "r-pptd"),
        outline=OutlineDocument(
            version=1,
            summary="network courseware",
            nodes=[OutlineNode(title="Data Link Layer", bullets=["Framing"])],
        ),
        slides=[SlideArtifact(slide_no=1, js_code="", status="ready")],
    )
    runtime = SimpleNamespace(
        settings=make_settings(
            compile_provider="pptd",
            pptd_skill_dir=str(tmp_path / "pptx-skill"),
            pptd_runner_timeout_sec=30.0,
        ),
        store=_Store(run),
        subprocess=SimpleNamespace(run=fake_run),
    )
    engine = CompileEngine(runtime)
    slides_dir = tmp_path / "artifacts" / "r-pptd" / "slides"

    asyncio.run(
        engine.compile_scratch_run(
            run_id="r-pptd",
            slides_dir=slides_dir,
            slide_count=1,
            theme={"primary": "#2563eb"},
        )
    )
    bundle = asyncio.run(engine.build_compile_bundle("r-pptd"))

    assert bundle["provider"] == "diego"
    assert bundle["mode"] == "scratch"
    assert bundle["entrypoint"] == "slides/compile_pptd_bundle.js"
    assert bundle["compile_options"]["command"] == ["node", "compile_pptd_bundle.js"]
    assert bundle["compile_options"]["preview_manifest_path"] == "slides/output/preview.json"
    assert bundle["compile_options"]["result_manifest_path"] == "slides/output/result.json"
    assert bundle["compile_options"]["output_artifacts"] == [
        {
            "kind": "pptx",
            "path": "slides/output/presentation.pptx",
            "media_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
    ]
    paths = {item["path"] for item in bundle["files"] + bundle["assets"]}
    assert "slides/compile.js" not in paths
    assert "slides/compile_pptd_bundle.js" in paths
    assert "slides/pptd/presentation.pptd" in paths
    assert "slides/pptd/pages/slide-01.page" in paths
    assert "slides/input/presentation.pptx" in paths
