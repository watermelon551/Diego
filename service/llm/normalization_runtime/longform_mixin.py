from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ...models import (
    ContentBlock,
    LongFormDraftSection,
    LongFormPlan,
    LongFormPlanSection,
)
from ..parsing import _extract_json_object
from ..types import LongFormFormatError


class LLMLongFormNormalizationMixin:
    def _fit_longform_plan(
        self,
        plan: LongFormPlan,
        *,
        topic: str,
        target_section_count: int,
        rag_context_snippets: list[dict[str, Any]],
    ) -> LongFormPlan:
        sections = list(plan.sections)
        default_refs = [
            str(item.get("chunk_id") or item.get("source_id") or f"src-{idx}")
            for idx, item in enumerate(rag_context_snippets[:2], start=1)
        ]
        if len(sections) > target_section_count:
            sections = sections[:target_section_count]
        while len(sections) < target_section_count:
            idx = len(sections) + 1
            sections.append(
                LongFormPlanSection(
                    section_id=f"section-{idx}",
                    title=f"{topic} - Section {idx}",
                    summary=f"Explain theme {idx} of {topic}.",
                    key_points=[f"{topic} point {idx}.1", f"{topic} point {idx}.2"],
                    intent=f"clarify theme {idx}",
                    source_refs=list(default_refs),
                )
            )
        normalized: list[LongFormPlanSection] = []
        for idx, section in enumerate(sections, start=1):
            normalized.append(
                LongFormPlanSection(
                    section_id=str(section.section_id or f"section-{idx}").strip()
                    or f"section-{idx}",
                    title=str(section.title or f"{topic} - Section {idx}").strip()
                    or f"{topic} - Section {idx}",
                    summary=str(section.summary or "").strip(),
                    key_points=[
                        str(item).strip()
                        for item in list(section.key_points or [])
                        if str(item).strip()
                    ][:6]
                    or [f"{topic} point {idx}.1", f"{topic} point {idx}.2"],
                    intent=str(section.intent or "").strip() or f"clarify theme {idx}",
                    source_refs=[
                        str(item).strip()
                        for item in list(section.source_refs or [])
                        if str(item).strip()
                    ][:4]
                    or list(default_refs),
                )
            )
        return LongFormPlan(
            version=max(1, plan.version),
            title=str(plan.title or topic).strip() or topic,
            summary=str(plan.summary or "").strip(),
            sections=normalized,
        )

    def _parse_longform_plan_or_raise(
        self,
        *,
        text: str,
        topic: str,
        target_section_count: int,
        rag_context_snippets: list[dict[str, Any]],
    ) -> LongFormPlan:
        try:
            payload = _extract_json_object(text)
        except Exception as exc:
            raise LongFormFormatError(
                category="parse",
                details=[str(exc)],
                raw_response=text,
            ) from exc
        try:
            plan = LongFormPlan.model_validate(payload)
        except ValidationError as exc:
            details: list[str] = []
            for item in exc.errors():
                loc = ".".join(str(x) for x in item.get("loc", ()))
                msg = str(item.get("msg", "validation error"))
                details.append(f"{loc}: {msg}")
            if not details:
                details = [str(exc)]
            raise LongFormFormatError(
                category="schema",
                details=details[:10],
                raw_response=text,
            ) from exc
        return self._fit_longform_plan(
            plan,
            topic=topic,
            target_section_count=target_section_count,
            rag_context_snippets=rag_context_snippets,
        )

    def _parse_longform_section_or_raise(
        self,
        *,
        text: str,
        section_id: str,
        heading: str,
        key_points: list[str],
        source_refs: list[str],
    ) -> LongFormDraftSection:
        try:
            payload = _extract_json_object(text)
        except Exception as exc:
            raise LongFormFormatError(
                category="parse",
                details=[str(exc)],
                raw_response=text,
            ) from exc
        return self._parse_longform_section_payload_or_raise(
            payload=payload,
            section_id=section_id,
            heading=heading,
            key_points=key_points,
            source_refs=source_refs,
            raw_response=text,
        )

    def _parse_longform_section_payload_or_raise(
        self,
        *,
        payload: dict[str, Any],
        section_id: str,
        heading: str,
        key_points: list[str],
        source_refs: list[str],
        raw_response: str,
    ) -> LongFormDraftSection:
        try:
            section = LongFormDraftSection.model_validate(
                self._normalize_longform_section_payload(payload)
            )
        except ValidationError as exc:
            details: list[str] = []
            for item in exc.errors():
                loc = ".".join(str(x) for x in item.get("loc", ()))
                msg = str(item.get("msg", "validation error"))
                details.append(f"{loc}: {msg}")
            if not details:
                details = [str(exc)]
            raise LongFormFormatError(
                category="schema",
                details=details[:10],
                raw_response=raw_response,
            ) from exc
        normalized_blocks = list(section.blocks or [])
        if not normalized_blocks:
            normalized_blocks = [
                ContentBlock(kind="heading", text=heading),
                ContentBlock(
                    kind="paragraph",
                    text=f"{heading} explains the section scope clearly.",
                ),
                ContentBlock(kind="bullet_list", items=list(key_points or [heading])),
            ]
        return LongFormDraftSection(
            section_id=section_id,
            heading=str(section.heading or heading).strip() or heading,
            blocks=normalized_blocks,
            citations=[
                str(item).strip()
                for item in list(section.citations or [])
                if str(item).strip()
            ][:6]
            or list(source_refs),
            revision=max(1, int(section.revision or 1)),
        )

    def _normalize_longform_section_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        blocks: list[dict[str, Any]] = []
        for raw in self._list_payload_items(payload.get("blocks")):
            if not isinstance(raw, dict):
                text = self._text_value(raw)
                if text:
                    blocks.append({"kind": "paragraph", "text": text})
                continue
            kind = self._text_value(raw.get("kind")) or "paragraph"
            if kind not in {"heading", "paragraph", "bullet_list", "quote"}:
                kind = "bullet_list" if raw.get("items") else "paragraph"
            if kind == "bullet_list":
                items = [
                    text
                    for item in self._list_payload_items(raw.get("items"))
                    if (text := self._text_value(item))
                ]
                if not items and (text := self._text_value(raw.get("text"))):
                    items = [text]
                if items:
                    blocks.append({"kind": "bullet_list", "items": items})
                continue
            text = self._text_value(raw.get("text")) or self._text_value(raw.get("content"))
            if not text and raw.get("items"):
                text = "；".join(
                    text
                    for item in self._list_payload_items(raw.get("items"))
                    if (text := self._text_value(item))
                )
            if text:
                blocks.append({"kind": kind, "text": text})

        normalized = dict(payload)
        normalized["section_id"] = self._text_value(payload.get("section_id"))
        normalized["heading"] = self._text_value(payload.get("heading")) or self._text_value(payload.get("title"))
        normalized["blocks"] = blocks
        normalized["citations"] = [
            text
            for item in self._list_payload_items(payload.get("citations"))
            if (text := self._text_value(item))
        ]
        normalized["revision"] = self._positive_int(payload.get("revision"), default=1)
        return normalized

    def _list_payload_items(self, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

    def _text_value(self, value: Any) -> str:
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
                "title",
                "label",
                "name",
                "value",
                "summary",
                "id",
                "source_id",
                "chunk_id",
            ):
                text = self._text_value(value.get(key))
                if text:
                    return text
        return str(value).strip()

    def _positive_int(self, value: Any, *, default: int) -> int:
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return max(1, value)
        if isinstance(value, float):
            return max(1, int(value))
        text = self._text_value(value)
        if text.isdigit():
            return max(1, int(text))
        return default
