from __future__ import annotations

import re
import subprocess
import time
import json
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from service.api.app import create_app
from service.config import Settings
from service.llm import MockLLMClient
from service.run.orchestrator import RunOrchestrator
from service.infra.store import RunStore


def fake_subprocess_run(args, cwd=None, capture_output=False, text=False, check=False, **kwargs):
    cmd = " ".join(args) if isinstance(args, (list, tuple)) else str(args)
    if "node" in cmd and "compile.js" in cmd:
        out = Path(cwd) / "output"
        out.mkdir(parents=True, exist_ok=True)
        (out / "presentation.pptx").write_bytes(b"fake-pptx")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="compiled", stderr="")
    if "node" in cmd and ".html-preview-runner-" in cmd:
        payload = {
            "operations": [
                {
                    "kind": "shape",
                    "payload": {
                        "shape": "RECTANGLE",
                        "options": {"x": 0.4, "y": 0.4, "w": 9.2, "h": 4.8},
                    },
                },
                {
                    "kind": "text",
                    "payload": {
                        "content": "Preview Title",
                        "options": {"x": 0.8, "y": 0.8, "w": 6.2, "h": 0.8, "fontSize": 32},
                    },
                },
            ],
            "background": {"color": "FFFFFF"},
            "slide_config": {"index": 1},
            "theme": {
                "primary": "111111",
                "secondary": "222222",
                "accent": "0A84FF",
                "light": "EEF2F7",
                "bg": "FFFFFF",
            },
        }
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(payload, ensure_ascii=False),
            stderr="",
        )
    if "node" in cmd and ".preview-runner-" in cmd:
        match = re.search(r"\.preview-runner-(\d+)\.js", cmd)
        if match:
            preview = Path(cwd) / f"slide-{int(match.group(1)):02d}-preview.pptx"
            preview.write_bytes(b"fake-preview-pptx")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="preview", stderr="")
    if "node" in cmd and "slide-" in cmd and cmd.strip().endswith(".js"):
        match = re.search(r"slide-(\d+)(?:-cand-\d+)?\.js", cmd)
        if match:
            preview = Path(cwd) / f"slide-{int(match.group(1)):02d}-preview.pptx"
            preview.write_bytes(b"fake-preview-pptx")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="preview", stderr="")
    if "python" in cmd and "markitdown" in cmd:
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="slide content extracted", stderr="")
    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")


def make_settings(**overrides) -> Settings:
    settings = Settings(
        llm_api_style="openai_chat",
        llm_base_url="https://api.example.com",
        llm_api_key="test",
        llm_model="test-model",
        llm_timeout_sec=30.0,
        llm_max_retries=2,
        llm_temperature_outline=0.3,
        llm_temperature_slide=0.6,
        slide_concurrency=2,
        slide_retry=2,
        qa_enabled=True,
        repair_rounds=2,
        asset_provider="mock",
        unsplash_access_key="",
        pexels_api_key="",
        asset_timeout_sec=5.0,
        asset_max_retries=1,
        generation_engine="legacy",
        debug_keep_previews=False,
        max_slide_repair_rounds=2,
        outline_timeout_retries=3,
        outline_timeout_backoff_sec=0.0,
        outline_structured_output=True,
        compile_provider="none",
        pagevra_base_url="",
        pagevra_preview_enabled=False,
        pagevra_preview_timeout_sec=10.0,
        pagevra_compile_timeout_sec=10.0,
    )
    return replace(settings, **overrides) if overrides else settings


def make_client(tmp_path: Path, llm_client: MockLLMClient | None = None, **settings_overrides) -> TestClient:
    orch = RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=llm_client or MockLLMClient(),
        settings=make_settings(**settings_overrides),
    )
    client = TestClient(create_app(base_dir=tmp_path, orchestrator=orch))
    client.__enter__()
    return client


def wait_status(client: TestClient, run_id: str, expected: set[str], timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/v1/ppt/runs/{run_id}").json()
        if data["status"] in expected:
            return data
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} not in {expected} within {timeout}s")
