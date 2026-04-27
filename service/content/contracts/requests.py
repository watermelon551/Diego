from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .results import LongFormPlan


class LongFormRunRequest(BaseModel):
    capability: Literal["content"] = "content"
    content_kind: Literal["longform_draft"] = "longform_draft"
    topic: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    rag_source_ids: list[str] = Field(default_factory=list)
    audience: str = Field(default="general audience")
    purpose: str = Field(default="explain the topic clearly")
    tone: str = Field(default="professional")
    target_section_count: int = Field(default=5, ge=1, le=24)


class LongFormPromptRunRequest(BaseModel):
    capability: Literal["content"] = "content"
    content_kind: Literal["longform_draft"] = "longform_draft"
    prompt: str = Field(min_length=1)
    project_id: str = Field(default="default-project", min_length=1)
    rag_source_ids: list[str] = Field(default_factory=list)
    audience: str = Field(default="general audience")
    purpose: str = Field(default="explain the topic clearly")
    tone: str = Field(default="professional")
    target_section_count: int = Field(default=5, ge=1, le=24)

    def to_create_run_request(self) -> LongFormRunRequest:
        return LongFormRunRequest(
            content_kind=self.content_kind,
            topic=self.prompt,
            project_id=self.project_id,
            rag_source_ids=self.rag_source_ids,
            audience=self.audience,
            purpose=self.purpose,
            tone=self.tone,
            target_section_count=self.target_section_count,
        )


class ContentSourceScope(BaseModel):
    mode: Literal["project_all", "selected_sources"] = "project_all"
    selected_source_ids: list[str] = Field(default_factory=list)
    scope_note: str = ""


class StructureExpansionAnchorContext(BaseModel):
    anchor_label: str = ""
    anchor_summary: str = ""
    related_labels: list[str] = Field(default_factory=list)


class StructureExpansionRunRequest(BaseModel):
    capability: Literal["content"] = "content"
    content_kind: Literal["structure_expansion"] = "structure_expansion"
    generation_goal: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    rag_source_ids: list[str] = Field(default_factory=list)
    source_scope: ContentSourceScope = Field(default_factory=ContentSourceScope)
    evidence_refs: list[str] = Field(default_factory=list)
    anchor_context: StructureExpansionAnchorContext = Field(
        default_factory=StructureExpansionAnchorContext
    )
    constraints: dict[str, Any] = Field(default_factory=dict)
    requested_output_shape: str = Field(default="units")


class StructureExpansionPromptRunRequest(BaseModel):
    capability: Literal["content"] = "content"
    content_kind: Literal["structure_expansion"] = "structure_expansion"
    prompt: str = Field(min_length=1)
    project_id: str = Field(default="default-project", min_length=1)
    rag_source_ids: list[str] = Field(default_factory=list)
    source_scope: ContentSourceScope = Field(default_factory=ContentSourceScope)
    evidence_refs: list[str] = Field(default_factory=list)
    anchor_context: StructureExpansionAnchorContext = Field(
        default_factory=StructureExpansionAnchorContext
    )
    constraints: dict[str, Any] = Field(default_factory=dict)
    requested_output_shape: str = Field(default="units")

    def to_create_run_request(self) -> StructureExpansionRunRequest:
        return StructureExpansionRunRequest(
            generation_goal=self.prompt,
            project_id=self.project_id,
            rag_source_ids=self.rag_source_ids,
            source_scope=self.source_scope,
            evidence_refs=self.evidence_refs,
            anchor_context=self.anchor_context,
            constraints=self.constraints,
            requested_output_shape=self.requested_output_shape,
        )


class ItemGenerationRunRequest(BaseModel):
    capability: Literal["content"] = "content"
    content_kind: Literal["item_generation"] = "item_generation"
    generation_goal: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    rag_source_ids: list[str] = Field(default_factory=list)
    source_scope: ContentSourceScope = Field(default_factory=ContentSourceScope)
    evidence_refs: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    requested_output_shape: str = Field(default="items")


class ItemGenerationPromptRunRequest(BaseModel):
    capability: Literal["content"] = "content"
    content_kind: Literal["item_generation"] = "item_generation"
    prompt: str = Field(min_length=1)
    project_id: str = Field(default="default-project", min_length=1)
    rag_source_ids: list[str] = Field(default_factory=list)
    source_scope: ContentSourceScope = Field(default_factory=ContentSourceScope)
    evidence_refs: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    requested_output_shape: str = Field(default="items")

    def to_create_run_request(self) -> ItemGenerationRunRequest:
        return ItemGenerationRunRequest(
            generation_goal=self.prompt,
            project_id=self.project_id,
            rag_source_ids=self.rag_source_ids,
            source_scope=self.source_scope,
            evidence_refs=self.evidence_refs,
            constraints=self.constraints,
            requested_output_shape=self.requested_output_shape,
        )


class ConfirmLongFormPlanRequest(BaseModel):
    approved: bool = True
    plan: LongFormPlan | None = None
    base_version: int | None = None
    change_reason: str | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "ConfirmLongFormPlanRequest":
        if self.plan is not None and self.base_version is None:
            raise ValueError("base_version is required when plan is provided")
        if self.plan is None and self.change_reason:
            raise ValueError("change_reason requires plan")
        return self


class ReviseLongFormSectionRequest(BaseModel):
    instruction: str = Field(min_length=1)
    base_revision: int = Field(ge=1)
    preserve_structure: bool = True

