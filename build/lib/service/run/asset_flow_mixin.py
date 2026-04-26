from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..models import OutlineNode, RunRecord, SlidePageType, VisualPolicy
from .types import VisualPolicyUnsatisfiedError


class RunAssetFlowMixin:
    def _push_asset_search_context(self, context: dict[str, Any]) -> None:
        payload = dict(context) if isinstance(context, dict) else {}
        with self._asset_context_lock:
            self._asset_search_context_stack.append(payload)

    def _pop_asset_search_context(self) -> None:
        with self._asset_context_lock:
            if self._asset_search_context_stack:
                self._asset_search_context_stack.pop()

    def _get_active_asset_search_context(self) -> dict[str, Any]:
        with self._asset_context_lock:
            if not self._asset_search_context_stack:
                return {}
            return dict(self._asset_search_context_stack[-1])

    def _remember_run_asset_key(self, *, run_id: str, key: str) -> None:
        normalized = str(key).strip()
        if not normalized:
            return
        with self._run_budget_lock:
            bucket = self._run_asset_keys.setdefault(run_id, set())
            bucket.add(normalized)

    def _run_asset_keys_snapshot(self, *, run_id: str) -> set[str]:
        with self._run_budget_lock:
            return set(self._run_asset_keys.get(run_id, set()))

    def _build_asset_search_context(
        self,
        *,
        run: RunRecord,
        node: OutlineNode,
        slide_no: int,
        slide_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        report = run.research_report if isinstance(run.research_report, dict) else {}
        page_focus_raw = report.get("page_focus")
        page_focus = ""
        if isinstance(page_focus_raw, list) and 0 < slide_no <= len(page_focus_raw):
            page_focus = str(page_focus_raw[slide_no - 1]).strip()
        style_intent = str(report.get("style_intent", "")).strip()
        if not style_intent:
            style_intent = str(run.input.template_style).strip()
        return {
            "run_id": run.run_id,
            "topic": run.input.topic,
            "project_id": run.input.project_id,
            "rag_source_ids": list(run.input.rag_source_ids or []),
            "research_report": report,
            "page_focus": page_focus,
            "style_intent": style_intent,
            "slide_no": slide_no,
            "page_type": node.page_type.value,
            "layout": str((slide_plan or {}).get("layout", "")).strip(),
        }

    async def _prepare_scratch_visual_assets(
        self,
        *,
        run: RunRecord,
        node: OutlineNode,
        slide_no: int,
        slide_plan: dict[str, Any],
        slides_dir: Path,
    ) -> list[dict[str, Any]]:
        if run.input.visual_policy == VisualPolicy.BASIC_GRAPHICS_ONLY:
            return []
        if node.page_type != SlidePageType.CONTENT:
            return []
        visual_plan = slide_plan.get("visual_plan", {}) if isinstance(slide_plan.get("visual_plan", {}), dict) else {}
        kind = str(visual_plan.get("kind", ""))
        requires_image = run.input.visual_policy == VisualPolicy.MEDIA_REQUIRED or kind in {"image_or_showcase", "icon_rows"}
        if run.input.visual_policy == VisualPolicy.AUTO and not requires_image:
            requires_image = True
        if not requires_image:
            return []

        primary_query = self._build_asset_query(node=node, slot_type="image", slide_no=slide_no)
        secondary_query = ""
        if node.bullets:
            second = node.bullets[1] if len(node.bullets) > 1 else node.bullets[0]
            secondary_query = f"{node.title} {str(second).strip()} presentation photo".strip()
        desired_slots = max(1, min(2, int(visual_plan.get("image_slots", 1) or 1)))
        slot_specs: list[tuple[str, str]] = [("main", primary_query)]
        if desired_slots >= 2 and secondary_query:
            slot_specs.append(("secondary", secondary_query))
        context = self._build_asset_search_context(
            run=run,
            node=node,
            slide_no=slide_no,
            slide_plan=slide_plan,
        )
        imgs_dir = slides_dir / "imgs"
        imgs_dir.mkdir(parents=True, exist_ok=True)
        used_keys = self._run_asset_keys_snapshot(run_id=run.run_id)
        assets: list[dict[str, Any]] = []
        for slot, query in slot_specs:
            try:
                asset_bytes, ext, meta = await self._fetch_slot_asset_with_gate(
                    query=query,
                    slot_type="image",
                    node=node,
                    slide_no=slide_no,
                    rel_id=f"scratch-{slide_no:02d}-{slot}",
                    search_context=context,
                    used_asset_keys=used_keys,
                )
                local_path = imgs_dir / f"slide-{slide_no:02d}-{slot}.{ext}"
                await asyncio.to_thread(local_path.write_bytes, asset_bytes)
                rel_path = Path("imgs") / local_path.name
                key = str(meta.get("key", "")).strip()
                if key:
                    used_keys.add(key)
                    self._remember_run_asset_key(run_id=run.run_id, key=key)
                assets.append(
                    {
                        "slot": slot,
                        "type": "image",
                        "query": str(meta.get("query", "")).strip() or query,
                        "path": rel_path.as_posix(),
                        "provider": str(meta.get("provider", "")).strip() or self.settings.asset_provider,
                        "source": str(meta.get("source", "")).strip() or "public",
                        "key": key,
                    }
                )
            except Exception as exc:
                if slot == "main" and run.input.visual_policy == VisualPolicy.MEDIA_REQUIRED:
                    raise VisualPolicyUnsatisfiedError(
                        f"slide {slide_no} requires media asset but fetch failed: {self._exception_reason(exc)}"
                    ) from exc
                continue
        return assets

    async def _fetch_slot_asset_with_gate(
        self,
        *,
        query: str,
        slot_type: str,
        node: OutlineNode,
        slide_no: int,
        rel_id: str,
        search_context: dict[str, Any] | None = None,
        used_asset_keys: set[str] | None = None,
    ) -> tuple[bytes, str, dict[str, Any]]:
        acquired = False
        try:
            timeout_sec = max(2.0, float(self.settings.asset_timeout_sec) + 2.0)
            acquired = await asyncio.to_thread(self._asset_fetch_gate.acquire, True, timeout_sec)
            if not acquired:
                raise TimeoutError("asset fetch concurrency gate timeout")
            return await asyncio.to_thread(
                self._fetch_slot_asset,
                query=query,
                slot_type=slot_type,
                node=node,
                slide_no=slide_no,
                rel_id=rel_id,
                search_context=search_context,
                used_asset_keys=used_asset_keys,
            )
        finally:
            if acquired:
                self._asset_fetch_gate.release()

    def _known_compile_stderr_reason(self, *, stderr: str, stdout: str = "") -> str | None:
        payload = "\n".join([str(stderr or ""), str(stdout or "")]).lower()
        markers = [
            ("addimage() requires either 'data' or 'path' parameter", "addImage call signature invalid"),
            ("error: addimage() requires either 'data' or 'path' parameter", "addImage call signature invalid"),
            ("typeerror: cannot read properties of undefined", "runtime type error during compile"),
        ]
        for marker, reason in markers:
            if marker in payload:
                return reason
        return None
