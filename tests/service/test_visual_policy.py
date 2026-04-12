from tests.support.service_flow_shared import *  # noqa: F401,F403

def test_visual_policy_media_required_should_fail_when_images_missing(tmp_path: Path) -> None:
    settings = make_settings()
    settings = Settings(
        **{
            **settings.__dict__,
            "generation_engine": "agentic_v2",
            "debug_keep_previews": False,
            "max_slide_repair_rounds": 2,
        }
    )
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=AgenticMockLLM(),
        settings=settings,
    )
    client = TestClient(create_app(base_dir=tmp_path, orchestrator=orch))

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Visual Policy Required",
            "project_id": "p-vp-media",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 5,
            "generation_mode": "scratch",
            "visual_policy": "media_required",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"FAILED"})
    assert final["error_code"] == "VISUAL_POLICY_UNSATISFIED"

def test_visual_policy_basic_graphics_only_should_fail_when_image_present(tmp_path: Path) -> None:
    settings = make_settings()
    settings = Settings(
        **{
            **settings.__dict__,
            "generation_engine": "agentic_v2",
            "debug_keep_previews": False,
            "max_slide_repair_rounds": 2,
        }
    )
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=ImageHeavyAgenticLLM(),
        settings=settings,
    )
    client = TestClient(create_app(base_dir=tmp_path, orchestrator=orch))

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "No Images Allowed",
            "project_id": "p-vp-basic",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 5,
            "generation_mode": "scratch",
            "visual_policy": "basic_graphics_only",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"SUCCEEDED"})
    assert final["status"] == "SUCCEEDED"

