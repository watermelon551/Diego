from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..models import (
    EditableSlideScene,
    EventType,
    GenerationMode,
    OutlineNode,
    RegenerateSlideRequest,
    RunRecord,
    RunStatus,
    RunSummaryResponse,
    SaveSlideSceneRequest,
    SaveSlideSceneResponse,
    SlideArtifact,
)
from ..run.slide_scene import (
    SlideSceneUnsupportedError,
    apply_scene_operations,
    build_slide_scene,
    scene_outline_values,
)


class SlideApplicationService:
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator

    async def get_slide_preview(self, run_id: str, slide_no: int) -> dict[str, Any] | None:
        if slide_no < 1:
            raise ValueError("slide_no must be >= 1")
        run = await self.orch.store.get_run(run_id)
        if run is None:
            return None
        slide, slide_js_path = self._require_slide_js_artifact(run=run, slide_no=slide_no, not_ready_message="slide preview not ready")
        preview = await self.render_slide_preview_or_fallback(
            run_id=run_id,
            slide_no=slide_no,
            slide_js_path=slide_js_path,
            theme=self.orch._resolve_run_design(run).theme,
        )
        return self._build_slide_preview_payload(run_id=run_id, slide_no=slide_no, preview=preview)

    async def get_slide_scene(self, run_id: str, slide_no: int) -> EditableSlideScene | None:
        if slide_no < 1:
            raise ValueError("slide_no must be >= 1")
        run = await self.orch.store.get_run(run_id)
        if run is None:
            return None
        _, slide_js_path = self._require_slide_js_artifact(run=run, slide_no=slide_no, not_ready_message="slide scene not ready")
        js_code = slide_js_path.read_text(encoding="utf-8")
        parsed = build_slide_scene(js_code=js_code, run_id=run_id, slide_no=slide_no)
        return parsed.scene

    async def get_slide_asset_path(self, run_id: str, slide_no: int, asset_path: str) -> Path | None:
        if slide_no < 1:
            raise ValueError("slide_no must be >= 1")
        requested_path = str(asset_path or "").strip()
        if not requested_path:
            raise ValueError("asset path is required")
        if requested_path.startswith(("http://", "https://", "data:", "blob:")):
            raise ValueError("asset path must reference a local slide asset")
        run = await self.orch.store.get_run(run_id)
        if run is None:
            return None
        _, slide_js_path = self._require_slide_js_artifact(run=run, slide_no=slide_no, not_ready_message="slide asset not ready")
        candidate = Path(requested_path)
        if not candidate.is_absolute():
            candidate = (slide_js_path.parent / candidate).resolve()
        else:
            candidate = candidate.resolve()
        artifact_root = Path(str(run.artifact_dir or "").strip()).resolve()
        try:
            candidate.relative_to(artifact_root)
        except ValueError as exc:
            raise ValueError("asset path escapes run artifact root") from exc
        if not candidate.exists() or not candidate.is_file():
            raise FileNotFoundError("slide asset file missing")
        return candidate

    async def save_slide_scene(self, *, run_id: str, slide_no: int, req: SaveSlideSceneRequest) -> SaveSlideSceneResponse | None:
        if slide_no < 1:
            raise ValueError("slide_no must be >= 1")
        run = await self.orch.store.get_run(run_id)
        if run is None:
            return None
        if run.status != RunStatus.SUCCEEDED:
            raise ValueError("run must be in SUCCEEDED state")
        slide, slide_js_path = self._require_slide_js_artifact(run=run, slide_no=slide_no, not_ready_message="slide scene not ready")
        js_code = slide_js_path.read_text(encoding="utf-8")
        parsed_scene = build_slide_scene(js_code=js_code, run_id=run_id, slide_no=slide_no)
        next_js_code, next_scene = apply_scene_operations(
            js_code=js_code,
            parsed_scene=parsed_scene,
            scene_version=req.scene_version,
            operations=[item.model_dump() for item in req.operations],
            run_id=run_id,
            slide_no=slide_no,
        )
        if next_scene.scene.readonly:
            raise SlideSceneUnsupportedError(next_scene.scene.readonly_reason or "slide is read-only")
        slide_js_path.write_text(next_js_code, encoding="utf-8")
        design = self.orch._resolve_run_design(run)
        compile_start = time.perf_counter()
        try:
            preview = await self.render_slide_preview_or_fallback(
                run_id=run_id,
                slide_no=slide_no,
                slide_js_path=slide_js_path,
                theme=design.theme,
            )
            compile_result = await self._recompile_run_after_scene_save(run=run)
        except Exception:
            slide_js_path.write_text(js_code, encoding="utf-8")
            raise
        updated_artifact = SlideArtifact(
            slide_no=slide.slide_no,
            js_path=str(slide_js_path),
            js_code=next_js_code,
            status=str(getattr(slide, "status", "ok") or "ok"),
            citations=list(getattr(slide, "citations", []) or []),
        )
        current_outline_node = (
            run.outline.nodes[slide_no - 1]
            if run.outline is not None and slide_no <= len(run.outline.nodes)
            else None
        )
        updated_outline_node = self._scene_to_outline_node(existing=current_outline_node, scene=next_scene.scene) if current_outline_node is not None else None

        def apply_save(r: RunRecord) -> None:
            r.status = RunStatus.SUCCEEDED
            r.stage_timings.compile_ms = int((time.perf_counter() - compile_start) * 1000)
            r.render_version += 1
            if updated_outline_node is not None and r.outline is not None and slide_no <= len(r.outline.nodes):
                r.outline.nodes[slide_no - 1] = updated_outline_node
            for index, existing in enumerate(r.slides):
                if int(getattr(existing, "slide_no", 0) or 0) == slide_no:
                    r.slides[index] = updated_artifact
                    break
            r.compile_js_path = str(compile_result.compile_js_path or r.compile_js_path or "")
            r.pptx_path = str(compile_result.pptx_path or r.pptx_path or "")
            r.compile_requested_provider = str(
                compile_result.requested_provider
                or getattr(self.orch.settings, "compile_provider", "none")
            )
            r.compile_provider = (
                str(compile_result.provider)
                if compile_result.provider not in {None, "none"}
                else None
            )
            r.compile_status = "bundle_ready" if bool(getattr(compile_result, "deferred", False)) else "succeeded"
            r.compile_bundle_ready = True
            r.compile_fallback_used = bool(compile_result.fallback_used)
            r.compile_error_code = None
            r.compile_error_details = {}

        updated_run = await self.orch.store.update_run(run_id, apply_save)
        await self._publish_slide_generated_preview(run_id=run_id, slide_no=slide_no, status=updated_artifact.status, preview=preview)
        await self.orch._publish(
            run_id,
            EventType.COMPILE_COMPLETED,
            {
                "file": str(compile_result.pptx_path or ""),
                "provider": compile_result.provider or "",
                "requested_provider": compile_result.requested_provider
                or getattr(self.orch.settings, "compile_provider", "none"),
                "bundle_ready": True,
                "deferred": bool(getattr(compile_result, "deferred", False)),
                "fallback_used": bool(compile_result.fallback_used),
                "reason": "scene_save",
            },
        )
        return SaveSlideSceneResponse(
            run_id=run_id,
            slide_id=next_scene.scene.slide_id,
            slide_index=next_scene.scene.slide_index,
            slide_no=slide_no,
            render_version=int(getattr(updated_run, "render_version", 0) or 0),
            status="ready",
            scene=next_scene.scene,
            preview=self._build_slide_preview_payload(run_id=run_id, slide_no=slide_no, preview=preview),
        )

    async def regenerate_single_slide(
        self,
        *,
        run_id: str,
        slide_no: int,
        instruction: str,
        preserve_style: bool,
        expected_render_version: int | None = None,
    ) -> RunSummaryResponse | None:
        if slide_no < 1:
            raise ValueError("slide_no must be >= 1")
        run = await self.orch.store.get_run(run_id)
        if run is None:
            return None
        if run.status != RunStatus.SUCCEEDED:
            raise ValueError("run must be in SUCCEEDED state")
        if expected_render_version is not None and run.render_version != expected_render_version:
            raise ValueError(
                "render version conflict: "
                f"expected {expected_render_version}, current {run.render_version}"
            )
        if run.outline is None:
            raise ValueError("run outline missing")
        if slide_no > len(run.outline.nodes):
            raise ValueError("slide_no out of range")
        if not any(int(getattr(item, "slide_no", 0) or 0) == slide_no for item in run.slides):
            raise ValueError("slide artifact missing")

        await self.orch.store.update_run(run_id, lambda r: setattr(r, "status", RunStatus.SLIDES_GENERATING))
        self.orch._spawn(
            self._regenerate_single_slide_task(
                run_id=run_id,
                slide_no=slide_no,
                instruction=instruction.strip(),
                preserve_style=preserve_style,
            )
        )
        return RunSummaryResponse(run_id=run.run_id, trace_id=run.trace_id, status=RunStatus.SLIDES_GENERATING)

    async def render_slide_preview_or_fallback(
        self,
        *,
        run_id: str,
        slide_no: int,
        slide_js_path: Path,
        theme: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.orch.render_slide_preview_or_fallback(
            run_id=run_id,
            slide_no=slide_no,
            slide_js_path=slide_js_path,
            theme=theme,
        )

    def _require_slide_js_artifact(self, *, run: RunRecord, slide_no: int, not_ready_message: str) -> tuple[SlideArtifact, Path]:
        return self.orch._require_slide_js_artifact(run=run, slide_no=slide_no, not_ready_message=not_ready_message)

    def _build_slide_preview_payload(self, *, run_id: str, slide_no: int, preview: dict[str, Any]) -> dict[str, Any]:
        return self.orch._build_slide_preview_payload(run_id=run_id, slide_no=slide_no, preview=preview)

    def _scene_to_outline_node(self, *, existing: OutlineNode | None, scene: EditableSlideScene) -> OutlineNode | None:
        if existing is None:
            return None
        title, bullets = scene_outline_values(scene)
        return OutlineNode(
            title=title or existing.title,
            bullets=bullets if bullets is not None else list(existing.bullets),
            page_type=existing.page_type,
            layout_hint=existing.layout_hint,
        )

    async def _recompile_run_after_scene_save(self, *, run: RunRecord) -> Any:
        if run.input.generation_mode == GenerationMode.TEMPLATE:
            (
                _,
                _,
                _,
                _,
                _,
                template_slides_dir,
                template_compile_js,
                template_compiled_pptx,
            ) = self.orch.template_engine.template_work_paths(Path(run.artifact_dir))
            compiled = await self.orch.template_engine.compile_template_js(template_slides_dir=template_slides_dir)
            if not compiled:
                raise RuntimeError("template scene save compile failed")
            return self.orch.compile_engine.result_type(
                ok=True,
                compile_js_path=template_compile_js,
                pptx_path=template_compiled_pptx,
                return_code=0,
                reason="",
                provider="template_js",
                fallback_used=False,
            )
        compile_result = await self.orch.compile_engine.compile_scratch_run(
            run_id=run.run_id,
            slides_dir=Path(run.artifact_dir) / "slides",
            slide_count=len(run.slides),
            theme=self.orch._resolve_run_design(run).theme,
        )
        if not compile_result.ok:
            raise RuntimeError(str(compile_result.reason or "scene save recompile failed"))
        return compile_result

    async def _regenerate_single_slide_task(self, *, run_id: str, slide_no: int, instruction: str, preserve_style: bool) -> None:
        return await self.orch._regenerate_single_slide_task(
            run_id=run_id,
            slide_no=slide_no,
            instruction=instruction,
            preserve_style=preserve_style,
        )

    async def _publish_slide_generated_preview(self, *, run_id: str, slide_no: int, status: str, preview: dict[str, Any]) -> None:
        return await self.orch._publish_slide_generated_preview(
            run_id=run_id,
            slide_no=slide_no,
            status=status,
            preview=preview,
        )
