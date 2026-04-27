from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..application import DiegoApplication
from ..models import RunStatus
from ..run import RunOrchestrator


class AppContext:
    def __init__(
        self, orchestrator: RunOrchestrator, application: DiegoApplication
    ) -> None:
        self.orchestrator = orchestrator
        self.application = application


async def sse_event_stream(ctx: AppContext, run_id: str):
    cursor = 0
    while True:
        run = await ctx.application.get_run_record(run_id)
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
            await ctx.application.wait_for_event(run_id, cursor, timeout=5.0)
        except (TimeoutError, asyncio.TimeoutError):
            yield ": keep-alive\n\n"


def build_app_lifespan(ctx: AppContext):
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await ctx.orchestrator.store.initialize()
        if getattr(
            ctx.orchestrator.settings, "run_store", "memory"
        ) == "postgres" and bool(
            getattr(ctx.orchestrator.settings, "recovery_scan_on_boot", True)
        ):
            await ctx.application.recover_interrupted_runs()
        yield

    return lifespan
