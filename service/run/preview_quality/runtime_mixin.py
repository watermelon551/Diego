from __future__ import annotations

from pathlib import Path
from typing import Any

from ...models import EventType, GenerationMode, RunRecord, SlideArtifact
from .preview_runtime import (
    markitdown_check,
    markitdown_extract,
    run_slide_preview_qa_with_text,
    summarize_process_failure,
)
from ..slide_preview import build_placeholder_preview, render_slide_via_pagevra


class RunPreviewRuntimeMixin:
    async def render_slide_preview_or_fallback(
        self,
        *,
        run_id: str,
        slide_no: int,
        slide_js_path: Path,
        theme: dict[str, Any],
    ) -> dict[str, Any]:
        if not bool(getattr(self.settings, "pagevra_preview_enabled", True)):
            return self._build_placeholder_preview(
                slide_no=slide_no,
                theme=theme,
                reason="pagevra_preview_disabled",
            )
        pagevra_base_url = (
            str(getattr(self.settings, "pagevra_base_url", "") or "")
            .strip()
            .rstrip("/")
        )
        if not pagevra_base_url:
            return self._build_placeholder_preview(
                slide_no=slide_no,
                theme=theme,
                reason="pagevra_base_url_missing",
            )
        try:
            return await render_slide_via_pagevra(
                slide_js_path=slide_js_path,
                theme=theme,
                slide_no=slide_no,
                pagevra_base_url=pagevra_base_url,
                timeout_sec=float(
                    getattr(self.settings, "pagevra_preview_timeout_sec", 300.0) or 300.0
                ),
                provider_run_id=run_id,
            )
        except Exception as exc:
            return self._build_placeholder_preview(
                slide_no=slide_no,
                theme=theme,
                reason=self._exception_reason(exc),
            )

    def _require_slide_js_artifact(
        self,
        *,
        run: RunRecord,
        slide_no: int,
        not_ready_message: str,
    ) -> tuple[SlideArtifact, Path]:
        slide = next(
            (
                item
                for item in run.slides
                if int(getattr(item, "slide_no", 0) or 0) == slide_no
            ),
            None,
        )
        if slide is None:
            raise ValueError(not_ready_message)
        slide_js_path = Path(str(getattr(slide, "js_path", "") or "").strip())
        if not str(slide_js_path):
            raise FileNotFoundError("slide js artifact missing")
        if not slide_js_path.exists() or not slide_js_path.is_file():
            inline_js_code = str(getattr(slide, "js_code", "") or "")
            if inline_js_code.strip():
                slide_js_path.parent.mkdir(parents=True, exist_ok=True)
                slide_js_path.write_text(inline_js_code, encoding="utf-8")
        if not slide_js_path.exists() or not slide_js_path.is_file():
            raise FileNotFoundError("slide js artifact missing")
        return slide, slide_js_path

    def _build_placeholder_preview(
        self,
        *,
        slide_no: int,
        theme: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        return build_placeholder_preview(
            slide_no=slide_no,
            theme=theme,
            reason=reason,
        )

    async def _markitdown_check(self, pptx_path: Path) -> tuple[bool, str | None]:
        return await markitdown_check(
            run_subprocess=self.subprocess.run,
            pptx_path=pptx_path,
        )

    async def _markitdown_extract(self, pptx_path: Path) -> tuple[str, str | None]:
        return await markitdown_extract(
            run_subprocess=self.subprocess.run,
            pptx_path=pptx_path,
        )

    def _summarize_process_failure(
        self, *, stderr: str, stdout: str
    ) -> tuple[str, str]:
        return summarize_process_failure(stderr=stderr, stdout=stdout)

    async def _run_slide_preview_qa(
        self, *, run_id: str, slide_js: Path, slide_no: int
    ) -> list[str]:
        issues, _, _ = await self._run_slide_preview_qa_with_text(
            run_id=run_id,
            slide_js=slide_js,
            slide_no=slide_no,
        )
        return issues

    async def _run_slide_preview_qa_with_text(
        self,
        *,
        run_id: str,
        slide_js: Path,
        slide_no: int,
    ) -> tuple[list[str], str, dict[str, Any]]:
        return await run_slide_preview_qa_with_text(
            run_id=run_id,
            slide_js=slide_js,
            slide_no=slide_no,
            preview_qa_gate=self._preview_qa_gate,
            llm_timeout_sec=self.settings.llm_timeout_sec,
            debug_keep_previews=self.settings.debug_keep_previews,
            run_subprocess=self.subprocess.run,
            known_compile_stderr_reason=self._known_compile_stderr_reason,
            truncate_diag_text=self._truncate_diag_text,
            exception_reason=self._exception_reason,
            publish=self._publish,
            append_artifact_cleanup_entry=self._append_artifact_cleanup_entry,
            extract_preview_text=self._markitdown_extract,
        )
