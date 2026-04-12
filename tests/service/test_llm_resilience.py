from tests.support.service_flow_shared import *  # noqa: F401,F403

def test_outline_format_error_should_trigger_repair_and_succeed(tmp_path: Path) -> None:
    client = make_client(tmp_path, llm_client=MalformedOutlineThenRepairLLM())
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Outline Repair",
            "project_id": "p-outline-repair",
            "rag_source_ids": ["r1"],
            "template_style": "default",
            "target_slide_count": 3,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    detail = wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    assert detail["outline"] is not None
    events = [item["event"] for item in detail["events"]]
    assert "outline.repair.failed" in events
    assert "outline.repair.started" in events
    assert "outline.repair.completed" in events

def test_outline_critique_format_error_should_repair_and_continue(tmp_path: Path) -> None:
    client = make_client(tmp_path, llm_client=CritiqueMalformedThenRepairLLM())
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Critique Repair",
            "project_id": "p-critique-repair",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 3,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    detail = wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    events = [item for item in detail["events"] if item["event"].startswith("outline.repair.")]
    assert any(item["payload"].get("phase") == "critique" and item["event"] == "outline.repair.failed" for item in events)
    assert any(item["payload"].get("phase") == "critique" and item["event"] == "outline.repair.completed" for item in events)

def test_outline_timeout_retry_then_success(tmp_path: Path) -> None:
    client = make_client(tmp_path, llm_client=TimeoutThenSuccessOutlineLLM(fail_times=2))
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Outline Timeout Retry",
            "project_id": "p-timeout-retry",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 3,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    detail = wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    events = [item["event"] for item in detail["events"]]
    assert "llm.request.timeout" in events
    assert "llm.request.retry" in events
    assert detail["outline"] is not None

def test_outline_timeout_exhausted_should_fail_with_timeout_code(tmp_path: Path) -> None:
    client = make_client(tmp_path, llm_client=AlwaysTimeoutOutlineLLM())
    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "Outline Timeout Exhausted",
            "project_id": "p-timeout-fail",
            "rag_source_ids": [],
            "template_style": "default",
            "target_slide_count": 3,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    detail = wait_status(client, run_id, {"FAILED"})
    assert detail["error_code"] == "OUTLINE_LLM_TIMEOUT"
    assert detail["failed_stage"] == "OUTLINE_DRAFTING"
    assert detail["error_details"]["phase"] == "outline.generate"
    assert detail["error_details"]["attempts"] == 4

def test_evaluate_slide_quality_should_retry_with_json_repair() -> None:
    class JsonRepairClient(llm_client_mod.OpenAICompatibleLLMClient):
        def __init__(self) -> None:
            super().__init__(
                base_url="https://api.example.com/v1",
                api_key="k",
                model="m",
                json_repair_retry=1,
            )
            self.calls = 0

        async def _chat_text(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return "{ bad json"
            return "{\"score\": 86, \"issues\": [], \"repair_directives\": []}"

    client = JsonRepairClient()
    result = asyncio.run(
        client.evaluate_slide_quality(
            topic="x",
            template_style="default",
            slide_no=1,
            target_slide_count=1,
            outline_node=OutlineNode(
                title="T",
                bullets=["a", "b"],
                page_type=SlidePageType.COVER,
                layout_hint="hero-center",
            ),
            candidate_js="module.exports = { createSlide, slideConfig }; function createSlide(){}",
            preview_text="",
            hard_issues=[],
        )
    )
    assert result["score"] == 86
    assert client.calls == 2

