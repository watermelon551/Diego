from __future__ import annotations

from pathlib import Path
import time
from typing import Any

import yaml

from service.pptd_runtime import PptdRuntimeAdapter

from ...models import EventType, OutlineNode, RunRecord, RunStatus, SlideArtifact
from ...run.engines.pptd_layout import PptdDeckWriter


class SlideRegenerationPptdMixin:
    async def regenerate_single_pptd_slide(
        self,
        *,
        run_id: str,
        slide_no: int,
        instruction: str,
        preserve_style: bool,
        run: RunRecord,
    ) -> None:
        if not self._run_has_pptd_project(run):
            raise FileNotFoundError("pptd project is missing")
        if run.outline is None or slide_no > len(run.outline.nodes):
            raise ValueError("run outline missing")

        pptd_path = self._pptd_project_path(run)
        original_project = self._snapshot_pptd_project(pptd_path)
        compile_start = time.perf_counter()
        try:
            next_nodes = list(run.outline.nodes)
            current_node = next_nodes[slide_no - 1]
            next_nodes[slide_no - 1] = self._regenerated_pptd_outline_node(
                node=current_node,
                instruction=instruction,
                preserve_style=preserve_style,
            )
            self._write_pptd_project(run=run, pptd_path=pptd_path, nodes=next_nodes)
            pptx_path = self._recompile_pptd_project(pptd_path=pptd_path, run=run)
            preview = self._pptd_preview_for_slide(
                pptd_path=pptd_path,
                slide_no=slide_no,
            )
        except Exception:
            self._restore_pptd_project(original_project)
            raise

        def apply_regeneration(record: RunRecord) -> None:
            record.status = RunStatus.SUCCEEDED
            record.stage_timings.compile_ms = int(
                (time.perf_counter() - compile_start) * 1000
            )
            record.render_version += 1
            if record.outline is not None and slide_no <= len(record.outline.nodes):
                record.outline.nodes[slide_no - 1] = next_nodes[slide_no - 1]
            existing_by_no = {
                int(getattr(slide, "slide_no", 0) or 0): slide
                for slide in list(getattr(record, "slides", []) or [])
            }
            total = max(
                len(next_nodes),
                int(getattr(record.input, "target_slide_count", 0) or 0),
            )
            record.slides = [
                existing_by_no.get(index)
                or SlideArtifact(
                    slide_no=index,
                    js_path=None,
                    js_code="",
                    status="pptd_outline_ready",
                    citations=[],
                )
                for index in range(1, total + 1)
            ]
            for index, slide in enumerate(record.slides):
                if int(getattr(slide, "slide_no", 0) or 0) == slide_no:
                    record.slides[index] = SlideArtifact(
                        slide_no=slide_no,
                        js_path=None,
                        js_code="",
                        status="pptd_regenerated",
                        citations=list(getattr(slide, "citations", []) or []),
                    )
                    break
            record.compile_js_path = str(pptd_path)
            record.pptx_path = str(pptx_path)
            record.compile_requested_provider = "pptd"
            record.compile_provider = "pptd"
            record.compile_status = "succeeded"
            record.compile_bundle_ready = True
            record.compile_fallback_used = False
            record.compile_error_code = None
            record.compile_error_details = {}

        await self.orch.store.update_run(run_id, apply_regeneration)
        await self.publish_slide_generated_preview(
            run_id=run_id,
            slide_no=slide_no,
            status="pptd_regenerated",
            preview=preview,
        )
        await self.orch._publish(
            run_id,
            EventType.COMPILE_COMPLETED,
            {
                "file": str(pptx_path),
                "provider": "pptd",
                "requested_provider": "pptd",
                "bundle_ready": True,
                "deferred": False,
                "fallback_used": False,
                "reason": "single_slide_regenerate",
            },
        )

    def _run_has_pptd_project(self, run: RunRecord) -> bool:
        pptd_path = self._pptd_project_path(run)
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

    def _pptd_project_path(self, run: RunRecord) -> Path:
        artifact_dir = Path(str(getattr(run, "artifact_dir", "") or ""))
        return artifact_dir / "slides" / "pptd" / "presentation.pptd"

    def _write_pptd_project(
        self, *, run: RunRecord, pptd_path: Path, nodes: list[OutlineNode]
    ) -> None:
        design = self.orch._resolve_run_design(run)
        PptdDeckWriter().write_project(
            pptd_path=pptd_path,
            title=str(getattr(run.input, "topic", "") or "Presentation"),
            nodes=nodes,
            slide_count=max(
                len(nodes),
                int(getattr(run.input, "target_slide_count", 0) or 0),
            ),
            theme=design.theme,
            skill_dir=Path(str(getattr(self.orch.settings, "pptd_skill_dir", "") or "")),
            template_style=str(getattr(run.input, "template_style", "") or ""),
            template_id=str(getattr(run.input, "template_id", "") or "") or None,
        )

    def _regenerated_pptd_outline_node(
        self, *, node: OutlineNode, instruction: str, preserve_style: bool
    ) -> OutlineNode:
        clean_instruction = " ".join(str(instruction or "").split())
        bullets = [item for item in list(node.bullets or []) if str(item).strip()]
        if clean_instruction:
            marker = f"重做要求：{clean_instruction}"
            bullets = [marker, *[item for item in bullets if item != marker]]
        return OutlineNode(
            title=self._regenerated_title(node.title, clean_instruction),
            bullets=bullets[:6],
            page_type=node.page_type,
            layout_hint=node.layout_hint if preserve_style else None,
        )

    def _regenerated_title(self, title: str, instruction: str) -> str:
        current = str(title or "").strip()
        if not instruction or "标题" not in instruction:
            return current
        if any(token in instruction for token in ("精简", "简短", "缩短")):
            for separator in ("：", ":", "，", ",", "（", "("):
                current = current.split(separator, 1)[0].strip()
            return current[:18] or str(title or "").strip()
        return current

    def _recompile_pptd_project(self, *, pptd_path: Path, run: RunRecord) -> Path:
        pptx_path = (
            Path(str(getattr(run, "artifact_dir", "") or ""))
            / "slides"
            / "output"
            / "presentation.pptx"
        )
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
                getattr(self.orch.settings, "pptd_runner_platform", "") or "linux/amd64"
            ),
            timeout_sec=float(
                getattr(self.orch.settings, "pptd_runner_timeout_sec", 120.0) or 120.0
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

    def _pptd_preview_for_slide(self, *, pptd_path: Path, slide_no: int) -> dict[str, Any]:
        manifest = PptdDeckWriter().preview_manifest_from_project(pptd_path=pptd_path)
        pages = manifest.get("pages") if isinstance(manifest.get("pages"), list) else []
        page = pages[slide_no - 1] if slide_no <= len(pages) else {}
        return page if isinstance(page, dict) else {}

    def _snapshot_pptd_project(self, pptd_path: Path) -> dict[Path, bytes]:
        paths = [
            pptd_path,
            pptd_path.parent / "design.md",
            pptd_path.parent / "outline.md",
        ]
        deck = yaml.safe_load(pptd_path.read_text(encoding="utf-8"))
        pages = deck.get("pages") if isinstance(deck, dict) else []
        for page_ref in pages if isinstance(pages, list) else []:
            paths.append(pptd_path.parent / str(page_ref))
        return {path: path.read_bytes() for path in paths if path.is_file()}

    def _restore_pptd_project(self, snapshot: dict[Path, bytes]) -> None:
        for path, content in snapshot.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
