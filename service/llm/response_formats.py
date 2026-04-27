from __future__ import annotations

from typing import Any

from ..models import SlidePageType


class LLMStructuredOutputMixin:
    def _outline_response_format(
        self, *, target_slide_count: int
    ) -> dict[str, Any] | None:
        if not self.outline_structured_output or self.api_style == "anthropic_messages":
            return None
        if "minimax" in self.model.lower():
            return {"type": "json_object"}

        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "version": {"type": "integer", "minimum": 1},
                "summary": {"type": "string"},
                "nodes": {
                    "type": "array",
                    "minItems": target_slide_count,
                    "maxItems": target_slide_count,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "title": {"type": "string"},
                            "bullets": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "page_type": {
                                "type": "string",
                                "enum": [
                                    SlidePageType.COVER.value,
                                    SlidePageType.TOC.value,
                                    SlidePageType.SECTION.value,
                                    SlidePageType.CONTENT.value,
                                    SlidePageType.SUMMARY.value,
                                ],
                            },
                            "layout_hint": {"type": ["string", "null"]},
                        },
                        "required": ["title", "bullets", "page_type", "layout_hint"],
                    },
                },
            },
            "required": ["version", "summary", "nodes"],
        }
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "outline_document",
                "strict": True,
                "schema": schema,
            },
        }

    def _longform_plan_response_format(
        self, *, target_section_count: int
    ) -> dict[str, Any] | None:
        if not self.outline_structured_output or self.api_style == "anthropic_messages":
            return None
        if "minimax" in self.model.lower():
            return {"type": "json_object"}

        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "version": {"type": "integer", "minimum": 1},
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "sections": {
                    "type": "array",
                    "minItems": target_section_count,
                    "maxItems": target_section_count,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "section_id": {"type": "string"},
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                            "key_points": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "intent": {"type": "string"},
                            "source_refs": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "section_id",
                            "title",
                            "summary",
                            "key_points",
                            "intent",
                            "source_refs",
                        ],
                    },
                },
            },
            "required": ["version", "title", "summary", "sections"],
        }
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "longform_plan",
                "strict": True,
                "schema": schema,
            },
        }

    def _longform_section_response_format(self) -> dict[str, Any] | None:
        if not self.outline_structured_output or self.api_style == "anthropic_messages":
            return None
        if "minimax" in self.model.lower():
            return {"type": "json_object"}

        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "section_id": {"type": "string"},
                "heading": {"type": "string"},
                "blocks": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": [
                                    "heading",
                                    "paragraph",
                                    "bullet_list",
                                    "quote",
                                ],
                            },
                            "text": {"type": "string"},
                            "items": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["kind", "text", "items"],
                    },
                },
                "citations": {"type": "array", "items": {"type": "string"}},
                "revision": {"type": "integer", "minimum": 1},
            },
            "required": ["section_id", "heading", "blocks", "citations", "revision"],
        }
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "longform_section_draft",
                "strict": True,
                "schema": schema,
            },
        }

    def _slide_spec_response_format(self) -> dict[str, Any] | None:
        if not self.outline_structured_output or self.api_style == "anthropic_messages":
            return None
        if "minimax" in self.model.lower():
            return {"type": "json_object"}

        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string"},
                "subtitle": {"type": "string"},
                "bullets": {"type": "array", "items": {"type": "string"}},
                "page_type": {
                    "type": "string",
                    "enum": [
                        SlidePageType.COVER.value,
                        SlidePageType.TOC.value,
                        SlidePageType.SECTION.value,
                        SlidePageType.CONTENT.value,
                        SlidePageType.SUMMARY.value,
                    ],
                },
                "layout_hint": {"type": ["string", "null"]},
                "visual_kind": {
                    "type": "string",
                    "enum": ["image", "chart", "shape"],
                },
                "emphasis": {"type": "string"},
                "citations": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "title",
                "subtitle",
                "bullets",
                "page_type",
                "layout_hint",
                "visual_kind",
                "emphasis",
                "citations",
            ],
        }
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "slide_spec",
                "strict": True,
                "schema": schema,
            },
        }
