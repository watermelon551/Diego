from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

import httpx

from .models import OutlineDocument, OutlineNode, SlidePageType
from .skill_profile import allowed_layouts_for, enforce_layout_variety

TokenCallback = Callable[[str], Awaitable[None]]


@dataclass
class GeneratedSlide:
    title: str
    bullets: list[str]
    citations: list[str]
    page_type: SlidePageType
    layout_hint: str | None = None


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

    async def critique_outline(
        self,
        *,
        topic: str,
        template_style: str,
        target_slide_count: int,
        outline: OutlineDocument,
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

    async def review_slide(
        self,
        *,
        topic: str,
        template_style: str,
        slide_no: int,
        target_slide_count: int,
        outline_node: OutlineNode,
        candidate: GeneratedSlide,
        rule_violations: list[str],
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


class OpenAICompatibleLLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        api_style: str = "openai_chat",
        timeout_sec: float = 60.0,
        outline_temperature: float = 0.3,
        slide_temperature: float = 0.6,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.api_style = api_style
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
            "You are a PPT planner following strict slide types. "
            "Return JSON only with keys: version, summary, nodes. "
            "Each node: title, bullets(list[str]), page_type(one of cover,toc,section,content,summary), layout_hint. "
            f"nodes length must equal {target_slide_count}. "
            "Layout hints must use skill-approved values only."
        )
        user_prompt = (
            f"topic={topic}\n"
            f"project_id={project_id}\n"
            f"template_style={template_style}\n"
            f"target_slide_count={target_slide_count}\n"
            f"rag_source_ids={json.dumps(rag_source_ids, ensure_ascii=False)}\n"
            "Plan varied layouts and avoid repeating adjacent layouts. Output JSON only."
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

    async def critique_outline(
        self,
        *,
        topic: str,
        template_style: str,
        target_slide_count: int,
        outline: OutlineDocument,
    ) -> OutlineDocument:
        system_prompt = (
            "You are a QA reviewer for PPT outlines. "
            "Ensure page types are well-distributed and avoid repetitive layouts. "
            "Return JSON only with the same schema. "
            "Layout hints must be valid skill layout names."
        )
        user_prompt = (
            f"topic={topic}\n"
            f"template_style={template_style}\n"
            f"target_slide_count={target_slide_count}\n"
            f"outline={outline.model_dump_json()}\n"
            "Return improved outline JSON only."
        )
        text = await self._chat_text(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.outline_temperature,
        )
        payload = _extract_json_object(text)
        improved = OutlineDocument.model_validate(payload)
        return self._fit_outline(improved, topic=topic, target_slide_count=target_slide_count)

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
            "You are a PPT slide content writer. "
            "Return JSON with keys: title, bullets(list[str]), citations(list[str]), page_type, layout_hint. "
            "Never use placeholder wording."
        )
        user_prompt = (
            f"topic={topic}\nproject_id={project_id}\ntemplate_style={template_style}\n"
            f"slide_no={slide_no}\ntarget_slide_count={target_slide_count}\n"
            f"outline_node={outline_node.model_dump_json()}\n"
            f"rag_source_ids={json.dumps(rag_source_ids, ensure_ascii=False)}\n"
            "Output JSON only."
        )
        text = await self._chat_text(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=self.slide_temperature,
        )
        return self._parse_generated_slide(text=text, fallback=outline_node)

    async def review_slide(
        self,
        *,
        topic: str,
        template_style: str,
        slide_no: int,
        target_slide_count: int,
        outline_node: OutlineNode,
        candidate: GeneratedSlide,
        rule_violations: list[str],
    ) -> GeneratedSlide:
        system_prompt = (
            "You are a PPT quality reviewer. "
            "Fix slide content to satisfy style/clarity rules and return JSON with same keys. "
            "Do not output placeholders."
        )
        user_prompt = (
            f"topic={topic}\ntemplate_style={template_style}\nslide_no={slide_no}\n"
            f"target_slide_count={target_slide_count}\noutline_node={outline_node.model_dump_json()}\n"
            f"candidate={json.dumps(candidate.__dict__, ensure_ascii=False)}\n"
            f"rule_violations={json.dumps(rule_violations, ensure_ascii=False)}\n"
            "Output corrected JSON only."
        )
        text = await self._chat_text(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=self.slide_temperature,
        )
        return self._parse_generated_slide(text=text, fallback=outline_node)

    def _parse_generated_slide(self, *, text: str, fallback: OutlineNode) -> GeneratedSlide:
        payload = _extract_json_object(text)
        title = str(payload.get("title", "")).strip() or fallback.title
        bullets_raw = payload.get("bullets", [])
        if not isinstance(bullets_raw, list):
            bullets_raw = []
        bullets = [str(item).strip() for item in bullets_raw if str(item).strip()]
        if not bullets:
            bullets = fallback.bullets or [f"{title} point 1", f"{title} point 2"]

        citations_raw = payload.get("citations", [])
        if not isinstance(citations_raw, list):
            citations_raw = []
        citations = [str(item).strip() for item in citations_raw if str(item).strip()]
        page_type = _normalize_page_type(str(payload.get("page_type", "")))
        layout_hint = self._normalize_layout_hint(
            raw=str(payload.get("layout_hint", "")).strip(),
            page_type=page_type,
            fallback=fallback.layout_hint,
        )
        return GeneratedSlide(
            title=title,
            bullets=bullets,
            citations=citations,
            page_type=page_type,
            layout_hint=layout_hint,
        )

    async def _chat_text(self, *, messages: list[dict[str, str]], temperature: float) -> str:
        if self.api_style == "anthropic_messages":
            return await self._anthropic_text(messages=messages, temperature=temperature)
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        endpoint = self._openai_completions_endpoint()
        async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
            resp = await client.post(endpoint, json=payload, headers=headers)
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
        if self.api_style == "anthropic_messages":
            text = await self._anthropic_text(messages=messages, temperature=temperature)
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
                    token = part.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if token:
                        chunks.append(token)
                        await on_token(token)
        return "".join(chunks)

    async def _anthropic_text(self, *, messages: list[dict[str, str]], temperature: float) -> str:
        system = ""
        converted_messages: list[dict[str, str]] = []
        for item in messages:
            if item["role"] == "system":
                system += item["content"] + "\n"
            else:
                converted_messages.append({"role": item["role"], "content": item["content"]})
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
            texts = [str(part.get("text", "")) for part in content if isinstance(part, dict)]
            return "".join(texts)
        return str(content)

    def _openai_completions_endpoint(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def _anthropic_messages_endpoint(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/messages"
        return f"{self.base_url}/v1/messages"

    def _fit_outline(self, outline: OutlineDocument, *, topic: str, target_slide_count: int) -> OutlineDocument:
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
        enforce_layout_variety(nodes=nodes, seed=f"{topic}|{target_slide_count}")
        return OutlineDocument(version=max(1, outline.version), summary=outline.summary, nodes=nodes)

    def _assign_page_types(self, nodes: list[OutlineNode]) -> None:
        if not nodes:
            return
        nodes[0].page_type = SlidePageType.COVER
        if len(nodes) > 1:
            nodes[1].page_type = SlidePageType.TOC
        if len(nodes) > 2:
            nodes[-1].page_type = SlidePageType.SUMMARY
        for i in range(2, len(nodes) - 1):
            if i % 4 == 0:
                nodes[i].page_type = SlidePageType.SECTION
            elif nodes[i].page_type not in {SlidePageType.SECTION, SlidePageType.CONTENT}:
                nodes[i].page_type = SlidePageType.CONTENT

    def _normalize_layout_hint(self, *, raw: str, page_type: SlidePageType, fallback: str | None) -> str | None:
        allowed = allowed_layouts_for(page_type)
        if raw in allowed:
            return raw
        if fallback and fallback in allowed:
            return fallback
        return allowed[0] if allowed else None


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
        nodes: list[OutlineNode] = []
        for i in range(1, target_slide_count + 1):
            nodes.append(
                OutlineNode(
                    title=f"{topic} - Section {i}",
                    bullets=[f"Point {i}.1", f"Point {i}.2"],
                    page_type=self._page_type_for_index(i, target_slide_count),
                    layout_hint="content-two-column" if i % 2 == 0 else "content-icon-rows",
                )
            )
        enforce_layout_variety(nodes=nodes, seed=f"{topic}|mock")
        return OutlineDocument(version=1, summary=f"Auto outline for {topic}", nodes=nodes)

    async def critique_outline(
        self,
        *,
        topic: str,
        template_style: str,
        target_slide_count: int,
        outline: OutlineDocument,
    ) -> OutlineDocument:
        return outline

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
            citations=rag_source_ids[:2],
            page_type=outline_node.page_type,
            layout_hint=outline_node.layout_hint,
        )

    async def review_slide(
        self,
        *,
        topic: str,
        template_style: str,
        slide_no: int,
        target_slide_count: int,
        outline_node: OutlineNode,
        candidate: GeneratedSlide,
        rule_violations: list[str],
    ) -> GeneratedSlide:
        if not candidate.bullets:
            candidate.bullets = [f"Point {slide_no}.1"]
        return candidate

    def _page_type_for_index(self, index: int, total: int) -> SlidePageType:
        if index == 1:
            return SlidePageType.COVER
        if index == 2:
            return SlidePageType.TOC
        if index == total:
            return SlidePageType.SUMMARY
        if index % 4 == 0:
            return SlidePageType.SECTION
        return SlidePageType.CONTENT
