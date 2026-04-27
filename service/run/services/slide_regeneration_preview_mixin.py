from __future__ import annotations

from typing import Any

from ...models import EventType
from ..slide_regeneration_reporting import build_slide_generated_preview_payload


class SlideRegenerationPreviewMixin:
    async def publish_slide_generated_preview(
        self,
        *,
        run_id: str,
        slide_no: int,
        status: str,
        preview: dict[str, Any],
    ) -> None:
        await self.orch._publish(
            run_id,
            EventType.SLIDE_GENERATED,
            build_slide_generated_preview_payload(
                slide_no=slide_no,
                status=status,
                preview=preview,
            ),
        )
