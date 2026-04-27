from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from ..run import RunOrchestrator, build_orchestrator
from .content_routes import register_content_routes
from .ppt_routes import register_ppt_routes
from .runtime_context import AppContext, build_app_lifespan


def create_app(
    base_dir: Path | None = None, orchestrator: RunOrchestrator | None = None
) -> FastAPI:
    resolved_base = base_dir or (Path.cwd() / ".runtime")
    resolved_base.mkdir(parents=True, exist_ok=True)
    orch = orchestrator or build_orchestrator(resolved_base)
    ctx = AppContext(orchestrator=orch, application=orch.application)
    app = FastAPI(title="Diego", version="0.1.0", lifespan=build_app_lifespan(ctx))

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "service": "diego"}
    register_ppt_routes(app, ctx)
    register_content_routes(app, ctx)

    return app
