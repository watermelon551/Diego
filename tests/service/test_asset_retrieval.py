from tests.support.service_flow_shared import *  # noqa: F401,F403


def test_fetch_slot_asset_should_prioritize_project_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings()
    settings = Settings(
        **{
            **settings.__dict__,
            "asset_provider": "unsplash",
            "unsplash_access_key": "test-key",
        }
    )
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=settings,
    )

    def fake_search_provider_assets(*, provider: str, queries: list[str], slot_type: str, per_query: int) -> list[dict]:
        return [
            {
                "key": "unsplash:public-1",
                "provider": provider,
                "source": "public",
                "query": queries[0] if queries else "",
                "url": "https://images.example.com/public.jpg",
                "text": "generic stock background",
                "width": 1600,
                "height": 900,
            }
        ]

    def fake_resolve_candidate_asset_bytes(*, candidate: dict, client) -> tuple[bytes, str]:
        if str(candidate.get("source", "")).strip() == "project":
            return b"project-bytes", "png"
        return b"public-bytes", "jpg"

    monkeypatch.setattr(orch, "_search_provider_assets", fake_search_provider_assets)
    monkeypatch.setattr(orch, "_resolve_candidate_asset_bytes", fake_resolve_candidate_asset_bytes)

    node = OutlineNode(
        title="Project Rollout",
        bullets=["Milestones", "Risks"],
        page_type=SlidePageType.CONTENT,
        layout_hint="content-two-column",
    )
    asset_bytes, ext, meta = orch._fetch_slot_asset(
        query="project rollout timeline",
        slot_type="image",
        node=node,
        slide_no=3,
        rel_id="unit-test",
        search_context={
            "topic": "Project Rollout",
            "rag_source_ids": ["https://cdn.example.com/project-diagram.png"],
        },
    )

    assert asset_bytes == b"project-bytes"
    assert ext == "png"
    assert meta.get("source") == "project"
    assert meta.get("provider") == "project"


def test_fetch_slot_asset_should_use_project_candidates_when_external_provider_disabled(
    tmp_path: Path,
) -> None:
    settings = make_settings()
    settings = Settings(
        **{
            **settings.__dict__,
            "asset_provider": "none",
        }
    )
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=settings,
    )
    image_path = tmp_path / "source-image.png"
    image_path.write_bytes(b"project-image-bytes")
    node = OutlineNode(
        title="Project Rollout",
        bullets=["Milestones", "Risks"],
        page_type=SlidePageType.CONTENT,
        layout_hint="content-two-column",
    )

    asset_bytes, ext, meta = orch._fetch_slot_asset(
        query="project rollout timeline",
        slot_type="image",
        node=node,
        slide_no=3,
        rel_id="unit-test",
        search_context={
            "topic": "Project Rollout",
            "project_asset_urls": [str(image_path)],
        },
    )

    assert asset_bytes == b"project-image-bytes"
    assert ext == "png"
    assert meta.get("source") == "project"
    assert meta.get("provider") == "project"


def test_prepare_scratch_visual_assets_icon_rows_should_use_image_slots(tmp_path: Path) -> None:
    settings = make_settings()
    settings = Settings(
        **{
            **settings.__dict__,
            "asset_provider": "mock",
            "generation_engine": "agentic_v2",
        }
    )
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=settings,
    )
    run = RunRecord(
        run_id="r-asset",
        trace_id="trace-asset",
        status=RunStatus.SLIDES_GENERATING,
        input=CreateRunRequest(
            topic="Asset Slot Check",
            project_id="proj-asset",
            target_slide_count=5,
            generation_mode=GenerationMode.SCRATCH,
            visual_policy="auto",
        ),
        artifact_dir=str(tmp_path / "artifacts" / "r-asset"),
    )
    node = OutlineNode(
        title="System Components",
        bullets=["Component map", "Data exchange"],
        page_type=SlidePageType.CONTENT,
        layout_hint="content-icon-rows",
    )
    slide_plan = {
        "layout": "content-icon-rows",
        "visual_plan": {"kind": "icon_rows", "image_slots": 2},
    }
    slides_dir = tmp_path / "slides"
    assets = asyncio.run(
        orch._prepare_scratch_visual_assets(
            run=run,
            node=node,
            slide_no=3,
            slide_plan=slide_plan,
            slides_dir=slides_dir,
        )
    )

    assert assets
    assert all(str(item.get("type", "")).strip().lower() == "image" for item in assets)
    assert str(assets[0].get("slot", "")).strip().lower() == "main"
