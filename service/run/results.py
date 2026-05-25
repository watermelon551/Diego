from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ScratchCompileResult:
    ok: bool
    compile_js_path: Path
    pptx_path: Path | None
    return_code: int | None
    reason: str
    provider: str
    deferred: bool = False
    bundle_ready: bool = False
    fallback_used: bool = False
    fallback_from: str | None = None
    requested_provider: str | None = None
    job_id: str | None = None
    error_details: dict[str, Any] | None = None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and hasattr(self, key)
