from __future__ import annotations

from typing import Any

from ...design.skill_profile import DesignProfile
from ...models import OutlineNode, SlideArtifact


class ScratchSlideEngine:
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    async def generate_slide(
        self,
        *,
        run_id: str,
        slide_no: int,
        node: OutlineNode,
        design: DesignProfile,
    ) -> SlideArtifact:
        return await self.runtime._generate_skill_slide(
            run_id=run_id,
            slide_no=slide_no,
            node=node,
            design=design,
        )
