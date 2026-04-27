from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from ..models import (
    ConfirmOutlineRequest,
    CreateRunRequest,
    PromptRunRequest,
    RegenerateSlideRequest,
    SaveSlideSceneRequest,
)
from ..run import (
    SlideSceneConflictError,
    SlideSceneNodeNotFoundError,
    SlideSceneUnsupportedError,
)
from .runtime_context import AppContext, sse_event_stream


def register_ppt_routes(app: FastAPI, ctx: AppContext) -> None:
    @app.post("/v1/ppt/runs")
    async def create_run(req: CreateRunRequest):
        return await ctx.application.create_run(req)

    @app.post("/v1/ppt/runs/prompt")
    async def create_run_from_prompt(req: PromptRunRequest):
        return await ctx.application.create_run(req.to_create_run_request())

    @app.post("/v1/ppt/templates")
    async def upload_template(file: UploadFile = File(...)):
        if not file.filename.lower().endswith(".pptx"):
            raise HTTPException(
                status_code=400, detail="only .pptx template is supported"
            )
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="empty template file")
        return await ctx.application.upload_template(
            filename=file.filename, content=data
        )

    @app.get("/v1/ppt/templates/{template_id}")
    async def get_template(template_id: str):
        detail = await ctx.application.get_template_detail(template_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="template not found")
        return detail

    @app.get("/v1/ppt/runs/{run_id}")
    async def get_run(run_id: str):
        run = await ctx.application.get_run_detail(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    @app.get("/v1/ppt/runs/{run_id}/slides/{slide_no}/preview")
    async def get_slide_preview(run_id: str, slide_no: int):
        if slide_no < 1:
            raise HTTPException(status_code=400, detail="slide_no must be >= 1")
        try:
            preview = await ctx.application.get_slide_preview(run_id, slide_no)
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
            scene = await ctx.application.get_slide_scene(run_id, slide_no)
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
            resolved_path = await ctx.application.get_slide_asset_path(
                run_id, slide_no, path
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if resolved_path is None:
            raise HTTPException(status_code=404, detail="run not found")
        media_type = (
            mimetypes.guess_type(str(resolved_path))[0]
            or "application/octet-stream"
        )
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
            result = await ctx.application.save_slide_scene(
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
            result = await ctx.application.regenerate_single_slide(
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

    @app.get("/v1/ppt/runs/{run_id}/artifacts/compile-bundle")
    async def get_compile_bundle(run_id: str):
        try:
            bundle = await ctx.application.build_compile_bundle(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return bundle

    @app.post("/v1/ppt/runs/{run_id}/outline/confirm")
    async def confirm_outline(run_id: str, req: ConfirmOutlineRequest):
        try:
            run = await ctx.application.confirm_outline(run_id, req)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    @app.get("/v1/ppt/runs/{run_id}/events")
    async def events(run_id: str):
        run = await ctx.application.get_run_detail(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return StreamingResponse(
            sse_event_stream(ctx, run_id), media_type="text/event-stream"
        )
