from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class RunStatus(str, Enum):
    OUTLINE_DRAFTING = "OUTLINE_DRAFTING"
    AWAITING_OUTLINE_CONFIRM = "AWAITING_OUTLINE_CONFIRM"
    SLIDES_GENERATING = "SLIDES_GENERATING"
    COMPILING = "COMPILING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class EventType(str, Enum):
    OUTLINE_TOKEN = "outline.token"
    OUTLINE_COMPLETED = "outline.completed"
    OUTLINE_UPDATED = "outline.updated"
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
    topic: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    rag_source_ids: list[str] = Field(default_factory=list)
    template_style: str = Field(default="default")
    target_slide_count: int = Field(default=8, ge=1, le=50)
    generation_mode: GenerationMode = GenerationMode.SCRATCH
    template_id: str | None = None
    visual_policy: VisualPolicy = VisualPolicy.AUTO

    @model_validator(mode="after")
    def validate_mode(self) -> "CreateRunRequest":
        if self.generation_mode == GenerationMode.TEMPLATE and not self.template_id:
            raise ValueError("template_id is required when generation_mode=template")
        return self


class PromptRunRequest(BaseModel):
    prompt: str = Field(min_length=1)
    project_id: str = Field(default="default-project", min_length=1)
    rag_source_ids: list[str] = Field(default_factory=list)
    template_style: str = Field(default="default")
    target_slide_count: int = Field(default=8, ge=1, le=50)
    generation_mode: GenerationMode = GenerationMode.SCRATCH
    template_id: str | None = None
    visual_policy: VisualPolicy = VisualPolicy.AUTO

    @model_validator(mode="after")
    def validate_mode(self) -> "PromptRunRequest":
        if self.generation_mode == GenerationMode.TEMPLATE and not self.template_id:
            raise ValueError("template_id is required when generation_mode=template")
        return self

    def to_create_run_request(self) -> CreateRunRequest:
        return CreateRunRequest(
            topic=self.prompt,
            project_id=self.project_id,
            rag_source_ids=self.rag_source_ids,
            template_style=self.template_style,
            target_slide_count=self.target_slide_count,
            generation_mode=self.generation_mode,
            template_id=self.template_id,
            visual_policy=self.visual_policy,
        )


class OutlineNode(BaseModel):
    title: str
    bullets: list[str] = Field(default_factory=list)
    page_type: SlidePageType = SlidePageType.CONTENT
    layout_hint: str | None = None


class OutlineDocument(BaseModel):
    version: int
    nodes: list[OutlineNode]
    summary: str


class SlideArtifact(BaseModel):
    slide_no: int
    js_path: str | None = None
    js_code: str
    status: str
    citations: list[str] = Field(default_factory=list)


class StageTimings(BaseModel):
    outline_ms: int = 0
    slide_ms: int = 0
    compile_ms: int = 0


class RunEvent(BaseModel):
    seq: int
    event: EventType
    ts: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ConfirmOutlineRequest(BaseModel):
    approved: bool = True
    outline: OutlineDocument | None = None
    base_version: int | None = None
    change_reason: str | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "ConfirmOutlineRequest":
        if self.outline is not None and self.base_version is None:
            raise ValueError("base_version is required when outline is provided")
        if self.outline is None and self.change_reason:
            raise ValueError("change_reason requires outline")
        return self


class OutlineHistoryEntry(BaseModel):
    action: str
    approved: bool
    base_version: int | None = None
    new_version: int | None = None
    change_reason: str | None = None
    at: str


class RunRecord(BaseModel):
    run_id: str
    trace_id: str
    status: RunStatus
    input: CreateRunRequest
    outline: OutlineDocument | None = None
    outline_history: list[OutlineHistoryEntry] = Field(default_factory=list)
    slides: list[SlideArtifact] = Field(default_factory=list)
    citation_map: dict[int, list[str]] = Field(default_factory=dict)
    events: list[RunEvent] = Field(default_factory=list)
    stage_timings: StageTimings = Field(default_factory=StageTimings)
    error_code: str | None = None
    failed_stage: str | None = None
    retryable: bool = False
    artifact_dir: str
    compile_js_path: str | None = None
    pptx_path: str | None = None
    qa_report: dict[str, Any] = Field(default_factory=dict)
    template_mapping_report: dict[str, Any] = Field(default_factory=dict)
    chart_truth_report: dict[str, Any] = Field(default_factory=dict)
    repair_history: list[dict[str, Any]] = Field(default_factory=list)
    quality_report: dict[str, Any] = Field(default_factory=dict)
    quality_gate_report: dict[str, Any] = Field(default_factory=dict)
    research_report: dict[str, Any] = Field(default_factory=dict)
    candidate_selection_report: dict[str, Any] = Field(default_factory=dict)
    template_layout_report: dict[str, Any] = Field(default_factory=dict)
    artifact_cleanup_report: dict[str, Any] = Field(default_factory=dict)


class RunSummaryResponse(BaseModel):
    run_id: str
    trace_id: str
    status: RunStatus


class RunDetailResponse(BaseModel):
    run_id: str
    trace_id: str
    status: RunStatus
    outline: OutlineDocument | None
    outline_history: list[OutlineHistoryEntry]
    slides: list[SlideArtifact]
    citation_map: dict[int, list[str]]
    stage_timings: StageTimings
    error_code: str | None
    failed_stage: str | None
    retryable: bool
    compile_js_path: str | None
    pptx_path: str | None
    qa_report: dict[str, Any]
    template_mapping_report: dict[str, Any]
    chart_truth_report: dict[str, Any]
    repair_history: list[dict[str, Any]]
    quality_report: dict[str, Any]
    quality_gate_report: dict[str, Any]
    research_report: dict[str, Any]
    candidate_selection_report: dict[str, Any]
    template_layout_report: dict[str, Any]
    artifact_cleanup_report: dict[str, Any]
    events: list[RunEvent]


class TemplateRecord(BaseModel):
    template_id: str
    filename: str
    path: str
    created_at: str


class TemplateUploadResponse(BaseModel):
    template_id: str
    filename: str


class TemplateDetailResponse(BaseModel):
    template_id: str
    filename: str
    path: str
    created_at: str
