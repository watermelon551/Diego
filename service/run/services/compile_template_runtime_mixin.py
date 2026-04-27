from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from ...design.skill_profile import DesignProfile
from ...models import EventType, RunRecord
from ..types import TemplateAssetError


class CompileTemplateRuntimeMixin:
    orch: Any

    def template_work_paths(
        self, artifact_dir: Path
    ) -> tuple[Path, Path, Path, Path, Path, Path, Path, Path]:
        template_dir = artifact_dir / "template_edit"
        work_template = template_dir / "template.pptx"
        template_md = template_dir / "template.md"
        unpacked = template_dir / "unpacked"
        edited = template_dir / "edited.pptx"
        template_slides_dir = artifact_dir / "template_slides"
        template_compile_js = template_slides_dir / "compile.js"
        template_compiled_pptx = template_slides_dir / "output" / "presentation.pptx"
        return (
            template_dir,
            work_template,
            template_md,
            unpacked,
            edited,
            template_slides_dir,
            template_compile_js,
            template_compiled_pptx,
        )

    def pack_template_unpacked(self, *, unpacked: Path, edited: Path) -> None:
        with ZipFile(edited, "w", compression=ZIP_DEFLATED) as zout:
            for file in unpacked.rglob("*"):
                if file.is_file():
                    arc = file.relative_to(unpacked).as_posix()
                    zout.write(file, arc)

    async def compile_template_js(self, *, template_slides_dir: Path) -> bool:
        orch = self.orch
        result = await asyncio.to_thread(
            orch.subprocess.run,
            ["node", "compile.js"],
            cwd=template_slides_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        reason = orch._known_compile_stderr_reason(
            stderr=result.stderr or "", stdout=result.stdout or ""
        )
        return result.returncode == 0 and not reason

    async def compile_scratch_slides(self, run_id: str) -> bool:
        orch = self.orch
        run = await orch.store.get_run(run_id)
        if run is None:
            return False
        compile_res = await asyncio.to_thread(
            orch.subprocess.run,
            ["node", "compile.js"],
            cwd=Path(run.artifact_dir) / "slides",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        reason = orch._known_compile_stderr_reason(
            stderr=compile_res.stderr or "", stdout=compile_res.stdout or ""
        )
        return compile_res.returncode == 0 and not reason

    async def revise_template_slides(
        self,
        *,
        run_id: str,
        design: DesignProfile,
        forced_issues: list[str] | None,
    ) -> bool:
        orch = self.orch
        run = await orch.store.get_run(run_id)
        if run is None:
            return False
        _, _, _, unpacked, edited, template_slides_dir, template_compile_js, _ = self.template_work_paths(
            Path(run.artifact_dir)
        )
        if not unpacked.exists():
            return False
        try:
            artifacts = await self.apply_template_nodes_once(
                run_id=run_id,
                unpacked=unpacked,
                design=design,
                use_review=True,
                forced_issues=forced_issues,
            )
        except TemplateAssetError:
            return False
        if not artifacts:
            return False
        self.pack_template_unpacked(unpacked=unpacked, edited=edited)
        compiled = await self.compile_template_js(
            template_slides_dir=template_slides_dir
        )
        if not compiled:
            return False

        def apply_compile(r: RunRecord) -> None:
            r.pptx_path = str(edited)
            r.compile_js_path = str(template_compile_js)
            r.stage_timings.compile_ms = max(1, r.stage_timings.compile_ms)
            r.slides = artifacts
            r.citation_map = {item.slide_no: list(item.citations) for item in artifacts}

        await orch.store.update_run(run_id, apply_compile)
        await orch._publish(
            run_id,
            EventType.COMPILE_COMPLETED,
            {"file": str(edited), "mode": "template-repair"},
        )
        return True
