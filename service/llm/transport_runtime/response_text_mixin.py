from __future__ import annotations

from typing import Any

import httpx

from ..parsing import _sanitize_llm_text


class LLMResponseTextMixin:
    def _response_content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text", "")
                    if text:
                        chunks.append(str(text))
                elif part:
                    chunks.append(str(part))
            return "".join(chunks)
        return str(content)

    def _clean_response_text(self, text: str) -> str:
        if not self.sanitize_think_tags:
            return str(text or "").replace("\ufeff", "").strip()
        return _sanitize_llm_text(text)

    def _is_response_format_unsupported(self, exc: httpx.HTTPStatusError) -> bool:
        status = exc.response.status_code
        if status not in {400, 404, 415, 422}:
            return False
        body = ""
        try:
            body = exc.response.text
        except Exception:
            body = ""
        hint = body.lower()
        return (
            "response_format" in hint or "json_schema" in hint or "schema" in hint
        )

    def _openai_completions_endpoint(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def _anthropic_messages_endpoint(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/messages"
        return f"{self.base_url}/v1/messages"
