from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from ..design.style_catalog import (
    STYLE_PRESET_AUTO,
    is_valid_style_choice,
    normalize_style_choice,
)


class RunStatus(str, Enum):
    PLANNING = "PLANNING"
    AWAITING_PLAN_CONFIRM = "AWAITING_PLAN_CONFIRM"
    DRAFTING = "DRAFTING"
    OUTLINE_DRAFTING = "OUTLINE_DRAFTING"
    AWAITING_OUTLINE_CONFIRM = "AWAITING_OUTLINE_CONFIRM"
    SLIDES_GENERATING = "SLIDES_GENERATING"
    COMPILING = "COMPILING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class EventType(str, Enum):
    REQUIREMENTS_ANALYZING_STARTED = "requirements.analyzing.started"
    REQUIREMENTS_ANALYZING_COMPLETED = "requirements.analyzing.completed"
    REQUIREMENTS_ANALYZED = "requirements.analyzed"
    RAG_RETRIEVAL_STARTED = "rag.retrieval.started"
    RAG_RETRIEVAL_COMPLETED = "rag.retrieval.completed"
    RAG_RETRIEVAL_FAILED = "rag.retrieval.failed"
    OUTLINE_TOKEN = "outline.token"
    OUTLINE_COMPLETED = "outline.completed"
    OUTLINE_UPDATED = "outline.updated"
    PLAN_TOKEN = "plan.token"
    PLAN_UPDATED = "plan.updated"
    SECTION_GENERATED = "section.generated"
    SECTION_REVISED = "section.revised"
    STRUCTURE_EXPANSION_COMPLETED = "structure.expansion.completed"
    ITEM_GENERATION_COMPLETED = "item.generation.completed"
    SLIDE_GENERATED = "slide.generated"
    COMPILE_COMPLETED = "compile.completed"
    RUN_FAILED = "run.failed"
    SLIDE_STARTED = "slide.started"
    COMPILE_STARTED = "compile.started"
    PLAN_COMPLETED = "plan.completed"
    SLIDE_REVIEWED = "slide.reviewed"
    QA_COMPLETED = "qa.completed"
    REPAIR_STARTED = "repair.started"
    SLOT_MAPPING_COMPLETED = "slot.mapping.completed"
    SLIDE_PREVIEW_QA = "slide.preview.qa"
    CHART_TRUTH_CHECKED = "chart.truth.checked"
    REPAIR_ROUND_COMPLETED = "repair.round.completed"
    SLIDE_CODEGEN_STARTED = "slide.codegen.started"
    SLIDE_CODEGEN_COMPLETED = "slide.codegen.completed"
    SLIDE_SPEC_GENERATED = "slide.spec.generated"
    SLIDE_SPEC_REPAIRED = "slide.spec.repaired"
    SLIDE_CRITIC_COMPLETED = "slide.critic.completed"
    SLIDE_REPAIR_COMPLETED = "slide.repair.completed"
    ARTIFACT_CLEANUP_COMPLETED = "artifact.cleanup.completed"
    SLIDE_PLAN_COMPLETED = "slide.plan.completed"
    SLIDE_QUALITY_GATE_COMPLETED = "slide.quality.gate.completed"
    SLIDE_REPAIR_DIRECTIVES_GENERATED = "slide.repair.directives.generated"
    RESEARCH_COMPLETED = "research.completed"
    SLIDE_CANDIDATE_GENERATED = "slide.candidate.generated"
    SLIDE_SELECTION_COMPLETED = "slide.selection.completed"
    TEMPLATE_LAYOUT_REFLOW_COMPLETED = "template.layout.reflow.completed"
    TEMPLATE_FIDELITY_CHECKED = "template.fidelity.checked"
    OUTLINE_REPAIR_STARTED = "outline.repair.started"
    OUTLINE_REPAIR_COMPLETED = "outline.repair.completed"
    OUTLINE_REPAIR_FAILED = "outline.repair.failed"
    LLM_REQUEST_RETRY = "llm.request.retry"
    LLM_REQUEST_TIMEOUT = "llm.request.timeout"
    SLIDE_FAILED = "slide.failed"
    SLIDE_FAILURE_DIAGNOSTICS = "slide.failure.diagnostics"
    SLIDE_AUTO_FIX_APPLIED = "slide.auto.fix.applied"
    SLIDE_RETRY_CONTEXT_BUILT = "slide.retry.context.built"
    RUN_FINALIZED = "run.finalized"


