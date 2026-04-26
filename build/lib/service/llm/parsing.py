from __future__ import annotations

import json
import re
from typing import Any

from ..models import SlidePageType

def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = _sanitize_llm_text(text)
    if stripped.startswith("```"):
        lines = [line for line in stripped.splitlines() if not line.strip().startswith("```")]
        stripped = "\n".join(lines).strip()

    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("model response does not contain a JSON object")
    return json.loads(stripped[start : end + 1])


def _normalize_page_type(raw: str | None) -> SlidePageType:
    if not raw:
        return SlidePageType.CONTENT
    value = raw.strip().lower()
    mapping = {
        "cover": SlidePageType.COVER,
        "toc": SlidePageType.TOC,
        "section": SlidePageType.SECTION,
        "content": SlidePageType.CONTENT,
        "summary": SlidePageType.SUMMARY,
    }
    return mapping.get(value, SlidePageType.CONTENT)


def _extract_code_block(text: str) -> str:
    stripped = _sanitize_llm_text(text)
    if not stripped:
        return stripped
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        while lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return _sanitize_llm_text("\n".join(lines))
    return stripped


def _sanitize_llm_text(text: str) -> str:
    cleaned = str(text or "").replace("\ufeff", "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"(?is)<think\b[^>]*>.*?</think>", "", cleaned)
    cleaned = re.sub(r"(?is)</?think\b[^>]*>", "", cleaned)
    return cleaned.strip()


def _extract_js_module(text: str) -> str:
    cleaned = _extract_code_block(text)
    if not cleaned:
        return cleaned

    anchors = ("const pptxgen", "const slideConfig", "function createSlide", "module.exports")
    start_indices = [cleaned.find(token) for token in anchors if cleaned.find(token) != -1]
    start_idx = min(start_indices) if start_indices else 0
    body = cleaned[start_idx:].strip()

    module_idx = body.rfind("module.exports")
    if module_idx != -1:
        end_line = body.find("\n", module_idx)
        if end_line == -1:
            return body.strip()
        return body[:end_line].strip() + "\n"
    return body


