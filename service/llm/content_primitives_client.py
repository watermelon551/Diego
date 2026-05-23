from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from ..models import (
    ItemGenerationResult,
    StructureExpansionAnchorContext,
    StructureExpansionResult,
)
from .format_errors import LongFormFormatError
from .parsing import _extract_json_object


class LLMContentPrimitivesMixin:
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
        system_prompt = (
            "You are Diego's generic structure-expansion primitive. "
            "Expand source-grounded ideas into reusable structure units for an upstream host. "
            "Do not mention any host product internals. Return JSON only with keys: "
            "units, anchors, source_refs, revision_targets, warnings."
        )
        user_prompt = (
            f"generation_goal={generation_goal}\n"
            f"project_id={project_id}\n"
            f"source_scope={json.dumps(source_scope, ensure_ascii=False)}\n"
            f"evidence_refs={json.dumps(evidence_refs, ensure_ascii=False)}\n"
            f"anchor_context={anchor_context.model_dump_json()}\n"
            f"constraints={json.dumps(constraints, ensure_ascii=False)}\n"
            f"requested_output_shape={requested_output_shape}\n"
            f"rag_source_ids={json.dumps(rag_source_ids, ensure_ascii=False)}\n"
            f"rag_context_snippets={json.dumps(rag_context_snippets, ensure_ascii=False)}\n"
            "Produce concise but substantive units. Each unit must have stable unit_id, title, "
            "summary, 2-5 key_points, source_refs, anchor_ref, and revision_target. "
            "If selected_node_path is present, treat this as a node-local replacement expansion."
        )
        text = await self._chat_text(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.slide_temperature,
            response_format=self._structure_expansion_response_format(),
            allow_response_format_fallback=True,
        )
        parsed = _extract_json_object(text)
        try:
            return StructureExpansionResult.model_validate(
                self._normalize_structure_expansion_payload(parsed)
            )
        except ValidationError as exc:
            raise LongFormFormatError(
                category="structure_expansion_schema",
                details=[str(error.get("loc")) for error in exc.errors()],
                raw_response=text,
            ) from exc

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
        system_prompt = (
            "You are Diego's generic item-generation primitive. "
            "Generate source-grounded assessment or interaction items for an upstream host. "
            "Do not own host workflow semantics. Return JSON only with keys: "
            "items, source_refs, revision_targets, warnings."
        )
        user_prompt = (
            f"generation_goal={generation_goal}\n"
            f"project_id={project_id}\n"
            f"source_scope={json.dumps(source_scope, ensure_ascii=False)}\n"
            f"evidence_refs={json.dumps(evidence_refs, ensure_ascii=False)}\n"
            f"constraints={json.dumps(constraints, ensure_ascii=False)}\n"
            f"requested_output_shape={requested_output_shape}\n"
            f"rag_source_ids={json.dumps(rag_source_ids, ensure_ascii=False)}\n"
            f"rag_context_snippets={json.dumps(rag_context_snippets, ensure_ascii=False)}\n"
            "Produce items with stable item_id, stem, choices when applicable, expected_response, "
            "expected_response_hints, explanation, source_refs, difficulty, and intent. "
            "Honor current_question_id as a single-item rewrite anchor when present. "
            "If humorous_distractors is true, distractors may be playful but must remain plausible."
        )
        text = await self._chat_text(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.slide_temperature,
            response_format=self._item_generation_response_format(),
            allow_response_format_fallback=True,
        )
        parsed = _extract_json_object(text)
        try:
            return ItemGenerationResult.model_validate(
                self._normalize_item_generation_payload(parsed)
            )
        except ValidationError as exc:
            raise LongFormFormatError(
                category="item_generation_schema",
                details=[str(error.get("loc")) for error in exc.errors()],
                raw_response=text,
            ) from exc

    def _normalize_structure_expansion_payload(self, parsed: dict[str, Any]) -> dict[str, Any]:
        units: list[dict[str, Any]] = []
        for index, raw in enumerate(self._list_value(parsed.get("units")), start=1):
            if not isinstance(raw, dict):
                continue
            unit_id = self._text(raw.get("unit_id")) or f"unit-{index}"
            units.append(
                {
                    "unit_id": unit_id,
                    "title": self._text(raw.get("title")) or f"Unit {index}",
                    "summary": self._text(raw.get("summary")),
                    "key_points": [self._text(item) for item in self._list_value(raw.get("key_points")) if self._text(item)],
                    "source_refs": self._text_list(raw.get("source_refs")),
                    "anchor_ref": self._text(raw.get("anchor_ref")),
                    "revision_target": self._text(raw.get("revision_target")) or unit_id,
                }
            )
        if not units:
            units.append(
                {
                    "unit_id": "unit-1",
                    "title": "Generated structure",
                    "summary": self._text(parsed.get("summary")),
                    "key_points": [],
                    "source_refs": self._text_list(parsed.get("source_refs")),
                    "anchor_ref": "",
                    "revision_target": "unit-1",
                }
            )
        return {
            "units": units,
            "anchors": self._text_list(parsed.get("anchors")),
            "source_refs": self._text_list(parsed.get("source_refs")),
            "revision_targets": self._text_list(parsed.get("revision_targets"))
            or [item["revision_target"] for item in units],
            "warnings": self._text_list(parsed.get("warnings")),
        }

    def _normalize_item_generation_payload(self, parsed: dict[str, Any]) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for index, raw in enumerate(self._list_value(parsed.get("items")), start=1):
            if not isinstance(raw, dict):
                continue
            item_id = self._text(raw.get("item_id")) or f"item-{index}"
            items.append(
                {
                    "item_id": item_id,
                    "stem": self._text(raw.get("stem")) or f"Item {index}",
                    "choices": self._text_list(raw.get("choices")),
                    "expected_response": self._text(raw.get("expected_response")),
                    "expected_response_hints": self._text_list(raw.get("expected_response_hints")),
                    "explanation": self._text(raw.get("explanation")),
                    "source_refs": self._text_list(raw.get("source_refs")),
                    "difficulty": self._text(raw.get("difficulty")),
                    "intent": self._text(raw.get("intent")),
                }
            )
        if not items:
            items.append(
                {
                    "item_id": "item-1",
                    "stem": self._text(parsed.get("stem")) or "Generated item",
                    "choices": self._text_list(parsed.get("choices")),
                    "expected_response": self._text(parsed.get("expected_response")),
                    "expected_response_hints": self._text_list(parsed.get("expected_response_hints")),
                    "explanation": self._text(parsed.get("explanation")),
                    "source_refs": self._text_list(parsed.get("source_refs")),
                    "difficulty": self._text(parsed.get("difficulty")),
                    "intent": self._text(parsed.get("intent")),
                }
            )
        return {
            "items": items,
            "source_refs": self._text_list(parsed.get("source_refs")),
            "revision_targets": self._text_list(parsed.get("revision_targets"))
            or [item["item_id"] for item in items],
            "warnings": self._text_list(parsed.get("warnings")),
        }

    def _list_value(self, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

    def _text_list(self, value: Any) -> list[str]:
        return [text for item in self._list_value(value) if (text := self._text(item))]

    def _text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, dict):
            for key in (
                "text",
                "content",
                "choice",
                "answer",
                "value",
                "title",
                "label",
                "name",
                "id",
                "source_id",
                "chunk_id",
                "unit_id",
                "item_id",
            ):
                text = self._text(value.get(key))
                if text:
                    return text
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return str(value).strip()
