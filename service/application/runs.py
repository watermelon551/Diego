from __future__ import annotations

from typing import Any

from .runs_runtime import (
    RunApplicationDetailMixin,
    RunApplicationOutlineConfirmMixin,
    RunApplicationRuntimeMixin,
)


class RunApplicationService(
    RunApplicationRuntimeMixin,
    RunApplicationDetailMixin,
    RunApplicationOutlineConfirmMixin,
):
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator


__all__ = ["RunApplicationService"]
