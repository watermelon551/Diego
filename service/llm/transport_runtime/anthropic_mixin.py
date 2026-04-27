from __future__ import annotations

from typing import Any

import httpx


class LLMAnthropicTransportMixin:
    async def _anthropic_text(
        self, *, messages: list[dict[str, str]], temperature: float
    ) -> str:
        system = ""
        converted_messages: list[dict[str, str]] = []
        for item in messages:
            if item["role"] == "system":
                system += item["content"] + "\n"
            else:
                converted_messages.append(
                    {"role": item["role"], "content": item["content"]}
                )
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4000,
            "messages": converted_messages,
            "temperature": temperature,
        }
        if system.strip():
            payload["system"] = system.strip()

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        endpoint = self._anthropic_messages_endpoint()
        async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
            resp = await client.post(endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
        content = body.get("content", [])
        if isinstance(content, list):
            texts = [
                str(part.get("text", "")) for part in content if isinstance(part, dict)
            ]
            return "".join(texts)
        return str(content)
