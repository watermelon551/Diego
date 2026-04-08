from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

import httpx

from .models import OutlineDocument, OutlineNode

TokenCallback = Callable[[str], Awaitable[None]]


@dataclass
class GeneratedSlide:
    title: str
    bullets: list[str]
    citations: list[str]


class LLMClient(Protocol):
    async def generate_outline(
        self,
        *,
        topic: str,
        project_id: str,
        rag_source_ids: list[str],
        template_style: str,
        target_slide_count: int,
        on_token: TokenCallback,
    ) -> OutlineDocument: ...

    async def generate_slide(
        self,
        *,
        topic: str,
        project_id: str,
        template_style: str,
        slide_no: int,
        target_slide_count: int,
        outline_node: OutlineNode,
        rag_source_ids: list[str],
    ) -> GeneratedSlide: ...


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
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


class OpenAICompatibleLLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_sec: float = 60.0,
        outline_temperature: float = 0.3,
        slide_temperature: float = 0.6,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_sec = timeout_sec
        self.outline_temperature = outline_temperature
        self.slide_temperature = slide_temperature

    async def generate_outline(
        self,
        *,
        topic: str,
        project_id: str,
        rag_source_ids: list[str],
        template_style: str,
        target_slide_count: int,
        on_token: TokenCallback,
    ) -> OutlineDocument:
        system_prompt = (
            "You are a presentation outline generator. "
            "Return strict JSON only with keys: version(int), summary(str), nodes(list). "
            "Each node must contain title(str), bullets(list[str]). "
            f"nodes length must be exactly {target_slide_count}."
        )
        user_prompt = (
            f"topic={topic}\n"
            f"project_id={project_id}\n"
            f"template_style={template_style}\n"
            f"target_slide_count={target_slide_count}\n"
            f"rag_source_ids={json.dumps(rag_source_ids, ensure_ascii=False)}\n"
            "Output only JSON."
        )
        text = await self._chat_stream_text(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.outline_temperature,
            on_token=on_token,
        )
        payload = _extract_json_object(text)
        outline = OutlineDocument.model_validate(payload)
        return self._fit_outline(outline, topic=topic, target_slide_count=target_slide_count)

    async def generate_slide(
        self,
        *,
        topic: str,
        project_id: str,
        template_style: str,
        slide_no: int,
        target_slide_count: int,
        outline_node: OutlineNode,
        rag_source_ids: list[str],
    ) -> GeneratedSlide:
        system_prompt = (
            "You are a PPT slide writer. "
            "Return strict JSON only with keys: title(str), bullets(list[str]), citations(list[str])."
        )
        user_prompt = (
            f"topic={topic}\n"
            f"project_id={project_id}\n"
            f"template_style={template_style}\n"
            f"slide_no={slide_no}\n"
            f"target_slide_count={target_slide_count}\n"
            f"outline_title={outline_node.title}\n"
            f"outline_bullets={json.dumps(outline_node.bullets, ensure_ascii=False)}\n"
            f"rag_source_ids={json.dumps(rag_source_ids, ensure_ascii=False)}\n"
            "Output only JSON."
        )
        text = await self._chat_text(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.slide_temperature,
        )
        payload = _extract_json_object(text)
        title = str(payload.get("title", "")).strip() or outline_node.title
        bullets = payload.get("bullets", [])
        if not isinstance(bullets, list):
            bullets = []
        bullets = [str(item).strip() for item in bullets if str(item).strip()]
        if not bullets:
            bullets = outline_node.bullets or [f"{title} key point 1", f"{title} key point 2"]

        citations_raw = payload.get("citations", [])
        if not isinstance(citations_raw, list):
            citations_raw = []
        citations = [str(item).strip() for item in citations_raw if str(item).strip()]
        return GeneratedSlide(title=title, bullets=bullets, citations=citations)

    async def _chat_text(self, *, messages: list[dict[str, str]], temperature: float) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_sec) as client:
            resp = await client.post("/v1/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
        return str(body["choices"][0]["message"]["content"])

    async def _chat_stream_text(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float,
        on_token: TokenCallback,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        chunks: list[str] = []
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_sec) as client:
            async with client.stream("POST", "/v1/chat/completions", json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    part = json.loads(raw)
                    token = (
                        part.get("choices", [{}])[0]
                        .get("delta", {})
                        .get("content", "")
                    )
                    if token:
                        chunks.append(token)
                        await on_token(token)
        return "".join(chunks)

    def _fit_outline(self, outline: OutlineDocument, *, topic: str, target_slide_count: int) -> OutlineDocument:
        nodes = list(outline.nodes)
        if len(nodes) > target_slide_count:
            nodes = nodes[:target_slide_count]
        while len(nodes) < target_slide_count:
            idx = len(nodes) + 1
            nodes.append(OutlineNode(title=f"{topic} - Section {idx}", bullets=[f"Point {idx}.1", f"Point {idx}.2"]))
        return OutlineDocument(version=max(1, outline.version), summary=outline.summary, nodes=nodes)


class MockLLMClient:
    async def generate_outline(
        self,
        *,
        topic: str,
        project_id: str,
        rag_source_ids: list[str],
        template_style: str,
        target_slide_count: int,
        on_token: TokenCallback,
    ) -> OutlineDocument:
        for token in ["生成", "大纲", "中", "...", topic]:
            await on_token(token)
        nodes = [
            OutlineNode(title=f"{topic} - Section {i}", bullets=[f"Point {i}.1", f"Point {i}.2"])
            for i in range(1, target_slide_count + 1)
        ]
        return OutlineDocument(version=1, summary=f"Auto outline for {topic}", nodes=nodes)

    async def generate_slide(
        self,
        *,
        topic: str,
        project_id: str,
        template_style: str,
        slide_no: int,
        target_slide_count: int,
        outline_node: OutlineNode,
        rag_source_ids: list[str],
    ) -> GeneratedSlide:
        return GeneratedSlide(
            title=outline_node.title,
            bullets=outline_node.bullets or [f"Point {slide_no}.1", f"Point {slide_no}.2"],
            citations=[],
        )
