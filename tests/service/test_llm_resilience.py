from tests.support.service_flow_shared import *  # noqa: F401,F403
from service.models import LongFormPlan, LongFormPlanSection, StructureExpansionAnchorContext

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


def test_content_primitives_use_llm_json_for_structure_expansion() -> None:
    class ContentPrimitiveClient(llm_client_mod.OpenAICompatibleLLMClient):
        def __init__(self) -> None:
            super().__init__(base_url="https://api.example.com/v1", api_key="k", model="m")
            self.last_messages = None
            self.last_max_tokens = None

        async def _chat_text(self, **kwargs):
            self.last_messages = kwargs["messages"]
            self.last_max_tokens = kwargs.get("max_tokens")
            return json.dumps(
                {
                    "units": [
                        {
                            "unit_id": "node-1",
                            "title": "拥塞窗口变化",
                            "summary": "围绕窗口增长和收缩组织节点。",
                            "key_points": ["慢启动", "拥塞避免"],
                            "source_refs": ["chunk-1"],
                            "anchor_ref": "root",
                            "revision_target": "node-1",
                        }
                    ],
                    "anchors": ["root"],
                    "source_refs": ["chunk-1"],
                    "revision_targets": ["node-1"],
                    "warnings": [],
                },
                ensure_ascii=False,
            )

    client = ContentPrimitiveClient()
    result = asyncio.run(
        client.generate_structure_expansion(
            generation_goal="展开 TCP 拥塞控制",
            project_id="project-1",
            source_scope={"mode": "selected_sources"},
            evidence_refs=["chunk-1"],
            anchor_context=StructureExpansionAnchorContext(anchor_label="root"),
            constraints={"selected_node_path": "root/slow-start", "depth": "deep"},
            requested_output_shape="units",
            rag_source_ids=["file-1"],
            rag_context_snippets=[{"chunk_id": "chunk-1", "text": "慢启动"}],
        )
    )

    assert result.units[0].title == "拥塞窗口变化"
    assert result.revision_targets == ["node-1"]
    assert client.last_messages is not None
    assert "selected_node_path" in client.last_messages[1]["content"]
    assert client.last_max_tokens == 2780


def test_content_primitives_use_llm_json_for_item_generation() -> None:
    class ContentPrimitiveClient(llm_client_mod.OpenAICompatibleLLMClient):
        def __init__(self) -> None:
            super().__init__(base_url="https://api.example.com/v1", api_key="k", model="m")
            self.last_messages = None
            self.last_max_tokens = None

        async def _chat_text(self, **kwargs):
            self.last_messages = kwargs["messages"]
            self.last_max_tokens = kwargs.get("max_tokens")
            return json.dumps(
                {
                    "items": [
                        {
                            "item_id": "q-1",
                            "stem": "慢启动的主要作用是什么？",
                            "choices": ["探测可用带宽", "删除 ACK", "固定窗口"],
                            "expected_response": "探测可用带宽",
                            "expected_response_hints": ["关注拥塞窗口增长"],
                            "explanation": "慢启动通过逐步扩大窗口探测网络容量。",
                            "source_refs": ["chunk-1"],
                            "difficulty": "medium",
                            "intent": "check misconception",
                        }
                    ],
                    "source_refs": ["chunk-1"],
                    "revision_targets": ["q-1"],
                    "warnings": [],
                },
                ensure_ascii=False,
            )

    client = ContentPrimitiveClient()
    result = asyncio.run(
        client.generate_item_generation(
            generation_goal="生成拥塞控制随堂题",
            project_id="project-1",
            source_scope={"mode": "selected_sources"},
            evidence_refs=["chunk-1"],
            constraints={
                "max_items": 1,
                "current_question_id": "q-old",
                "humorous_distractors": True,
            },
            requested_output_shape="items",
            rag_source_ids=["file-1"],
            rag_context_snippets=[{"chunk_id": "chunk-1", "text": "慢启动"}],
        )
    )

    assert result.items[0].item_id == "q-1"
    assert result.items[0].expected_response == "探测可用带宽"
    assert client.last_messages is not None
    assert "current_question_id" in client.last_messages[1]["content"]
    assert client.last_max_tokens == 1000


