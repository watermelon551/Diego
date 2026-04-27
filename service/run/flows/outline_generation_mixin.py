from __future__ import annotations

from ...llm import OutlineFormatError
from ...models import EventType, OutlineDocument, RunRecord
from ..outline_reporting import (
    build_outline_repair_completed_payload,
    build_outline_repair_failed_payload,
    build_outline_repair_started_payload,
)


class OutlineGenerationMixin:
    async def _draft_outline(
        self,
        *,
        run_id: str,
        run: RunRecord,
        rag_context_snippets: list[dict],
        effective_template_style: str,
    ) -> OutlineDocument | None:
        orch = self.orch

        async def on_token(token: str) -> None:
            await orch._publish(run_id, EventType.OUTLINE_TOKEN, {"token": token})

        outline: OutlineDocument | None = None
        repair_attempts = max(1, orch.llm_max_retries)
        previous_response = ""
        error_category = ""
        error_details: list[str] = []

        for attempt in range(1, repair_attempts + 2):
            try:
                if attempt == 1:
                    outline = await orch._call_outline_with_timeout_retry(
                        run_id=run_id,
                        phase="outline.generate",
                        action=lambda: orch.llm_client.generate_outline(
                            topic=run.input.topic,
                            project_id=run.input.project_id,
                            rag_source_ids=run.input.rag_source_ids,
                            rag_context_snippets=rag_context_snippets,
                            template_style=effective_template_style,
                            target_slide_count=run.input.target_slide_count,
                            on_token=on_token,
                        ),
                    )
                else:
                    await orch._publish(
                        run_id,
                        EventType.OUTLINE_REPAIR_STARTED,
                        build_outline_repair_started_payload(
                            attempt=attempt - 1,
                            phase="generate",
                            error_category=error_category,
                            error_details=error_details,
                        ),
                    )
                    outline = await orch._call_outline_with_timeout_retry(
                        run_id=run_id,
                        phase="outline.repair.generate",
                        action=lambda: orch.llm_client.repair_outline(
                            topic=run.input.topic,
                            project_id=run.input.project_id,
                            rag_source_ids=run.input.rag_source_ids,
                            rag_context_snippets=rag_context_snippets,
                            template_style=effective_template_style,
                            target_slide_count=run.input.target_slide_count,
                            previous_response=previous_response,
                            error_category=error_category,
                            error_details=error_details,
                        ),
                    )
                    await orch._publish(
                        run_id,
                        EventType.OUTLINE_REPAIR_COMPLETED,
                        build_outline_repair_completed_payload(
                            attempt=attempt - 1,
                            phase="generate",
                        ),
                    )
                break
            except OutlineFormatError as fmt_err:
                previous_response = fmt_err.raw_response
                error_category = fmt_err.category
                error_details = list(fmt_err.details)
                await orch._publish(
                    run_id,
                    EventType.OUTLINE_REPAIR_FAILED,
                    build_outline_repair_failed_payload(
                        attempt=attempt,
                        phase="generate",
                        error_category=error_category,
                        error_details=error_details,
                    ),
                )
                if attempt >= repair_attempts + 1:
                    await orch._fail_run(
                        run_id,
                        "OUTLINE_DRAFTING",
                        "OUTLINE_REPAIR_EXHAUSTED",
                        retryable=True,
                        error_details={
                            "attempts": attempt,
                            "error_category": error_category,
                            "error_details": error_details,
                        },
                    )
                    return None
                continue
        if outline is None:
            await orch._fail_run(
                run_id,
                "OUTLINE_DRAFTING",
                "OUTLINE_REPAIR_EXHAUSTED",
                retryable=True,
                error_details={
                    "attempts": repair_attempts + 1,
                    "error_category": error_category,
                    "error_details": error_details,
                },
            )
            return None
        return outline

    async def _critique_outline(
        self,
        *,
        run_id: str,
        run: RunRecord,
        outline: OutlineDocument,
        rag_context_snippets: list[dict],
        effective_template_style: str,
    ) -> OutlineDocument:
        orch = self.orch
        base_outline = outline
        try:
            return await orch._call_outline_with_timeout_retry(
                run_id=run_id,
                phase="outline.critique",
                action=lambda: orch.llm_client.critique_outline(
                    topic=run.input.topic,
                    template_style=effective_template_style,
                    target_slide_count=run.input.target_slide_count,
                    outline=outline,
                ),
            )
        except OutlineFormatError as fmt_err:
            await orch._publish(
                run_id,
                EventType.OUTLINE_REPAIR_FAILED,
                build_outline_repair_failed_payload(
                    attempt=1,
                    phase="critique",
                    error_category=fmt_err.category,
                    error_details=list(fmt_err.details),
                ),
            )
            try:
                await orch._publish(
                    run_id,
                    EventType.OUTLINE_REPAIR_STARTED,
                    build_outline_repair_started_payload(
                        attempt=1,
                        phase="critique",
                        error_category=fmt_err.category,
                        error_details=list(fmt_err.details),
                    ),
                )
                repaired = await orch._call_outline_with_timeout_retry(
                    run_id=run_id,
                    phase="outline.repair.critique",
                    action=lambda: orch.llm_client.repair_outline(
                        topic=run.input.topic,
                        project_id=run.input.project_id,
                        rag_source_ids=run.input.rag_source_ids,
                        rag_context_snippets=rag_context_snippets,
                        template_style=effective_template_style,
                        target_slide_count=run.input.target_slide_count,
                        previous_response=fmt_err.raw_response,
                        error_category=f"critique_{fmt_err.category}",
                        error_details=list(fmt_err.details),
                    ),
                )
                await orch._publish(
                    run_id,
                    EventType.OUTLINE_REPAIR_COMPLETED,
                    build_outline_repair_completed_payload(
                        attempt=1,
                        phase="critique",
                    ),
                )
                return repaired
            except OutlineFormatError:
                await orch._publish(
                    run_id,
                    EventType.OUTLINE_REPAIR_COMPLETED,
                    build_outline_repair_completed_payload(
                        attempt=1,
                        phase="critique",
                        fallback_used=True,
                    ),
                )
                return base_outline
