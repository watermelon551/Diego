from __future__ import annotations

from pydantic import ValidationError

from ...design.skill_profile import enforce_layout_variety
from ...design.style_catalog import resolve_style_dna_choice
from ...models import OutlineDocument, OutlineNode, SlidePageType
from ..parsing import _extract_json_object
from ..pptd_outline_quality import (
    has_strong_content_signal,
    has_toc_signal,
    normalize_pptd_outline_nodes,
)
from ..types import OutlineFormatError


class LLMOutlineDocumentNormalizationMixin:
    def _fit_outline(
        self,
        outline: OutlineDocument,
        *,
        topic: str,
        target_slide_count: int,
        template_style: str,
    ) -> OutlineDocument:
        nodes = list(outline.nodes)
        if len(nodes) > target_slide_count:
            nodes = nodes[:target_slide_count]
        while len(nodes) < target_slide_count:
            idx = len(nodes) + 1
            nodes.append(
                OutlineNode(
                    title=f"{topic} - Section {idx}",
                    bullets=[f"Point {idx}.1", f"Point {idx}.2"],
                    page_type=SlidePageType.CONTENT,
                    layout_hint="content-two-column",
                )
            )
        self._assign_page_types(nodes)
        style_dna = resolve_style_dna_choice(
            "auto",
            template_style=template_style,
            seed=f"{topic}|{target_slide_count}|outline",
        )
        enforce_layout_variety(
            nodes=nodes,
            seed=f"{topic}|{target_slide_count}",
            style_dna_id=style_dna.id,
        )
        normalize_pptd_outline_nodes(nodes)
        return OutlineDocument(
            version=max(1, outline.version),
            summary=outline.summary,
            nodes=nodes,
        )

    def _parse_outline_or_raise(
        self,
        *,
        text: str,
        topic: str,
        target_slide_count: int,
        template_style: str,
    ) -> OutlineDocument:
        try:
            payload = _extract_json_object(text)
        except Exception as exc:
            raise OutlineFormatError(
                category="parse",
                details=[str(exc)],
                raw_response=text,
            ) from exc
        try:
            outline = OutlineDocument.model_validate(payload)
        except ValidationError as exc:
            details: list[str] = []
            for item in exc.errors():
                loc = ".".join(str(x) for x in item.get("loc", ()))
                msg = str(item.get("msg", "validation error"))
                details.append(f"{loc}: {msg}")
            if not details:
                details = [str(exc)]
            raise OutlineFormatError(
                category="schema",
                details=details[:10],
                raw_response=text,
            ) from exc
        return self._fit_outline(
            outline,
            topic=topic,
            target_slide_count=target_slide_count,
            template_style=template_style,
        )

    def _assign_page_types(self, nodes: list[OutlineNode]) -> None:
        if not nodes:
            return
        nodes[0].page_type = SlidePageType.COVER
        if len(nodes) > 1:
            if has_toc_signal(nodes[1]) or (
                len(nodes) >= 5 and not has_strong_content_signal(nodes[1])
            ):
                nodes[1].page_type = SlidePageType.TOC
            elif nodes[1].page_type == SlidePageType.TOC:
                nodes[1].page_type = SlidePageType.CONTENT
        if len(nodes) > 2:
            nodes[-1].page_type = SlidePageType.SUMMARY
        for idx in range(2, len(nodes) - 1):
            if nodes[idx].page_type == SlidePageType.SECTION and has_strong_content_signal(nodes[idx]):
                nodes[idx].page_type = SlidePageType.CONTENT
                continue
            if (
                idx % 4 == 0
                and nodes[idx].page_type == SlidePageType.CONTENT
                and not has_strong_content_signal(nodes[idx])
            ):
                nodes[idx].page_type = SlidePageType.SECTION
            elif nodes[idx].page_type not in {
                SlidePageType.SECTION,
                SlidePageType.CONTENT,
            }:
                nodes[idx].page_type = SlidePageType.CONTENT
