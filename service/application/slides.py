from __future__ import annotations

from typing import Any

from .slide_preview_application_mixin import SlidePreviewApplicationMixin
from .slide_regeneration_application_mixin import (
    SlideRegenerationApplicationMixin,
)
from .slide_scene_application_mixin import SlideSceneApplicationMixin


class SlideApplicationService(
    SlidePreviewApplicationMixin,
    SlideSceneApplicationMixin,
    SlideRegenerationApplicationMixin,
):
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator

