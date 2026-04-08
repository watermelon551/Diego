from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import load_settings
from .llm_client import GeneratedSlide, LLMClient, OpenAICompatibleLLMClient
from .models import (
    ConfirmOutlineRequest,
    CreateRunRequest,
    EventType,
    OutlineNode,
    RunDetailResponse,
    RunEvent,
    RunRecord,
    RunStatus,
    RunSummaryResponse,
    SlideArtifact,
)
from .pptx_builder import build_pptx
from .store import RunStore, now_iso


class RunOrchestrator:
    def __init__(
        self,
        store: RunStore,
        artifacts_base: Path,
        llm_client: LLMClient,
        slide_concurrency: int = 4,
        slide_retry: int = 2,
        llm_max_retries: int = 2,
    ) -> None:
        self.store = store
        self.artifacts_base = artifacts_base
        self.llm_client = llm_client
        self.slide_concurrency = max(1, slide_concurrency)
        self.slide_retry = max(1, slide_retry)
        self.llm_max_retries = max(1, llm_max_retries)

    def _spawn(self, coro: Any) -> None:
        def runner() -> None:
            asyncio.run(coro)

        threading.Thread(target=runner, daemon=True).start()

    async def create_run(self, req: CreateRunRequest) -> RunSummaryResponse:
        run_id = str(uuid4())
        trace_id = str(uuid4())
        artifact_dir = self.artifacts_base / run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        run = RunRecord(
            run_id=run_id,
            trace_id=trace_id,
            status=RunStatus.OUTLINE_DRAFTING,
            input=req,
            artifact_dir=str(artifact_dir),
        )
        await self.store.add_run(run)
        self._spawn(self._generate_outline(run_id))
        return RunSummaryResponse(run_id=run_id, trace_id=trace_id, status=run.status)

    async def get_run_detail(self, run_id: str) -> RunDetailResponse | None:
        run = await self.store.get_run(run_id)
        if run is None:
            return None
        return RunDetailResponse(
            run_id=run.run_id,
            trace_id=run.trace_id,
            status=run.status,
            outline=run.outline,
            slides=run.slides,
            citation_map=run.citation_map,
            stage_timings=run.stage_timings,
            error_code=run.error_code,
            failed_stage=run.failed_stage,
            retryable=run.retryable,
            compile_js_path=run.compile_js_path,
            pptx_path=run.pptx_path,
            events=run.events,
        )

    async def confirm_outline(self, run_id: str, req: ConfirmOutlineRequest) -> RunSummaryResponse | None:
        run = await self.store.get_run(run_id)
        if run is None:
            return None
        if run.status != RunStatus.AWAITING_OUTLINE_CONFIRM:
            raise ValueError("run is not awaiting outline confirmation")

        def apply_confirm(r: RunRecord) -> None:
            if req.outline is not None:
                r.outline = req.outline
            r.status = RunStatus.SLIDES_GENERATING

        await self.store.update_run(run_id, apply_confirm)
        self._spawn(self._generate_slides_and_compile(run_id))
        updated = await self.store.get_run(run_id)
        assert updated is not None
        return RunSummaryResponse(run_id=updated.run_id, trace_id=updated.trace_id, status=updated.status)

    async def _publish(self, run_id: str, event_type: EventType, payload: dict[str, Any]) -> None:
        run = await self.store.get_run(run_id)
        if run is None:
            return
        event = RunEvent(seq=len(run.events) + 1, event=event_type, ts=now_iso(), payload=payload)
        await self.store.append_event(run_id, event)

    async def _generate_outline(self, run_id: str) -> None:
        started = time.perf_counter()
        run = await self.store.get_run(run_id)
        if run is None:
            return

        try:
            async def on_token(token: str) -> None:
                await self._publish(run_id, EventType.OUTLINE_TOKEN, {"token": token})

            outline = None
            for attempt in range(1, self.llm_max_retries + 1):
                try:
                    outline = await self.llm_client.generate_outline(
                        topic=run.input.topic,
                        project_id=run.input.project_id,
                        rag_source_ids=run.input.rag_source_ids,
                        template_style=run.input.template_style,
                        target_slide_count=run.input.target_slide_count,
                        on_token=on_token,
                    )
                    break
                except Exception:
                    if attempt >= self.llm_max_retries:
                        raise
                    await asyncio.sleep(0.1 * attempt)

            assert outline is not None

            def apply_outline(r: RunRecord) -> None:
                r.outline = outline
                r.status = RunStatus.AWAITING_OUTLINE_CONFIRM
                r.stage_timings.outline_ms = int((time.perf_counter() - started) * 1000)

            await self.store.update_run(run_id, apply_outline)
            await self._publish(run_id, EventType.OUTLINE_COMPLETED, {"version": outline.version, "sections": len(outline.nodes)})
        except Exception as exc:  # pragma: no cover
            await self._fail_run(run_id, "OUTLINE_DRAFTING", "OUTLINE_LLM_ERROR", retryable=True)

    async def _generate_slides_and_compile(self, run_id: str) -> None:
        run = await self.store.get_run(run_id)
        if run is None or run.outline is None:
            await self._fail_run(run_id, "SLIDES_GENERATING", "OUTLINE_MISSING", retryable=False)
            return

        slide_start = time.perf_counter()
        sem = asyncio.Semaphore(self.slide_concurrency)

        async def generate_one(slide_no: int, node: OutlineNode) -> None:
            async with sem:
                await self._publish(run_id, EventType.SLIDE_STARTED, {"slide_no": slide_no})
                slide = await self._generate_slide_with_retry(run_id, slide_no, node)

                def apply_slide(r: RunRecord) -> None:
                    r.slides.append(slide)
                    r.citation_map[slide_no] = slide.citations

                await self.store.update_run(run_id, apply_slide)
                await self._publish(run_id, EventType.SLIDE_GENERATED, {"slide_no": slide_no, "status": slide.status})

        results = await asyncio.gather(
            *(generate_one(i, n) for i, n in enumerate(run.outline.nodes, start=1)),
            return_exceptions=True,
        )
        if any(isinstance(x, Exception) for x in results):
            await self._fail_run(run_id, "SLIDES_GENERATING", "SLIDE_LLM_ERROR", retryable=True)
            return

        await self.store.update_run(
            run_id,
            lambda r: setattr(r.stage_timings, "slide_ms", int((time.perf_counter() - slide_start) * 1000)),
        )
        await self.store.update_run(run_id, lambda r: setattr(r, "status", RunStatus.COMPILING))
        await self._publish(run_id, EventType.COMPILE_STARTED, {})

        compile_start = time.perf_counter()
        try:
            await self._compile(run_id)
            await self.store.update_run(
                run_id,
                lambda r: setattr(r.stage_timings, "compile_ms", int((time.perf_counter() - compile_start) * 1000)),
            )
            await self.store.update_run(run_id, lambda r: setattr(r, "status", RunStatus.SUCCEEDED))
            await self._publish(run_id, EventType.COMPILE_COMPLETED, {})
        except Exception:
            await self._fail_run(run_id, "COMPILING", "COMPILE_ERROR", retryable=False)

    async def _generate_slide_with_retry(self, run_id: str, slide_no: int, node: OutlineNode) -> SlideArtifact:
        run = await self.store.get_run(run_id)
        assert run is not None
        artifact_dir = Path(run.artifact_dir)
        retries = 0
        while True:
            try:
                if f"FAIL_SLIDE_{slide_no}" in run.input.topic and retries == 0:
                    raise RuntimeError("simulated one-time failure")

                generated = await self.llm_client.generate_slide(
                    topic=run.input.topic,
                    project_id=run.input.project_id,
                    template_style=run.input.template_style,
                    slide_no=slide_no,
                    target_slide_count=run.input.target_slide_count,
                    outline_node=node,
                    rag_source_ids=run.input.rag_source_ids,
                )
                citations = self._normalize_citations(generated, run.input.rag_source_ids, slide_no)
                js_code = self._build_slide_js(slide_no, generated.title, generated.bullets, citations)
                (artifact_dir / f"slide-{slide_no:02d}.js").write_text(js_code, encoding="utf-8")
                status = "ok" if retries == 0 else f"ok_after_retry_{retries}"
                return SlideArtifact(slide_no=slide_no, js_code=js_code, status=status, citations=citations)
            except Exception:
                retries += 1
                if retries >= self.slide_retry:
                    raise
                await asyncio.sleep(0.05 * retries)

    async def _compile(self, run_id: str) -> None:
        run = await self.store.get_run(run_id)
        assert run is not None
        if "FAIL_COMPILE" in run.input.topic:
            raise RuntimeError("simulated compile failure")

        slides_sorted = sorted(run.slides, key=lambda x: x.slide_no)
        artifact_dir = Path(run.artifact_dir)
        compile_js = artifact_dir / "compile.js"
        compile_js.write_text(
            "\n".join(
                [
                    "// compile script generated by ppt-agent-service",
                    "const slides = [",
                    *[f"  'slide-{s.slide_no:02d}.js'," for s in slides_sorted],
                    "];",
                    "console.log('Compiling slides:', slides.length);",
                ]
            ),
            encoding="utf-8",
        )
        pptx_path = artifact_dir / "output.pptx"
        build_pptx(pptx_path, [f"Slide {s.slide_no}" for s in slides_sorted])

        def apply_compile(r: RunRecord) -> None:
            r.compile_js_path = str(compile_js)
            r.pptx_path = str(pptx_path)

        await self.store.update_run(run_id, apply_compile)

    async def _fail_run(self, run_id: str, stage: str, error_code: str, retryable: bool) -> None:
        def apply_fail(r: RunRecord) -> None:
            r.status = RunStatus.FAILED
            r.error_code = error_code
            r.failed_stage = stage
            r.retryable = retryable

        await self.store.update_run(run_id, apply_fail)
        await self._publish(
            run_id,
            EventType.RUN_FAILED,
            {"error_code": error_code, "failed_stage": stage, "retryable": retryable},
        )

    def _normalize_citations(self, generated: GeneratedSlide, rag_source_ids: list[str], slide_no: int) -> list[str]:
        if generated.citations:
            normalized = [item for item in generated.citations if item]
            if normalized:
                return list(dict.fromkeys(normalized))
        return self._fallback_citations(rag_source_ids, slide_no)

    def _fallback_citations(self, rag_source_ids: list[str], slide_no: int) -> list[str]:
        if not rag_source_ids:
            return []
        first = rag_source_ids[(slide_no - 1) % len(rag_source_ids)]
        second = rag_source_ids[slide_no % len(rag_source_ids)] if len(rag_source_ids) > 1 else first
        return list(dict.fromkeys([first, second]))

    def _build_slide_js(self, slide_no: int, title: str, bullets: list[str], citations: list[str]) -> str:
        return "\n".join(
            [
                f"// slide-{slide_no:02d}.js",
                "module.exports = {",
                f"  slideNo: {slide_no},",
                f"  title: {json.dumps(title, ensure_ascii=False)},",
                f"  bullets: {json.dumps(bullets, ensure_ascii=False)},",
                f"  citations: {json.dumps(citations, ensure_ascii=False)},",
                "};",
            ]
        )


def build_orchestrator(base_dir: Path) -> RunOrchestrator:
    settings = load_settings()
    artifacts_dir = base_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    llm_client = OpenAICompatibleLLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_sec=settings.llm_timeout_sec,
        outline_temperature=settings.llm_temperature_outline,
        slide_temperature=settings.llm_temperature_slide,
    )
    return RunOrchestrator(
        store=RunStore(base_dir=base_dir),
        artifacts_base=artifacts_dir,
        llm_client=llm_client,
        slide_concurrency=settings.slide_concurrency,
        slide_retry=settings.slide_retry,
        llm_max_retries=settings.llm_max_retries,
    )
