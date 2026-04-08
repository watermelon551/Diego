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
    SLIDE_GENERATED = "slide.generated"
    COMPILE_COMPLETED = "compile.completed"
    RUN_FAILED = "run.failed"
    SLIDE_STARTED = "slide.started"
    COMPILE_STARTED = "compile.started"


class CreateRunRequest(BaseModel):
    topic: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    rag_source_ids: list[str] = Field(default_factory=list)
    template_style: str = Field(default="default")
    target_slide_count: int = Field(default=8, ge=1, le=50)


class OutlineNode(BaseModel):
    title: str
    bullets: list[str] = Field(default_factory=list)


class OutlineDocument(BaseModel):
    version: int
    nodes: list[OutlineNode]
    summary: str


class SlideArtifact(BaseModel):
    slide_no: int
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


class RunRecord(BaseModel):
    run_id: str
    trace_id: str
    status: RunStatus
    input: CreateRunRequest
    outline: OutlineDocument | None = None
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


class RunSummaryResponse(BaseModel):
    run_id: str
    trace_id: str
    status: RunStatus


class RunDetailResponse(BaseModel):
    run_id: str
    trace_id: str
    status: RunStatus
    outline: OutlineDocument | None
    slides: list[SlideArtifact]
    citation_map: dict[int, list[str]]
    stage_timings: StageTimings
    error_code: str | None
    failed_stage: str | None
    retryable: bool
    compile_js_path: str | None
    pptx_path: str | None
    events: list[RunEvent]
