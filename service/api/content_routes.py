from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from ..models import (
    ConfirmLongFormPlanRequest,
    ItemGenerationPromptRunRequest,
    ItemGenerationRunRequest,
    LongFormPromptRunRequest,
    LongFormRunRequest,
    ReviseLongFormSectionRequest,
    StructureExpansionPromptRunRequest,
    StructureExpansionRunRequest,
)
from .runtime_context import AppContext, sse_event_stream


def register_content_routes(app: FastAPI, ctx: AppContext) -> None:
    @app.post("/v1/content/runs")
    async def create_content_run(
        req: LongFormRunRequest | StructureExpansionRunRequest | ItemGenerationRunRequest,
    ):
        return await ctx.application.create_content_run(req)

    @app.post("/v1/content/runs/prompt")
    async def create_content_run_from_prompt(
        req: LongFormPromptRunRequest
        | StructureExpansionPromptRunRequest
        | ItemGenerationPromptRunRequest,
    ):
        return await ctx.application.create_content_run(req.to_create_run_request())

    @app.get("/v1/content/runs/{run_id}")
    async def get_content_run(run_id: str):
        run = await ctx.application.get_content_run_detail(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    @app.post("/v1/content/runs/{run_id}/plan/confirm")
    async def confirm_content_plan(run_id: str, req: ConfirmLongFormPlanRequest):
        try:
            run = await ctx.application.confirm_content_plan(run_id, req)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    @app.post("/v1/content/runs/{run_id}/sections/{section_id}/revise")
    async def revise_content_section(
        run_id: str, section_id: str, req: ReviseLongFormSectionRequest
    ):
        try:
            result = await ctx.application.revise_content_section(
                run_id, section_id, req
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="run not found")
        return result

    @app.get("/v1/content/runs/{run_id}/events")
    async def content_events(run_id: str):
        run = await ctx.application.get_content_run_detail(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return StreamingResponse(
            sse_event_stream(ctx, run_id), media_type="text/event-stream"
        )
