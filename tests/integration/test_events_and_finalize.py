from tests.support.service_flow_shared import *  # noqa: F401,F403

def test_event_stream_has_required_events(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Observability",
            "project_id": "p3",
            "rag_source_ids": ["s1", "s2"],
            "template_style": "default",
            "target_slide_count": 2,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    wait_status(client, run_id, {"SUCCEEDED"})

    with client.stream("GET", f"/v1/ppt/runs/{run_id}/events") as stream:
        body = "".join(chunk for chunk in stream.iter_text())

    assert "event: outline.token" in body
    assert "event: outline.completed" in body
    assert "event: research.completed" in body
    assert "event: plan.completed" in body
    assert "event: slide.generated" in body
    assert "event: qa.completed" in body
    assert "event: slide.preview.qa" in body
    assert "event: chart.truth.checked" in body

def test_fail_run_should_emit_run_finalized_failed_event(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    req = CreateRunRequest(topic="t", project_id="p", generation_mode=GenerationMode.SCRATCH)
    run = RunRecord(run_id="r1", trace_id="tr1", status=RunStatus.SLIDES_GENERATING, input=req, artifact_dir=str(tmp_path / "artifacts" / "r1"))
    asyncio.run(orch.store.add_run(run))

    asyncio.run(orch._fail_run("r1", "COMPILING", "QA_FAILED", retryable=False, error_details={"reason": "x"}))
    detail = asyncio.run(orch.get_run_detail("r1"))
    assert detail is not None
    assert detail.status == RunStatus.FAILED
    event_names = [event.event for event in detail.events]
    assert EventType.RUN_FAILED in event_names
    assert EventType.RUN_FINALIZED in event_names
    finalized_payloads = [event.payload for event in detail.events if event.event == EventType.RUN_FINALIZED]
    assert finalized_payloads and finalized_payloads[-1]["final_status"] == RunStatus.FAILED.value

def test_finalize_run_success_should_emit_run_finalized_success_event(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    req = CreateRunRequest(topic="t2", project_id="p2", generation_mode=GenerationMode.SCRATCH)
    run = RunRecord(run_id="r2", trace_id="tr2", status=RunStatus.COMPILING, input=req, artifact_dir=str(tmp_path / "artifacts" / "r2"))
    asyncio.run(orch.store.add_run(run))

    asyncio.run(orch._finalize_run_success("r2", from_stage="COMPILING", reason="unit-test"))
    detail = asyncio.run(orch.get_run_detail("r2"))
    assert detail is not None
    assert detail.status == RunStatus.SUCCEEDED
    finalized_payloads = [event.payload for event in detail.events if event.event == EventType.RUN_FINALIZED]
    assert finalized_payloads and finalized_payloads[-1]["final_status"] == RunStatus.SUCCEEDED.value

