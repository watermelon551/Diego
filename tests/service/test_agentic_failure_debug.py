from tests.support.service_flow_shared import *  # noqa: F401,F403


def test_agentic_failure_should_keep_last_failed_candidate(tmp_path: Path) -> None:
    class InvalidContractAgenticLLM(MockLLMClient):
        async def generate_slide_js(self, **kwargs):
            return "const broken = true;"

        async def critique_slide_js(self, **kwargs):
            return "const broken = true;"

    settings = make_settings()
    settings = Settings(
        **{
            **settings.__dict__,
            "generation_engine": "agentic_v2",
            "max_slide_repair_rounds": 4,
            "slide_fatal_early_stop_rounds": 2,
            "keep_failed_candidate_js": True,
        }
    )
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=InvalidContractAgenticLLM(),
        settings=settings,
    )
    client = TestClient(create_app(base_dir=tmp_path, orchestrator=orch))

    run_id = client.post(
        "/v1/ppt/runs",
        json={
            "topic": "keep failed candidate",
            "project_id": "p-failed-js",
            "target_slide_count": 2,
            "generation_mode": "scratch",
        },
    ).json()["run_id"]
    wait_status(client, run_id, {"AWAITING_OUTLINE_CONFIRM"})
    client.post(f"/v1/ppt/runs/{run_id}/outline/confirm", json={"approved": True})
    final = wait_status(client, run_id, {"FAILED"}, timeout=20.0)

    assert final["error_code"] in {"SLIDE_LLM_ERROR", "QA_FAILED"}
    if final["error_code"] == "SLIDE_LLM_ERROR":
        failed_dir = tmp_path / "artifacts" / run_id / "slides" / "failed"
        assert failed_dir.exists()
        assert list(failed_dir.glob("slide-*-last.js"))


def test_build_slide_failure_context_should_include_structured_debug_fields(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    sample_js = "\n".join(
        [
            "function createSlide(pres, theme) {",
            "  const slide = pres.addSlide();",
            "  slide.addShape(pres.shapes.LINE, { x: 1, y: 1, w: 2, h: 0.01, line: { color: theme.accent } });",
            "  return slide;",
            "}",
        ]
    )
    context = orch._build_slide_failure_context(
        phase="candidate.preview",
        slide_js_path=tmp_path / "slide-01-cand-01.js",
        candidate_js=sample_js,
        issues=["preview compile failed: slide-01-cand-01.js:3"],
        diagnostics={
            "stderr": "slide-01-cand-01.js:3 TypeError: bad call",
            "stdout": "",
            "error_message": "TypeError: bad call",
            "attempt": 2,
            "gate_summary": {"blocking": 1, "high_risk": 0, "warnings": 1},
        },
    )
    assert context["slide_js_path"].endswith("slide-01-cand-01.js")
    assert context["stderr_excerpt"]
    assert context["error_location"].get("line") == 3
    assert context["gate_summary"]["blocking"] == 1
    assert context["attempt"] == 2
