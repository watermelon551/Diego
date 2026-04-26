from __future__ import annotations

import os
import warnings


def maybe_warn_legacy_import(*, legacy: str, replacement: str) -> None:
    """Emit deprecation warning for legacy shim imports when explicitly enabled."""
    flag = str(os.getenv("PPT_AGENT_SHIM_WARNINGS", "")).strip().lower()
    if flag not in {"1", "true", "yes", "on"}:
        return
    warnings.warn(
        f"{legacy} is deprecated; use {replacement} instead.",
        DeprecationWarning,
        stacklevel=3,
    )

