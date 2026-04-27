from __future__ import annotations

from typing import Any

import httpx

from ..types import LLMEmptyResponseError


class LLMOpenAIChatTextMixin:
    async def _chat_text(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float,
        response_format: dict[str, Any] | None = None,
        allow_response_format_fallback: bool = False,
    ) -> str:
        if self.api_style == "anthropic_messages":
            return await self._anthropic_text(messages=messages, temperature=temperature)
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if response_format and self.outline_structured_output:
            payload["response_format"] = response_format
        headers = {"Authorization": f"Bearer {self.api_key}"}
        endpoint = self._openai_completions_endpoint()
        attempted_fallback = False
        while True:
            try:
                async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                    resp = await client.post(endpoint, json=payload, headers=headers)
                    resp.raise_for_status()
                    body = resp.json()
                content = body["choices"][0]["message"]["content"]
                text = self._clean_response_text(self._response_content_to_text(content))
                if not text:
                    raise LLMEmptyResponseError(
                        phase="chat.text",
                        reason="provider returned empty text content",
                    )
                return text
            except httpx.HTTPStatusError as exc:
                if (
                    allow_response_format_fallback
                    and not attempted_fallback
                    and "response_format" in payload
                    and self._is_response_format_unsupported(exc)
                ):
                    attempted_fallback = True
                    payload.pop("response_format", None)
                    continue
                raise
