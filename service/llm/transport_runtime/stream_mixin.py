from __future__ import annotations

import json

import httpx

from ..types import LLMEmptyResponseError


class LLMOpenAIStreamMixin:
    async def _chat_stream_text(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float,
        on_token,
    ) -> str:
        if self.api_style == "anthropic_messages":
            text = self._clean_response_text(
                await self._anthropic_text(messages=messages, temperature=temperature)
            )
            for token in text.split():
                await on_token(token + " ")
            return text

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        endpoint = self._openai_completions_endpoint()

        chunks: list[str] = []
        async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
            async with client.stream("POST", endpoint, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    part = json.loads(raw)
                    token = part.get("choices", [{}])[0].get("delta", {}).get(
                        "content", ""
                    )
                    if token:
                        chunks.append(token)
                        await on_token(token)
        text = self._clean_response_text("".join(chunks))
        if not text:
            raise LLMEmptyResponseError(
                phase="chat.stream",
                reason="stream completed without visible text",
            )
        return text
