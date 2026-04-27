from __future__ import annotations

from typing import Any

from ...models import (
    GeneratedItem,
    ItemGenerationResult,
    StructureExpansionAnchorContext,
    StructureExpansionResult,
    StructureExpansionUnit,
)


class MockStructuredContentGenerationMixin:
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
    ) -> StructureExpansionResult:
        base_refs = [
            str(item.get("chunk_id") or item.get("source_id") or f"src-{idx}")
            for idx, item in enumerate(rag_context_snippets[:2], start=1)
        ] or list(evidence_refs or rag_source_ids[:2])
        anchor = anchor_context.anchor_label.strip() or "selected unit"
        units = [
            StructureExpansionUnit(
                unit_id=f"unit-{idx}",
                title=f"{anchor.title()} expansion {idx}",
                summary=f"Expand {anchor or generation_goal} toward {generation_goal}.",
                key_points=[
                    f"{generation_goal} sub-point {idx}.1",
                    f"{generation_goal} sub-point {idx}.2",
                ],
                source_refs=list(base_refs),
                anchor_ref=anchor,
                revision_target=f"unit-{idx}",
            )
            for idx in range(1, 3)
        ]
        return StructureExpansionResult(
            units=units,
            anchors=[anchor] if anchor else [],
            source_refs=list(base_refs),
            revision_targets=[item.unit_id for item in units],
            warnings=[] if base_refs else ["no_grounding_refs"],
        )

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
    ) -> ItemGenerationResult:
        base_refs = [
            str(item.get("chunk_id") or item.get("source_id") or f"src-{idx}")
            for idx, item in enumerate(rag_context_snippets[:2], start=1)
        ] or list(evidence_refs or rag_source_ids[:2])
        items = [
            GeneratedItem(
                item_id=f"item-{idx}",
                stem=f"What is the key idea {idx} in {generation_goal}?",
                choices=[
                    f"{generation_goal} answer {idx}.A",
                    f"{generation_goal} answer {idx}.B",
                    f"{generation_goal} answer {idx}.C",
                ],
                expected_response=f"{generation_goal} answer {idx}.A",
                expected_response_hints=[f"focus on {generation_goal} concept {idx}"],
                explanation=f"The expected answer should reflect the grounded idea {idx}.",
                source_refs=list(base_refs),
                difficulty="medium",
                intent="check understanding",
            )
            for idx in range(1, 3)
        ]
        return ItemGenerationResult(
            items=items,
            source_refs=list(base_refs),
            revision_targets=[item.item_id for item in items],
            warnings=[] if base_refs else ["no_grounding_refs"],
        )
