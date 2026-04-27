from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from .contracts_shared import (
    EventType,
    GenerationMode,
    OutlineDocument,
    OutlineNode,
    RunEvent,
    RunStatus,
    SlidePageType,
    StageTimings,
)


class SlideArtifact(BaseModel):
    slide_no: int
    js_path: Optional[str] = None
    js_code: str
    status: str
    citations: list[str] = Field(default_factory=list)


class GenerationResult(BaseModel):
    mode: GenerationMode
    artifact_dir: Optional[str] = None
    outline_ready: bool = False
    slide_count: int = 0
    slide_artifacts_ready: bool = False
    citation_map_ready: bool = False
    compile_bundle_ready: bool = False
    compile_bundle_entrypoint: Optional[str] = None


class CompileBundleResult(BaseModel):
    status: str = "not_available"
    provider: str = "diego"
    available: bool = False
    entrypoint: Optional[str] = None
    build_endpoint: Optional[str] = None
    mode: Optional[str] = None


class CompileResult(BaseModel):
    status: str = "not_requested"
    requested_provider: Optional[str] = None
    provider: Optional[str] = None
    bundle_ready: bool = False
    artifact_path: Optional[str] = None
    artifact_ready: bool = False
    fallback_used: bool = False
    fallback_from: Optional[str] = None
    error_code: Optional[str] = None
    error_details: dict[str, Any] = Field(default_factory=dict)


class ConfirmOutlineRequest(BaseModel):
    approved: bool = True
    outline: Optional[OutlineDocument] = None
    base_version: Optional[int] = None
    change_reason: Optional[str] = None

    @model_validator(mode="after")
    def validate_patch(self) -> "ConfirmOutlineRequest":
        if self.outline is not None and self.base_version is None:
            raise ValueError("base_version is required when outline is provided")
        if self.outline is None and self.change_reason:
            raise ValueError("change_reason requires outline")
        return self


class RegenerateSlideRequest(BaseModel):
    instruction: str = Field(min_length=1)
    preserve_style: bool = True
    expected_render_version: Optional[int] = Field(default=None, ge=1)


class EditableSlideNodeBBox(BaseModel):
    x: float
    y: float
    w: float
    h: float


class EditableSlideNode(BaseModel):
    node_id: str = Field(min_length=1)
    kind: Literal["text", "image"]
    label: str = Field(min_length=1)
    text: Optional[str] = None
    src: Optional[str] = None
    alt: Optional[str] = None
    bbox: Optional[EditableSlideNodeBBox] = None
    style: dict[str, Any] = Field(default_factory=dict)
    edit_capabilities: list[str] = Field(default_factory=list)


class EditableSlideScene(BaseModel):
    run_id: str = Field(min_length=1)
    slide_id: str = Field(min_length=1)
    slide_index: int = Field(ge=0)
    slide_no: int = Field(ge=1)
    scene_version: str = Field(min_length=1)
    nodes: list[EditableSlideNode] = Field(default_factory=list)
    readonly: bool = False
    readonly_reason: Optional[str] = None


class SaveSlideSceneOperation(BaseModel):
    op: Literal["replace_text", "replace_image"]
    node_id: str = Field(min_length=1)
    value: str


class SaveSlideSceneRequest(BaseModel):
    scene_version: str = Field(min_length=1)
    operations: list[SaveSlideSceneOperation] = Field(
        default_factory=list, min_length=1
    )


class SaveSlideSceneResponse(BaseModel):
    run_id: str = Field(min_length=1)
    slide_id: str = Field(min_length=1)
    slide_index: int = Field(ge=0)
    slide_no: int = Field(ge=1)
    render_version: int = Field(default=0, ge=0)
    status: str = Field(default="ready")
    scene: EditableSlideScene
    preview: dict[str, Any] = Field(default_factory=dict)


class OutlineHistoryEntry(BaseModel):
    action: str
    approved: bool
    base_version: Optional[int] = None
    new_version: Optional[int] = None
    change_reason: Optional[str] = None
    at: str


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
