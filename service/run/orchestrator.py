from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..config import Settings
from ..llm import (
    GeneratedSlide,
    LLMClient,
    LLMEmptyResponseError,
    OutlineFormatError,
    SlideSpec,
)
from ..rag import StratumindSearchClient, StratumindSearchError, build_rag_context_snippets
from ..models import (
    EventType,
    OutlineNode,
    OutlineHistoryEntry,
    RunEvent,
    RunRecord,
    RunStatus,
    SlideArtifact,
    SlidePageType,
    TemplateRecord,
    VisualPolicy,
)
from ..design.skill_profile import allowed_layouts_for, enforce_layout_variety
from ..design.style_catalog import STYLE_PRESET_AUTO
from ..infra.store import now_iso


from .types import (
    ChartFact,
    ChartPlan,
    JsLayoutBox,
    LayoutBox,
    SlideGenerationError,
    VisualPolicyUnsatisfiedError,
    SlotGraph,
    TemplateAssetError,
    TemplateLayoutConflictError,
    TemplateSlotMappingError,
)
from .orchestrator_api_mixin import RunOrchestratorApiMixin
from .orchestrator_bootstrap_mixin import RunOrchestratorBootstrapMixin
from .slide_scene import (
    SlideSceneConflictError,
    SlideSceneNodeNotFoundError,
    SlideSceneUnsupportedError,
    apply_scene_operations,
    build_slide_scene,
)


class RunOrchestrator(
    RunOrchestratorBootstrapMixin,
    RunOrchestratorApiMixin,
):
    def __init__(
        self,
        *,
        store: Any,
        artifacts_base: Path,
        templates_base: Path,
        llm_client: LLMClient,
        settings: Settings,
        rag_client: StratumindSearchClient | None = None,
    ) -> None:
        self.store = store
        self.artifacts_base = artifacts_base
        self.templates_base = templates_base
        self.settings = settings
        self._initialize_runtime(llm_client=llm_client, rag_client=rag_client)

    def _use_agentic_engine(self) -> bool:
        return self.settings.generation_engine == "agentic_v2"
