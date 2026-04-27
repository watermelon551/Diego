from __future__ import annotations

import json
import re
from typing import Any

from ....design.skill_profile import allowed_layouts_for
from ....llm import GeneratedSlide
from ....models import OutlineNode, SlidePageType


class QualitySlideCandidateParsingMixin:
    def extract_candidate_from_js(
        self, *, js_code: str, fallback_node: OutlineNode, citations: list[str]
    ) -> GeneratedSlide:
        title = self.extract_js_string_field(js_code, "title") or fallback_node.title
        layout_hint = self.extract_js_string_field(js_code, "layoutHint") or fallback_node.layout_hint
        bullets = self.extract_js_array_field(js_code, "bullets")
        if not bullets:
            bullets = list(fallback_node.bullets)
        return GeneratedSlide(
            title=title,
            bullets=bullets,
            citations=list(citations),
            page_type=fallback_node.page_type,
            layout_hint=layout_hint,
        )

    def extract_js_string_field(self, js_code: str, field_name: str) -> str | None:
        match = re.search(
            rf"{re.escape(field_name)}\s*:\s*(['\"])(.*?)\1",
            js_code,
            flags=re.DOTALL,
        )
        if not match:
            return None
        raw = match.group(2)
        try:
            return json.loads(f'"{raw}"')
        except json.JSONDecodeError:
            return raw

    def extract_js_array_field(self, js_code: str, field_name: str) -> list[str]:
        match = re.search(rf"{re.escape(field_name)}\s*:\s*(\[[\s\S]*?\])\s*,", js_code)
        if not match:
            return []
        raw = match.group(1)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(item).strip() for item in parsed if str(item).strip()]

    def check_slide_content_rules(
        self, candidate: GeneratedSlide, node: OutlineNode
    ) -> list[str]:
        issues: list[str] = []
        if not candidate.title.strip():
            issues.append("title is empty")
        if len(candidate.bullets) < 2 and node.page_type in {
            SlidePageType.CONTENT,
            SlidePageType.SUMMARY,
            SlidePageType.TOC,
        }:
            issues.append("not enough bullet points")
        if candidate.page_type != node.page_type:
            issues.append(
                f"page_type mismatch expected={node.page_type.value} got={candidate.page_type.value}"
            )
        allowed_layouts = allowed_layouts_for(node.page_type)
        if candidate.layout_hint and candidate.layout_hint not in allowed_layouts:
            issues.append(
                f"layout_hint invalid for {node.page_type.value}: {candidate.layout_hint}"
            )
        return issues
