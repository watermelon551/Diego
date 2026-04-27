from __future__ import annotations

from typing import Any

from .slides_runtime import (
    SlidePreviewApplicationMixin,
    SlideRegenerationApplicationMixin,
    SlideSceneApplicationMixin,
)


class SlideApplicationService(
    SlidePreviewApplicationMixin,
    SlideSceneApplicationMixin,
    SlideRegenerationApplicationMixin,
):
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator
