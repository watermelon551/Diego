from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from ....models import EventType, RunStatus


class TemplateFlowPrepareMixin:
    orch: Any

    async def _prepare_template_workspace(
        self,
        *,
        run_id: str,
        artifact_dir: str,
        template_path: str,
    ) -> tuple[Path, Path, Path, Path, Path, Path, Path, Path] | None:
        orch = self.orch
        await orch.store.update_run(
            run_id, lambda r: setattr(r, "status", RunStatus.COMPILING)
        )
        await orch._publish(run_id, EventType.COMPILE_STARTED, {"mode": "template"})

        work_paths = orch.template_engine.template_work_paths(Path(artifact_dir))
        (
            template_dir,
            work_template,
            template_md,
            unpacked,
            _edited,
            _template_slides_dir,
            _template_compile_js,
            _,
        ) = work_paths
        template_dir.mkdir(parents=True, exist_ok=True)
        unpacked.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(template_path), work_template)
        markitdown_template = await asyncio.to_thread(
            orch.subprocess.run,
            [sys.executable, "-m", "markitdown", str(work_template)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if markitdown_template.returncode == 0 and markitdown_template.stdout:
            template_md.write_text(markitdown_template.stdout, encoding="utf-8")
        elif markitdown_template.returncode != 0:
            markitdown_stderr = (markitdown_template.stderr or "").lower()
            markitdown_stdout = (markitdown_template.stdout or "").lower()
            if (
                "template parse error" in markitdown_stderr
                or "template parse error" in markitdown_stdout
            ):
                await orch._fail_run(
                    run_id,
                    "SLIDES_GENERATING",
                    "TEMPLATE_MARKITDOWN_FAILED",
                    retryable=False,
                )
                return None
            await orch._append_quality_entry(
                run_id=run_id,
                entry={
                    "stage": "template.markitdown.preflight",
                    "status": "degraded_skip",
                    "reason": orch._summarize_process_failure(
                        stderr=markitdown_template.stderr or "",
                        stdout=markitdown_template.stdout or "",
                    )[0],
                },
            )

        if unpacked.exists():
            shutil.rmtree(unpacked)
        unpacked.mkdir(parents=True, exist_ok=True)
        with ZipFile(work_template, "r") as zin:
            zin.extractall(unpacked)
        return work_paths
