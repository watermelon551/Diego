from __future__ import annotations

import asyncio
from pathlib import Path

from ..results import ScratchCompileResult


class CompileLocalRuntimeMixin:
    runtime: object

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
