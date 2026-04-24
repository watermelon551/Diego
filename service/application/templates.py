from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from ..infra.store import now_iso
from ..models import TemplateDetailResponse, TemplateRecord, TemplateUploadResponse


class TemplateApplicationService:
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator

    async def upload_template(self, *, filename: str, content: bytes) -> TemplateUploadResponse:
        template_id = str(uuid4())
        target_dir = self.orch.templates_base / template_id
        target_dir.mkdir(parents=True, exist_ok=True)
        sanitized_name = Path(filename).name or "template.pptx"
        template_path = target_dir / sanitized_name
        template_path.write_bytes(content)
        record = TemplateRecord(
            template_id=template_id,
            filename=sanitized_name,
            path=str(template_path),
            created_at=now_iso(),
        )
        await self.orch.store.add_template(record)
        return TemplateUploadResponse(template_id=template_id, filename=sanitized_name)

    async def get_template_detail(self, template_id: str) -> TemplateDetailResponse | None:
        record = await self.orch.store.get_template(template_id)
        if record is None:
            return None
        return TemplateDetailResponse(
            template_id=record.template_id,
            filename=record.filename,
            path=record.path,
            created_at=record.created_at,
        )
