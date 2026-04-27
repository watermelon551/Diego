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
        try:
            section = LongFormDraftSection.model_validate(payload)
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
            section_id=str(section.section_id or section_id).strip() or section_id,
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
