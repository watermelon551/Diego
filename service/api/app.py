from __future__ import annotations

import asyncio
import json
import mimetypes
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from ..models import (
    ConfirmOutlineRequest,
    CreateRunRequest,
    SaveSlideSceneRequest,
    PromptRunRequest,
    RegenerateSlideRequest,
    RunStatus,
)
from ..run import (
    RunOrchestrator,
    SlideSceneConflictError,
    SlideSceneNodeNotFoundError,
    SlideSceneUnsupportedError,
    build_orchestrator,
)


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


def create_app(
    base_dir: Path | None = None, orchestrator: RunOrchestrator | None = None
) -> FastAPI:
    app = FastAPI(title="Diego", version="0.1.0")
    resolved_base = base_dir or (Path.cwd() / ".runtime")
    resolved_base.mkdir(parents=True, exist_ok=True)
    orch = orchestrator or build_orchestrator(resolved_base)
    ctx = AppContext(orchestrator=orch)

    @app.on_event("startup")
    async def _startup_runtime_recovery() -> None:
        await ctx.orchestrator.store.initialize()
        if getattr(
            ctx.orchestrator.settings, "run_store", "memory"
        ) == "postgres" and bool(
            getattr(ctx.orchestrator.settings, "recovery_scan_on_boot", True)
        ):
            await ctx.orchestrator.recover_interrupted_runs()

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "service": "diego"}

    @app.post("/v1/ppt/runs")
    async def create_run(req: CreateRunRequest):
        return await ctx.orchestrator.create_run(req)

    @app.post("/v1/ppt/runs/prompt")
    async def create_run_from_prompt(req: PromptRunRequest):
        return await ctx.orchestrator.create_run(req.to_create_run_request())

    @app.post("/v1/ppt/templates")
    async def upload_template(file: UploadFile = File(...)):
        if not file.filename.lower().endswith(".pptx"):
            raise HTTPException(
                status_code=400, detail="only .pptx template is supported"
            )
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="empty template file")
        return await ctx.orchestrator.upload_template(
            filename=file.filename, content=data
        )

    @app.get("/v1/ppt/templates/{template_id}")
    async def get_template(template_id: str):
        detail = await ctx.orchestrator.get_template_detail(template_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="template not found")
        return detail

    @app.get("/v1/ppt/runs/{run_id}")
    async def get_run(run_id: str):
        run = await ctx.orchestrator.get_run_detail(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    @app.get("/v1/ppt/runs/{run_id}/slides/{slide_no}/preview")
    async def get_slide_preview(run_id: str, slide_no: int):
        if slide_no < 1:
            raise HTTPException(status_code=400, detail="slide_no must be >= 1")
        try:
            preview = await ctx.orchestrator.get_slide_preview(run_id, slide_no)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if preview is None:
            raise HTTPException(status_code=404, detail="run not found")
        return preview

    @app.get("/v1/ppt/runs/{run_id}/slides/{slide_no}/scene")
    async def get_slide_scene(run_id: str, slide_no: int):
        if slide_no < 1:
            raise HTTPException(status_code=400, detail="slide_no must be >= 1")
        try:
            scene = await ctx.orchestrator.get_slide_scene(run_id, slide_no)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if scene is None:
            raise HTTPException(status_code=404, detail="run not found")
        return scene

    @app.get("/v1/ppt/runs/{run_id}/slides/{slide_no}/asset")
    async def get_slide_asset(run_id: str, slide_no: int, path: str = Query(...)):
        if slide_no < 1:
            raise HTTPException(status_code=400, detail="slide_no must be >= 1")
        try:
            resolved_path = await ctx.orchestrator.get_slide_asset_path(
                run_id, slide_no, path
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if resolved_path is None:
            raise HTTPException(status_code=404, detail="run not found")
        media_type = mimetypes.guess_type(str(resolved_path))[0] or "application/octet-stream"
        return FileResponse(
            path=str(resolved_path),
            media_type=media_type,
            filename=resolved_path.name,
        )

    @app.post("/v1/ppt/runs/{run_id}/slides/{slide_no}/scene/save")
    async def save_slide_scene(run_id: str, slide_no: int, req: SaveSlideSceneRequest):
        if slide_no < 1:
            raise HTTPException(status_code=400, detail="slide_no must be >= 1")
        try:
            result = await ctx.orchestrator.save_slide_scene(
                run_id=run_id, slide_no=slide_no, req=req
            )
        except SlideSceneConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (SlideSceneUnsupportedError, SlideSceneNodeNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="run not found")
        return result

    @app.post("/v1/ppt/runs/{run_id}/slides/{slide_no}/regenerate")
    async def regenerate_slide(run_id: str, slide_no: int, req: RegenerateSlideRequest):
        if slide_no < 1:
            raise HTTPException(status_code=400, detail="slide_no must be >= 1")
        try:
            result = await ctx.orchestrator.regenerate_single_slide(
                run_id=run_id,
                slide_no=slide_no,
                instruction=req.instruction,
                preserve_style=req.preserve_style,
                expected_render_version=req.expected_render_version,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="run not found")
        return result

    @app.get("/v1/ppt/runs/{run_id}/artifacts/pptx")
    async def download_pptx(run_id: str):
        run = await ctx.orchestrator.store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        pptx_path = Path(str(run.pptx_path or "").strip())
        if not str(pptx_path):
            raise HTTPException(status_code=404, detail="pptx artifact not found")
        if not pptx_path.exists() or not pptx_path.is_file():
            raise HTTPException(status_code=404, detail="pptx artifact file missing")
        return FileResponse(
            path=str(pptx_path),
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            filename=f"{run_id}.pptx",
        )

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
        return StreamingResponse(
            _sse_generator(ctx, run_id), media_type="text/event-stream"
        )

    return app