def test_content_primitives_repair_malformed_structure_json() -> None:
    class RepairingContentPrimitiveClient(llm_client_mod.OpenAICompatibleLLMClient):
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
                return '{"units":[{"unit_id":"node-1","title":"坏 JSON" "summary":"少逗号"}],"anchors":[],"source_refs":[],"revision_targets":[],"warnings":[]}'
            return json.dumps(
                {
                    "units": [
                        {
                            "unit_id": "node-1",
                            "title": "拥塞窗口变化",
                            "summary": "围绕窗口增长和收缩组织节点。",
                            "key_points": ["慢启动"],
                            "source_refs": [],
                            "anchor_ref": "root",
                            "revision_target": "node-1",
                        }
                    ],
                    "anchors": ["root"],
                    "source_refs": [],
                    "revision_targets": ["node-1"],
                    "warnings": [],
                },
                ensure_ascii=False,
            )

    client = RepairingContentPrimitiveClient()
    result = asyncio.run(
        client.generate_structure_expansion(
            generation_goal="展开 TCP 拥塞控制",
            project_id="project-1",
            source_scope={"mode": "project_all"},
            evidence_refs=[],
            anchor_context=StructureExpansionAnchorContext(anchor_label="root"),
            constraints={"max_units": 4},
            requested_output_shape="units",
            rag_source_ids=[],
            rag_context_snippets=[],
        )
    )

    assert client.calls == 2
    assert result.units[0].title == "拥塞窗口变化"


def test_longform_section_normalizes_object_bullet_items() -> None:
    client = llm_client_mod.OpenAICompatibleLLMClient(
        base_url="https://api.example.com/v1",
        api_key="k",
        model="m",
    )
    section = client._parse_longform_section_or_raise(
        text=json.dumps(
            {
                "section_id": "wrong-model-id",
                "heading": "Ethernet 技术概述",
                "blocks": [
                    {"kind": "heading", "text": "Ethernet 技术概述"},
                    {"kind": "paragraph", "text": "以太网用于局域网链路层通信。"},
                    {
                        "kind": "bullet_list",
                        "items": [
                            {"text": "使用 48 位 MAC 地址"},
                            {"content": "帧内包含 EtherType 字段"},
                            {"title": "缺少内置用户认证"},
                        ],
                    },
                ],
                "citations": [{"source_id": "chunk-1"}],
                "revision": "1",
            },
            ensure_ascii=False,
        ),
        section_id="S3",
        heading="Ethernet 技术概述",
        key_points=["MAC 地址"],
        source_refs=["chunk-1"],
    )

    assert section.section_id == "S3"
    assert section.blocks[2].items == [
        "使用 48 位 MAC 地址",
        "帧内包含 EtherType 字段",
        "缺少内置用户认证",
    ]
    assert section.citations == ["chunk-1"]


def test_longform_section_parse_error_uses_json_repair() -> None:
    class RepairingLongformClient(llm_client_mod.OpenAICompatibleLLMClient):
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
                return '{"section_id":"S1","heading":"坏 JSON","blocks":[{"kind":"paragraph","text":"少逗号" "oops"}],"citations":[],"revision":"1"}'
            return json.dumps(
                {
                    "section_id": "wrong",
                    "heading": "教学目标",
                    "blocks": [
                        {"kind": "heading", "text": "教学目标"},
                        {"kind": "paragraph", "text": "学生能够比较 PPP、PPPoE 与 Ethernet。"},
                        {"kind": "bullet_list", "items": [{"text": "识别帧结构差异"}]},
                    ],
                    "citations": [{"source_id": "chunk-1"}],
                    "revision": "1",
                },
                ensure_ascii=False,
            )

    client = RepairingLongformClient()
    result = asyncio.run(
        client.generate_section_draft(
            topic="PPP 对比",
            project_id="project-1",
            audience="undergraduate",
            purpose="teaching document",
            tone="classroom-ready",
            plan=LongFormPlan(
                version=1,
                title="PPP 对比",
                summary="",
                sections=[
                    LongFormPlanSection(
                        section_id="S1",
                        title="教学目标",
                        summary="",
                        key_points=["识别帧结构差异"],
                        source_refs=["chunk-1"],
                    )
                ],
            ),
            section_id="S1",
            rag_source_ids=["file-1"],
            rag_context_snippets=[],
        )
    )

    assert client.calls == 2
    assert result.section_id == "S1"
    assert result.blocks[2].items == ["识别帧结构差异"]
