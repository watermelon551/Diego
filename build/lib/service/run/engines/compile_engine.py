from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

import httpx

from ..results import ScratchCompileResult
from ..types import RunStageError


class CompileEngine:
    result_type = ScratchCompileResult

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    async def compile_scratch_run(
        self,
        *,
        run_id: str,
        slides_dir: Path,
        slide_count: int,
        theme: dict[str, Any],
    ) -> ScratchCompileResult:
        requested_provider = str(
            getattr(self.runtime.settings, "compile_provider", "none") or "none"
        ).strip().lower()
        compile_js = self._ensure_compile_script(
            slides_dir=slides_dir,
            slide_count=slide_count,
            theme=theme,
        )
        if requested_provider == "none":
            return ScratchCompileResult(
                ok=True,
                compile_js_path=compile_js,
                pptx_path=None,
                return_code=None,
                reason="external_compile_deferred",
                provider="none",
                deferred=True,
                bundle_ready=True,
                requested_provider="none",
            )
        if requested_provider == "local":
            local_result = await self._compile_scratch_local(slides_dir=slides_dir)
            return ScratchCompileResult(
                **{**local_result.__dict__, "requested_provider": "local"}
            )
        if requested_provider == "pagevra":
            pagevra_result = await self._compile_scratch_via_pagevra(
                run_id=run_id,
                slides_dir=slides_dir,
                theme=theme,
            )
            return ScratchCompileResult(
                **{
                    **pagevra_result.__dict__,
                    "requested_provider": pagevra_result.requested_provider or "pagevra",
                }
            )

        raise ValueError(f"unsupported compile provider: {requested_provider}")

    async def build_compile_bundle(self, run_id: str) -> dict[str, Any]:
        run = await self.runtime.store.get_run(run_id)
        if run is None:
            raise ValueError(f"run not found: {run_id}")
        generation_mode = getattr(getattr(run, "input", None), "generation_mode", None)
        if str(getattr(generation_mode, "value", generation_mode)) != "scratch":
            raise ValueError(f"compile bundle is only available for scratch runs: {run_id}")
        slides_dir = Path(run.artifact_dir) / "slides"
        slide_count = len(getattr(run, "slides", []) or [])
        theme: dict[str, Any] = {}
        resolver = getattr(self.runtime, "_resolve_run_design", None)
        if callable(resolver):
            theme = dict(getattr(resolver(run), "theme", {}) or {})
        self._ensure_compile_script(
            slides_dir=slides_dir,
            slide_count=slide_count,
            theme=theme,
        )
        return await self._build_scratch_compile_bundle(run=run, slides_dir=slides_dir)

    def _ensure_compile_script(
        self,
        *,
        slides_dir: Path,
        slide_count: int,
        theme: dict[str, Any],
    ) -> Path:
        compile_js = slides_dir / "compile.js"
        compile_js.write_text(
            self.runtime._build_compile_script(total=slide_count, theme=theme),
            encoding="utf-8",
        )
        return compile_js

    async def _compile_scratch_local(self, *, slides_dir: Path) -> ScratchCompileResult:
        result = await asyncio.to_thread(
            self.runtime.subprocess.run,
            ["node", "compile.js"],
            cwd=slides_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        compile_reason = self.runtime._known_compile_stderr_reason(
            stderr=result.stderr or "",
            stdout=result.stdout or "",
        )
        return ScratchCompileResult(
            ok=result.returncode == 0 and not compile_reason,
            compile_js_path=slides_dir / "compile.js",
            pptx_path=slides_dir / "output" / "presentation.pptx",
            return_code=result.returncode,
            reason=compile_reason or "compile.js returned non-zero",
            provider="local",
            bundle_ready=True,
            fallback_used=False,
            fallback_from=None,
        )

    async def _compile_scratch_via_pagevra(
        self,
        *,
        run_id: str,
        slides_dir: Path,
        theme: dict[str, Any] | None = None,
        swallow_failure: bool = False,
    ) -> ScratchCompileResult:
        base_url = str(getattr(self.runtime.settings, "pagevra_base_url", "") or "").strip().rstrip("/")
        if not base_url:
            if swallow_failure:
                return ScratchCompileResult(
                    ok=False,
                    compile_js_path=slides_dir / "compile.js",
                    pptx_path=slides_dir / "output" / "presentation.pptx",
                    return_code=None,
                    reason="pagevra_base_url_missing",
                    provider="pagevra",
                    bundle_ready=True,
                )
            raise RunStageError(
                stage="COMPILING",
                error_code="PAGEVRA_BASE_URL_MISSING",
                retryable=False,
                details={"provider": "pagevra", "reason": "pagevra_base_url_missing"},
            )
        try:
            run = await self.runtime.store.get_run(run_id)
            if run is None:
                raise RunStageError(
                    stage="COMPILING",
                    error_code="COMPILE_RUN_NOT_FOUND",
                    retryable=False,
                    details={"provider": "pagevra", "reason": "run_not_found"},
                )
            bundle = await self._build_scratch_compile_bundle(run=run, slides_dir=slides_dir, theme=theme)
            timeout = float(getattr(self.runtime.settings, "pagevra_compile_timeout_sec", 180.0) or 180.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{base_url}/compile/bundles", json=bundle)
                payload = response.json()
                if response.status_code >= 400 or payload.get("state") != "success":
                    reason = str(payload.get("state_reason") or payload.get("error") or "pagevra_compile_failed")
                    if swallow_failure:
                        return ScratchCompileResult(
                            ok=False,
                            compile_js_path=slides_dir / "compile.js",
                            pptx_path=slides_dir / "output" / "presentation.pptx",
                            return_code=response.status_code,
                            reason=reason,
                            provider="pagevra",
                            bundle_ready=True,
                        )
                    raise RunStageError(
                        stage="COMPILING",
                        error_code="PAGEVRA_COMPILE_FAILED",
                        retryable=response.status_code >= 500 or response.status_code == 429,
                        details={
                            "provider": "pagevra",
                            "status_code": response.status_code,
                            "reason": reason,
                        },
                    )
                job_id = str(payload.get("job_id") or "").strip()
                if not job_id:
                    raise RunStageError(
                        stage="COMPILING",
                        error_code="PAGEVRA_JOB_ID_MISSING",
                        retryable=True,
                        details={"provider": "pagevra", "reason": "pagevra_compile_missing_job_id"},
                    )
                artifact = await client.get(f"{base_url}/compile/jobs/{job_id}/artifacts/pptx")
                if artifact.status_code >= 400:
                    raise RunStageError(
                        stage="COMPILING",
                        error_code="PAGEVRA_ARTIFACT_DOWNLOAD_FAILED",
                        retryable=artifact.status_code >= 500 or artifact.status_code == 429,
                        details={
                            "provider": "pagevra",
                            "status_code": artifact.status_code,
                            "job_id": job_id,
                            "reason": "pagevra_artifact_download_failed",
                        },
                    )
                pptx_path = slides_dir / "output" / "presentation.pptx"
                pptx_path.parent.mkdir(parents=True, exist_ok=True)
                pptx_path.write_bytes(artifact.content)
                return ScratchCompileResult(
                    ok=True,
                    compile_js_path=slides_dir / "compile.js",
                    pptx_path=pptx_path,
                    return_code=0,
                    reason="",
                    provider="pagevra",
                    job_id=job_id,
                    bundle_ready=True,
                    fallback_used=False,
                    fallback_from=None,
                    requested_provider="pagevra",
                )
        except Exception as exc:
            if swallow_failure:
                return ScratchCompileResult(
                    ok=False,
                    compile_js_path=slides_dir / "compile.js",
                    pptx_path=slides_dir / "output" / "presentation.pptx",
                    return_code=None,
                    reason=str(exc),
                    provider="pagevra",
                    bundle_ready=True,
                )
            if isinstance(exc, RunStageError):
                raise
            if isinstance(exc, httpx.HTTPError):
                raise RunStageError(
                    stage="COMPILING",
                    error_code="PAGEVRA_HTTP_ERROR",
                    retryable=True,
                    details={"provider": "pagevra", "reason": str(exc)},
                ) from exc
            raise RunStageError(
                stage="COMPILING",
                error_code="PAGEVRA_COMPILE_ERROR",
                retryable=True,
                details={"provider": "pagevra", "reason": str(exc)},
            ) from exc

    async def _build_scratch_compile_bundle(self, *, run: Any, slides_dir: Path, theme: dict[str, Any] | None = None) -> dict[str, Any]:
        files: list[dict[str, str]] = []
        assets: list[dict[str, str]] = []
        for file_path in sorted(slides_dir.rglob("*")):
            if not file_path.is_file():
                continue
            rel_path = file_path.relative_to(slides_dir).as_posix()
            if rel_path.startswith("output/"):
                continue
            entry = {
                "path": f"slides/{rel_path}",
                "content_base64": base64.b64encode(file_path.read_bytes()).decode("ascii"),
            }
            if file_path.suffix.lower() == ".js":
                files.append(entry)
            else:
                assets.append(entry)
        return {
            "provider": "diego",
            "provider_run_id": str(run.run_id),
            "provider_trace_id": str(run.trace_id),
            "mode": "scratch",
            "entrypoint": "slides/compile.js",
            "working_dir_manifest": {
                "dirs": ["slides", "slides/output"],
            },
            "files": files,
            "assets": assets,
            "compile_options": {
                "command": ["node", "compile.js"],
                "cwd": "slides",
                "output_artifact_path": "slides/output/presentation.pptx",
            },
            "metadata": {
                "artifact_dir": str(run.artifact_dir),
                "theme_source": "diego",
                "compile_context": {
                    "theme": theme or {},
                },
            },
        }
