from __future__ import annotations

from typing import Any, Protocol

from ...models import (
    ItemGenerationResult,
    LongFormDraftSection,
    LongFormPlan,
    StructureExpansionAnchorContext,
    StructureExpansionResult,
)
from .base import TokenCallback


class LLMContentProtocol(Protocol):
    async def generate_longform_research_brief(
        self,
        *,
        topic: str,
        project_id: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, Any]],
        audience: str,
        purpose: str,
        tone: str,
        target_section_count: int,
    ) -> dict[str, Any]: ...

    async def generate_longform_plan(
        self,
        *,
        topic: str,
        project_id: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, Any]],
        audience: str,
        purpose: str,
        tone: str,
        target_section_count: int,
        on_token: TokenCallback,
    ) -> LongFormPlan: ...

    async def repair_longform_plan(
        self,
        *,
        topic: str,
        project_id: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, Any]],
        audience: str,
        purpose: str,
        tone: str,
        target_section_count: int,
        previous_response: str,
        error_category: str,
        error_details: list[str],
    ) -> LongFormPlan: ...

    async def critique_longform_plan(
        self,
        *,
        topic: str,
        audience: str,
        purpose: str,
        tone: str,
        target_section_count: int,
        plan: LongFormPlan,
    ) -> LongFormPlan: ...

    async def generate_section_draft(
        self,
        *,
        topic: str,
        project_id: str,
        audience: str,
        purpose: str,
        tone: str,
        plan: LongFormPlan,
        section_id: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, Any]],
    ) -> LongFormDraftSection: ...

    async def revise_section_draft(
        self,
        *,
        topic: str,
        project_id: str,
        audience: str,
        purpose: str,
        tone: str,
        plan: LongFormPlan,
        current_section: LongFormDraftSection,
        instruction: str,
        preserve_structure: bool,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, Any]],
    ) -> LongFormDraftSection: ...

    async def generate_structure_expansion(
        self,
        *,
        generation_goal: str,
        project_id: str,
        source_scope: dict[str, Any],
        evidence_refs: list[str],
        anchor_context: StructureExpansionAnchorContext,
        constraints: dict[str, Any],
        requested_output_shape: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, Any]],
    ) -> StructureExpansionResult: ...

    async def generate_item_generation(
        self,
        *,
        generation_goal: str,
        project_id: str,
        source_scope: dict[str, Any],
        evidence_refs: list[str],
        constraints: dict[str, Any],
        requested_output_shape: str,
        rag_source_ids: list[str],
        rag_context_snippets: list[dict[str, Any]],
    ) -> ItemGenerationResult: ...

