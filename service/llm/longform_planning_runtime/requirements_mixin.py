from __future__ import annotations

import json
from typing import Any


class LLMLongFormRequirementsMixin:
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
    ) -> dict[str, Any]:
        system_prompt = (
            "You are a long-form drafting research planner. "
            "Return JSON only with keys: audience, purpose, tone, narrative_arc, section_focus(list[str]), source_themes(list[str]). "
            "Ground section_focus and source_themes in rag_context_snippets when present."
        )
        user_prompt = (
            f"topic={topic}\n"
            f"project_id={project_id}\n"
            f"audience={audience}\n"
            f"purpose={purpose}\n"
            f"tone={tone}\n"
            f"target_section_count={target_section_count}\n"
            f"rag_source_ids={json.dumps(rag_source_ids, ensure_ascii=False)}\n"
            f"rag_context_snippets={json.dumps(rag_context_snippets, ensure_ascii=False)}\n"
            "Provide concise planning guidance for a structured long-form draft."
        )
        text = await self._chat_text(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.outline_temperature,
        )
        payload = await self._extract_json_object_with_repair(
            text=text,
            expected_keys=[
                "audience",
                "purpose",
                "tone",
                "narrative_arc",
                "section_focus",
                "source_themes",
            ],
            temperature=self.outline_temperature,
        )
        section_focus = payload.get("section_focus", [])
        source_themes = payload.get("source_themes", [])
        if not isinstance(section_focus, list):
            section_focus = []
        if not isinstance(source_themes, list):
            source_themes = []
        return {
            "audience": str(payload.get("audience", "")).strip() or audience,
            "purpose": str(payload.get("purpose", "")).strip() or purpose,
            "tone": str(payload.get("tone", "")).strip() or tone,
            "narrative_arc": str(payload.get("narrative_arc", "")).strip()
            or "context -> key ideas -> evidence -> synthesis",
            "section_focus": [
                str(item).strip() for item in section_focus if str(item).strip()
            ][:target_section_count],
            "source_themes": [
                str(item).strip() for item in source_themes if str(item).strip()
            ][:8],
        }