class GenerationMode(str, Enum):
    SCRATCH = "scratch"
    TEMPLATE = "template"


class VisualPolicy(str, Enum):
    AUTO = "auto"
    MEDIA_REQUIRED = "media_required"
    BASIC_GRAPHICS_ONLY = "basic_graphics_only"


class SlidePageType(str, Enum):
    COVER = "cover"
    TOC = "toc"
    SECTION = "section"
    CONTENT = "content"
    SUMMARY = "summary"


class CreateRunRequest(BaseModel):
    capability: Literal["ppt"] = "ppt"
    topic: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    rag_source_ids: list[str] = Field(default_factory=list)
    template_style: str = Field(default="default")
    style_preset: str = Field(default=STYLE_PRESET_AUTO)
    target_slide_count: int = Field(default=8, ge=1, le=50)
    generation_mode: GenerationMode = GenerationMode.SCRATCH
    template_id: Optional[str] = None
    visual_policy: VisualPolicy = VisualPolicy.AUTO

    @model_validator(mode="after")
    def validate_mode(self) -> "CreateRunRequest":
        self.style_preset = normalize_style_choice(self.style_preset)
        if not is_valid_style_choice(self.style_preset):
            raise ValueError(f"invalid style_preset={self.style_preset!r}")
        if self.generation_mode == GenerationMode.TEMPLATE and not self.template_id:
            raise ValueError("template_id is required when generation_mode=template")
        return self


class PromptRunRequest(BaseModel):
    capability: Literal["ppt"] = "ppt"
    prompt: str = Field(min_length=1)
    project_id: str = Field(default="default-project", min_length=1)
    rag_source_ids: list[str] = Field(default_factory=list)
    template_style: str = Field(default="default")
    style_preset: str = Field(default=STYLE_PRESET_AUTO)
    target_slide_count: int = Field(default=8, ge=1, le=50)
    generation_mode: GenerationMode = GenerationMode.SCRATCH
    template_id: Optional[str] = None
    visual_policy: VisualPolicy = VisualPolicy.AUTO

    @model_validator(mode="after")
    def validate_mode(self) -> "PromptRunRequest":
        self.style_preset = normalize_style_choice(self.style_preset)
        if not is_valid_style_choice(self.style_preset):
            raise ValueError(f"invalid style_preset={self.style_preset!r}")
        if self.generation_mode == GenerationMode.TEMPLATE and not self.template_id:
            raise ValueError("template_id is required when generation_mode=template")
        return self

    def to_create_run_request(self) -> CreateRunRequest:
        return CreateRunRequest(
            topic=self.prompt,
            project_id=self.project_id,
            rag_source_ids=self.rag_source_ids,
            template_style=self.template_style,
            style_preset=self.style_preset,
            target_slide_count=self.target_slide_count,
            generation_mode=self.generation_mode,
            template_id=self.template_id,
            visual_policy=self.visual_policy,
        )


class OutlineNode(BaseModel):
    title: str
    bullets: list[str] = Field(default_factory=list)
    page_type: SlidePageType = SlidePageType.CONTENT
    layout_hint: Optional[str] = None


class OutlineDocument(BaseModel):
    version: int
    nodes: list[OutlineNode]
    summary: str


class StageTimings(BaseModel):
    outline_ms: int = 0
    slide_ms: int = 0
    compile_ms: int = 0


class RunEvent(BaseModel):
    seq: int
    event: EventType
    ts: str
    payload: dict[str, Any] = Field(default_factory=dict)
