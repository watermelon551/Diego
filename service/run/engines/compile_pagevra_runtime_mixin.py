from __future__ import annotations

from pathlib import Path
from typing import Any

from ..results import ScratchCompileResult
from ..types import RunStageError


class CompilePagevraRuntimeMixin:
    runtime: Any
    httpx: Any

    async def _compile_scratch_via_pagevra(
        self,
        *,
        run_id: str,
        slides_dir: Path,
        theme: dict[str, Any] | None = None,
        swallow_failure: bool = False,
    ) -> ScratchCompileResult:
        base_url = (
            str(getattr(self.runtime.settings, "pagevra_base_url", "") or "")
            .strip()
            .rstrip("/")
        )
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
            bundle = await self._build_scratch_compile_bundle(
                run=run, slides_dir=slides_dir, theme=theme
            )
            timeout = float(
                getattr(self.runtime.settings, "pagevra_compile_timeout_sec", 180.0)
                or 180.0
            )
            async with self.httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{base_url}/compile/bundles", json=bundle)
                payload = response.json()
                if response.status_code >= 400 or payload.get("state") != "success":
                    reason = str(
                        payload.get("state_reason")
                        or payload.get("error")
                        or "pagevra_compile_failed"
                    )
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
                        retryable=response.status_code >= 500
                        or response.status_code == 429,
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
                        details={
                            "provider": "pagevra",
                            "reason": "pagevra_compile_missing_job_id",
                        },
                    )
                artifact = await client.get(
                    f"{base_url}/compile/jobs/{job_id}/artifacts/pptx"
                )
                if artifact.status_code >= 400:
                    raise RunStageError(
                        stage="COMPILING",
                        error_code="PAGEVRA_ARTIFACT_DOWNLOAD_FAILED",
                        retryable=artifact.status_code >= 500
                        or artifact.status_code == 429,
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
            if isinstance(exc, self.httpx.HTTPError):
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
