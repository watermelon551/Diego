from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from .models import ConfirmOutlineRequest, CreateRunRequest, RunStatus
from .orchestrator import RunOrchestrator, build_orchestrator


class AppContext:
    def __init__(self, orchestrator: RunOrchestrator) -> None:
        self.orchestrator = orchestrator


async def _sse_generator(ctx: AppContext, run_id: str):
    cursor = 0
    while True:
        run = await ctx.orchestrator.store.get_run(run_id)
        if run is None:
            break

        while cursor < len(run.events):
            event = run.events[cursor]
            payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
            yield f"event: {event.event.value}\ndata: {payload}\n\n"
            cursor += 1

        if run.status in (RunStatus.SUCCEEDED, RunStatus.FAILED):
            break

        try:
            await ctx.orchestrator.store.wait_for_event(run_id, cursor, timeout=5.0)
        except (TimeoutError, asyncio.TimeoutError):
            yield ": keep-alive\n\n"


def create_app(base_dir: Path | None = None, orchestrator: RunOrchestrator | None = None) -> FastAPI:
    app = FastAPI(title="ppt-agent-service", version="0.1.0")
    resolved_base = base_dir or (Path.cwd() / ".runtime")
    resolved_base.mkdir(parents=True, exist_ok=True)
    orch = orchestrator or build_orchestrator(resolved_base)
    ctx = AppContext(orchestrator=orch)

    @app.post("/v1/ppt/runs")
    async def create_run(req: CreateRunRequest):
        return await ctx.orchestrator.create_run(req)

    @app.get("/v1/ppt/runs/{run_id}")
    async def get_run(run_id: str):
        run = await ctx.orchestrator.get_run_detail(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    @app.post("/v1/ppt/runs/{run_id}/outline/confirm")
    async def confirm_outline(run_id: str, req: ConfirmOutlineRequest):
        try:
            run = await ctx.orchestrator.confirm_outline(run_id, req)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    @app.get("/v1/ppt/runs/{run_id}/events")
    async def events(run_id: str):
        run = await ctx.orchestrator.get_run_detail(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return StreamingResponse(_sse_generator(ctx, run_id), media_type="text/event-stream")

    return app
