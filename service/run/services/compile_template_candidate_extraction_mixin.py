from __future__ import annotations

import re
from pathlib import Path

from ...llm import GeneratedSlide
from ...models import OutlineNode


class CompileTemplateCandidateExtractionMixin:
    def extract_candidate_from_template_slide(
        self,
        *,
        unpacked: Path,
        slide_xml: Path,
        fallback_node: OutlineNode,
        citations: list[str],
    ) -> GeneratedSlide:
        orch = self.orch
        content = slide_xml.read_text(encoding="utf-8", errors="ignore")
        placeholder_re = re.compile(
            r"(placeholder|lorem|ipsum|xxxx|template|caption|insert)",
            flags=re.IGNORECASE,
        )
        raw_texts = [
            orch._xml_unescape(item).strip()
            for item in re.findall(r"<a:t>(.*?)</a:t>", content, flags=re.DOTALL)
        ]
        texts = [item for item in raw_texts if item and not placeholder_re.search(item)]
        chart_texts = self.extract_related_chart_texts(
            unpacked=unpacked, slide_xml=slide_xml
        )
        title = texts[0] if texts else fallback_node.title
        bullets = [item for item in texts[1:] if item != title]
        for item in chart_texts:
            if item and item != title and item not in bullets:
                bullets.append(item)
        if not bullets:
            bullets = list(fallback_node.bullets)
        return GeneratedSlide(
            title=title,
            bullets=bullets,
            citations=list(citations),
            page_type=fallback_node.page_type,
            layout_hint=fallback_node.layout_hint,
        )

    def extract_related_chart_texts(self, *, unpacked: Path, slide_xml: Path) -> list[str]:
        orch = self.orch
        rels_path = slide_xml.parent / "_rels" / f"{slide_xml.name}.rels"
        if not rels_path.exists():
            return []
        rels_text = rels_path.read_text(encoding="utf-8", errors="ignore")
        results: list[str] = []
        for tag in re.findall(r"<Relationship\b[^>]*/>", rels_text):
            attrs = orch._parse_xml_attrs(tag)
            rel_type = attrs.get("Type", "")
            target = attrs.get("Target", "")
            if not rel_type.endswith("/chart") or not target:
                continue
            chart_path = (slide_xml.parent / target).resolve()
            try:
                chart_path.relative_to(unpacked.resolve())
            except ValueError:
                continue
            if not chart_path.exists():
                continue
            chart_xml = chart_path.read_text(encoding="utf-8", errors="ignore")
            for text in re.findall(
                r"<(?:a:t|c:v)>(.*?)</(?:a:t|c:v)>", chart_xml, flags=re.DOTALL
            ):
                normalized = orch._xml_unescape(text).strip()
                if normalized and normalized not in results:
                    results.append(normalized)
        return results
