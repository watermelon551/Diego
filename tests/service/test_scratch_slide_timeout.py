from tests.support.service_flow_shared import *  # noqa: F401,F403


class SlowScratchEngine:
    async def generate_slide(self, **_kwargs):
        await asyncio.sleep(1)


def test_scratch_slide_batch_timeout_should_fail_run_truthfully(tmp_path: Path) -> None:
    settings = make_settings(
        generation_engine="agentic_v2",
        slide_generation_timeout_sec=0.05,
    )
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=settings,
    )
    orch.scratch_engine = SlowScratchEngine()
    run = RunRecord(
        run_id="r-slide-timeout",
        trace_id="t-slide-timeout",
        status=RunStatus.SLIDES_GENERATING,
        input=CreateRunRequest(
            topic="Slow slides",
            project_id="p-slide-timeout",
            target_slide_count=1,
            generation_mode=GenerationMode.SCRATCH,
        ),
        artifact_dir=str(tmp_path / "artifacts" / "r-slide-timeout"),
        outline=OutlineDocument(
            version=1,
            summary="slow",
            nodes=[OutlineNode(title="Slow", bullets=["wait"])],
        ),
    )

    async def scenario() -> RunRecord:
        await orch.store.add_run(run)
        await orch._scratch_flow.execute(run.run_id)
        final = await orch.store.get_run(run.run_id)
        assert final is not None
        return final

    final = asyncio.run(scenario())

    assert final.status == RunStatus.FAILED
    assert final.error_code == "SLIDE_GENERATION_TIMEOUT"
    assert final.failed_stage == "SLIDES_GENERATING"
    assert final.error_details["first_failure"]["details"]["error_type"] == "SlideGenerationTimeout"
    assert final.stage_timings.slide_ms > 0
    assert any(item.event == EventType.RUN_FAILED for item in final.events)
