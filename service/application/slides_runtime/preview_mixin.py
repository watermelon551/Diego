from __future__ import annotations

from pathlib import Path
from typing import Any

from ...models import RunRecord
from ...run.slide_preview import build_slide_preview_payload


class SlidePreviewApplicationMixin:
    async def get_slide_preview(
        self, run_id: str, slide_no: int
    ) -> dict[str, Any] | None:
        if slide_no < 1:
            raise ValueError("slide_no must be >= 1")
        run = await self.orch.store.get_run(run_id)
        if run is None:
            return None
        _, slide_js_path = self._require_slide_js_artifact(
            run=run,
            slide_no=slide_no,
            not_ready_message="slide preview not ready",
        )
        preview = await self.render_slide_preview_or_fallback(
            run_id=run_id,
            slide_no=slide_no,
            slide_js_path=slide_js_path,
            theme=self.orch._resolve_run_design(run).theme,
        )
        return build_slide_preview_payload(
            run_id=run_id,
            slide_no=slide_no,
            preview=preview,
        )

    async def get_slide_asset_path(
        self, run_id: str, slide_no: int, asset_path: str
    ) -> Path | None:
        if slide_no < 1:
            raise ValueError("slide_no must be >= 1")
        requested_path = str(asset_path or "").strip()
        if not requested_path:
            raise ValueError("asset path is required")
        if requested_path.startswith(("http://", "https://", "data:", "blob:")):
            raise ValueError("asset path must reference a local slide asset")
        run = await self.orch.store.get_run(run_id)
        if run is None:
            return None
        _, slide_js_path = self._require_slide_js_artifact(
            run=run,
            slide_no=slide_no,
            not_ready_message="slide asset not ready",
        )
        candidate = Path(requested_path)
        if not candidate.is_absolute():
            candidate = (slide_js_path.parent / candidate).resolve()
        else:
            candidate = candidate.resolve()
        artifact_root = Path(str(run.artifact_dir or "").strip()).resolve()
        try:
            candidate.relative_to(artifact_root)
        except ValueError as exc:
            raise ValueError("asset path escapes run artifact root") from exc
        if not candidate.exists() or not candidate.is_file():
            raise FileNotFoundError("slide asset file missing")
        return candidate

    async def render_slide_preview_or_fallback(
        self,
        *,
        run_id: str,
        slide_no: int,
        slide_js_path: Path,
        theme: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.orch.render_slide_preview_or_fallback(
            run_id=run_id,
            slide_no=slide_no,
            slide_js_path=slide_js_path,
            theme=theme,
        )

    def _require_slide_js_artifact(
        self,
        *,
        run: RunRecord,
        slide_no: int,
        not_ready_message: str,
    ):
        return self.orch._require_slide_js_artifact(
            run=run,
            slide_no=slide_no,
            not_ready_message=not_ready_message,
        )
