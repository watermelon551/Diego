from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from ...pptd_runtime import PptdRuntimeAdapter
from ...models import (
    EditableSlideScene,
    EventType,
    GenerationMode,
    RunRecord,
    RunStatus,
    SaveSlideSceneRequest,
    SaveSlideSceneResponse,
    SlideArtifact,
)
from ...run.engines.pptd_layout import PptdDeckWriter
from ...run.slide_scene import (
    SlideSceneUnsupportedError,
    apply_scene_operations,
    build_slide_scene,
    scene_to_outline_node,
)
from ...run.slide_scene.pptd_scene import (
    apply_pptd_scene_operations,
    build_pptd_slide_scene,
)
from ...run.slide_preview import build_slide_preview_payload


class SlideSceneApplicationMixin:
    async def get_slide_scene(
        self, run_id: str, slide_no: int
    ) -> EditableSlideScene | None:
        if slide_no < 1:
            raise ValueError("slide_no must be >= 1")
        run = await self.orch.store.get_run(run_id)
        if run is None:
            return None
        if self._run_has_pptd_project(run):
            pptd_path, page_path = self._pptd_project_paths(run, slide_no=slide_no)
            return build_pptd_slide_scene(
                pptd_path=pptd_path,
                page_path=page_path,
                run_id=run_id,
                slide_no=slide_no,
            )
        _, slide_js_path = self._require_slide_js_artifact(
            run=run,
            slide_no=slide_no,
            not_ready_message="slide scene not ready",
        )
        js_code = slide_js_path.read_text(encoding="utf-8")
        parsed = build_slide_scene(js_code=js_code, run_id=run_id, slide_no=slide_no)
        return parsed.scene

    async def save_slide_scene(
        self,
        *,
        run_id: str,
        slide_no: int,
        req: SaveSlideSceneRequest,
    ) -> SaveSlideSceneResponse | None:
        if slide_no < 1:
            raise ValueError("slide_no must be >= 1")
        run = await self.orch.store.get_run(run_id)
        if run is None:
            return None
        if run.status != RunStatus.SUCCEEDED:
            raise ValueError("run must be in SUCCEEDED state")
        if self._run_has_pptd_project(run):
            return await self._save_pptd_slide_scene(
                run=run,
                slide_no=slide_no,
                req=req,
            )
        slide, slide_js_path = self._require_slide_js_artifact(
            run=run,
            slide_no=slide_no,
            not_ready_message="slide scene not ready",
        )
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
            raise SlideSceneUnsupportedError(
                next_scene.scene.readonly_reason or "slide is read-only"
            )
        slide_js_path.write_text(next_js_code, encoding="utf-8")
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
        updated_outline_node = (
            scene_to_outline_node(existing=current_outline_node, scene=next_scene.scene)
            if current_outline_node is not None
            else None
        )
        staged_for_compile = False
        original_slide = slide.model_copy(deep=True)
        original_outline_node = (
            current_outline_node.model_copy(deep=True)
            if current_outline_node is not None
            else None
        )
        if self._scene_save_recompile_reads_run_record(run):
            await self.orch.store.update_run(
                run_id,
                lambda r: self._apply_scene_save_to_run(
                    r,
                    slide_no=slide_no,
                    updated_artifact=updated_artifact,
                    updated_outline_node=updated_outline_node,
                ),
            )
            staged_for_compile = True

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
            if staged_for_compile:
                await self.orch.store.update_run(
                    run_id,
                    lambda r: self._rollback_scene_save_for_compile(
                        r,
                        slide_no=slide_no,
                        original_slide=original_slide,
                        original_outline_node=original_outline_node,
                    ),
                )
            raise

        def apply_save(r: RunRecord) -> None:
            r.status = RunStatus.SUCCEEDED
            r.stage_timings.compile_ms = int(
                (time.perf_counter() - compile_start) * 1000
            )
            r.render_version += 1
            if (
                updated_outline_node is not None
                and r.outline is not None
                and slide_no <= len(r.outline.nodes)
            ):
                r.outline.nodes[slide_no - 1] = updated_outline_node
            for index, existing in enumerate(r.slides):
                if int(getattr(existing, "slide_no", 0) or 0) == slide_no:
                    r.slides[index] = updated_artifact
                    break
            r.compile_js_path = str(
                compile_result.compile_js_path or r.compile_js_path or ""
            )
            r.pptx_path = str(compile_result.pptx_path or r.pptx_path or "")
            if r.input.generation_mode == GenerationMode.TEMPLATE:
                r.compile_requested_provider = None
                r.compile_provider = None
                r.compile_status = "not_requested"
                r.compile_bundle_ready = False
            else:
                r.compile_requested_provider = str(
                    compile_result.requested_provider
                    or getattr(self.orch.settings, "compile_provider", "none")
                )
                r.compile_provider = (
                    str(compile_result.provider)
                    if compile_result.provider not in {None, "none"}
                    else None
                )
                r.compile_status = (
                    "bundle_ready"
                    if bool(getattr(compile_result, "deferred", False))
                    else "succeeded"
                )
                r.compile_bundle_ready = True
            r.compile_fallback_used = bool(compile_result.fallback_used)
            r.compile_error_code = None
            r.compile_error_details = {}

        updated_run = await self.orch.store.update_run(run_id, apply_save)
        await self._publish_slide_generated_preview(
            run_id=run_id,
            slide_no=slide_no,
            status=updated_artifact.status,
            preview=preview,
        )
        await self.orch._publish(
            run_id,
            EventType.COMPILE_COMPLETED,
            {
                "file": str(compile_result.pptx_path or ""),
                "provider": (
                    None
                    if run.input.generation_mode == GenerationMode.TEMPLATE
                    else (compile_result.provider or "")
                ),
                "requested_provider": (
                    "none"
                    if run.input.generation_mode == GenerationMode.TEMPLATE
                    else (
                        compile_result.requested_provider
                        or getattr(self.orch.settings, "compile_provider", "none")
                    )
                ),
                "bundle_ready": False
                if run.input.generation_mode == GenerationMode.TEMPLATE
                else True,
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
            preview=build_slide_preview_payload(
                run_id=run_id,
                slide_no=slide_no,
                preview=preview,
            ),
        )

    async def _save_pptd_slide_scene(
        self,
        *,
        run: RunRecord,
        slide_no: int,
        req: SaveSlideSceneRequest,
    ) -> SaveSlideSceneResponse:
        pptd_path, page_path = self._pptd_project_paths(run, slide_no=slide_no)
        original_page = page_path.read_bytes()
        compile_start = time.perf_counter()
        try:
            next_scene = apply_pptd_scene_operations(
                pptd_path=pptd_path,
                page_path=page_path,
                scene_version=req.scene_version,
                operations=[item.model_dump() for item in req.operations],
                run_id=run.run_id,
                slide_no=slide_no,
            )
            pptx_path = self._recompile_existing_pptd_project(
                pptd_path=pptd_path,
                run=run,
            )
            preview = self._pptd_preview_for_slide(run=run, slide_no=slide_no)
        except Exception:
            page_path.write_bytes(original_page)
            raise

        def apply_save(r: RunRecord) -> None:
            r.status = RunStatus.SUCCEEDED
            r.stage_timings.compile_ms = int(
                (time.perf_counter() - compile_start) * 1000
            )
            r.render_version += 1
            r.compile_js_path = str(pptd_path)
            r.pptx_path = str(pptx_path)
            r.compile_requested_provider = "pptd"
            r.compile_provider = "pptd"
            r.compile_status = "succeeded"
            r.compile_bundle_ready = True
            r.compile_fallback_used = False
            r.compile_error_code = None
            r.compile_error_details = {}

        updated_run = await self.orch.store.update_run(run.run_id, apply_save)
        await self._publish_slide_generated_preview(
            run_id=run.run_id,
            slide_no=slide_no,
            status="pptd_scene_saved",
            preview=preview,
        )
        await self.orch._publish(
            run.run_id,
            EventType.COMPILE_COMPLETED,
            {
                "file": str(pptx_path),
                "provider": "pptd",
                "requested_provider": "pptd",
                "bundle_ready": True,
                "deferred": False,
                "fallback_used": False,
                "reason": "pptd_scene_save",
            },
        )
        return SaveSlideSceneResponse(
            run_id=run.run_id,
            slide_id=next_scene.slide_id,
            slide_index=next_scene.slide_index,
            slide_no=slide_no,
            render_version=int(getattr(updated_run, "render_version", 0) or 0),
            status="ready",
            scene=next_scene,
            preview=build_slide_preview_payload(
                run_id=run.run_id,
                slide_no=slide_no,
                preview=preview,
            ),
        )

    def _run_has_pptd_project(self, run: RunRecord) -> bool:
        artifact_dir = Path(str(getattr(run, "artifact_dir", "") or ""))
        pptd_path = artifact_dir / "slides" / "pptd" / "presentation.pptd"
        providers = {
            str(getattr(run, "compile_provider", "") or "").lower(),
            str(getattr(run, "compile_requested_provider", "") or "").lower(),
        }
        compile_path = Path(str(getattr(run, "compile_js_path", "") or ""))
        return (
            pptd_path.is_file()
            or "pptd" in providers
            or compile_path.suffix == ".pptd"
        )

    def _pptd_project_paths(self, run: RunRecord, *, slide_no: int) -> tuple[Path, Path]:
        artifact_dir = Path(str(getattr(run, "artifact_dir", "") or ""))
        pptd_path = artifact_dir / "slides" / "pptd" / "presentation.pptd"
        if not pptd_path.is_file():
            raise FileNotFoundError(f"pptd project is missing: {pptd_path}")
        manifest = PptdDeckWriter().preview_manifest_from_project(pptd_path=pptd_path)
        page_count = int(manifest.get("page_count") or 0)
        if slide_no > page_count:
            raise FileNotFoundError(f"pptd page is missing for slide {slide_no}")
        page_path = self._pptd_page_path_from_deck(pptd_path, slide_no=slide_no)
        if not page_path.is_file():
            raise FileNotFoundError(f"pptd page is missing: {page_path}")
        return pptd_path, page_path

    def _pptd_page_path_from_deck(self, pptd_path: Path, *, slide_no: int) -> Path:
        import yaml

        deck = yaml.safe_load(pptd_path.read_text(encoding="utf-8"))
        pages = deck.get("pages") if isinstance(deck, dict) else None
        if not isinstance(pages, list) or slide_no > len(pages):
            raise FileNotFoundError(f"pptd page is missing for slide {slide_no}")
        page_ref = str(pages[slide_no - 1] or "").strip()
        if not page_ref:
            raise FileNotFoundError(f"pptd page is missing for slide {slide_no}")
        return pptd_path.parent / page_ref

    def _pptd_preview_for_slide(self, *, run: RunRecord, slide_no: int) -> dict[str, Any]:
        pptd_path, _ = self._pptd_project_paths(run, slide_no=slide_no)
        manifest = PptdDeckWriter().preview_manifest_from_project(pptd_path=pptd_path)
        pages = manifest.get("pages") if isinstance(manifest.get("pages"), list) else []
        page = pages[slide_no - 1] if slide_no <= len(pages) else {}
        return page if isinstance(page, dict) else {}

    def _recompile_existing_pptd_project(self, *, pptd_path: Path, run: RunRecord) -> Path:
        pptx_path = Path(str(getattr(run, "artifact_dir", "") or "")) / "slides" / "output" / "presentation.pptx"
        pptx_path.parent.mkdir(parents=True, exist_ok=True)
        adapter = PptdRuntimeAdapter(
            skill_dir=Path(str(getattr(self.orch.settings, "pptd_skill_dir", "") or "")),
            runner_mode=str(
                getattr(self.orch.settings, "pptd_runner_mode", "") or "docker"
            ),
            runner_image=str(
                getattr(self.orch.settings, "pptd_runner_image", "")
                or "debian:bookworm-slim"
            ),
            platform=str(
                getattr(self.orch.settings, "pptd_runner_platform", "")
                or "linux/amd64"
            ),
            timeout_sec=float(
                getattr(self.orch.settings, "pptd_runner_timeout_sec", 120.0)
                or 120.0
            ),
            run_subprocess=self.orch.subprocess.run,
        )
        check = adapter.check(pptd_path)
        if not check.ok:
            raise RuntimeError(check.reason or "pptd_check_failed")
        convert = adapter.convert(pptd_path, output_path=pptx_path)
        if not convert.ok:
            raise RuntimeError(convert.reason or "pptd_convert_failed")
        return pptx_path

    async def _recompile_run_after_scene_save(self, *, run: RunRecord) -> Any:
        return await self.orch._recompile_run_after_scene_save(run=run)

    async def _publish_slide_generated_preview(
        self,
        *,
        run_id: str,
        slide_no: int,
        status: str,
        preview: dict[str, Any],
    ) -> None:
        return await self.orch._publish_slide_generated_preview(
            run_id=run_id,
            slide_no=slide_no,
            status=status,
            preview=preview,
        )

    def _scene_save_recompile_reads_run_record(self, run: RunRecord) -> bool:
        if run.input.generation_mode == GenerationMode.TEMPLATE:
            return False
        providers = {
            str(getattr(self.orch.settings, "compile_provider", "") or "").lower(),
            str(getattr(run, "compile_provider", "") or "").lower(),
            str(getattr(run, "compile_requested_provider", "") or "").lower(),
        }
        return "pptd" in providers

    def _apply_scene_save_to_run(
        self,
        run: RunRecord,
        *,
        slide_no: int,
        updated_artifact: SlideArtifact,
        updated_outline_node: Any,
    ) -> None:
        if (
            updated_outline_node is not None
            and run.outline is not None
            and slide_no <= len(run.outline.nodes)
        ):
            run.outline.nodes[slide_no - 1] = updated_outline_node
        for index, existing in enumerate(run.slides):
            if int(getattr(existing, "slide_no", 0) or 0) == slide_no:
                run.slides[index] = updated_artifact
                break

    def _rollback_scene_save_for_compile(
        self,
        run: RunRecord,
        *,
        slide_no: int,
        original_slide: SlideArtifact,
        original_outline_node: Any,
    ) -> None:
        if (
            original_outline_node is not None
            and run.outline is not None
            and slide_no <= len(run.outline.nodes)
        ):
            run.outline.nodes[slide_no - 1] = original_outline_node
        for index, existing in enumerate(run.slides):
            if int(getattr(existing, "slide_no", 0) or 0) == slide_no:
                run.slides[index] = original_slide
                break
