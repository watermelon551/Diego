from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from service.run.slide_preview import render_slide_via_pagevra


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *, payload: dict) -> None:
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, _url: str, json: dict) -> _FakeResponse:
        assert json["render"]["outputs"] == ["preview"]
        return _FakeResponse(200, self._payload)


@pytest.mark.anyio
async def test_render_slide_via_pagevra_accepts_image_only_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slide_js_path = tmp_path / "slide1.js"
    slide_js_path.write_text("export default {};\n", encoding="utf-8")

    monkeypatch.setattr(
        "service.run.slide_preview._capture_slide_payload",
        AsyncMock(return_value={"title": "Preview", "operations": []}),
    )
    monkeypatch.setattr(
        "service.run.slide_preview._build_pagevra_render_input",
        lambda **_: {
            "render_job_id": "preview-job",
            "page_id": "slide-1",
            "page_index": 0,
            "render": {"outputs": ["preview"]},
        },
    )
    monkeypatch.setattr(
        "service.run.slide_preview.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(
            payload={
                "state": "success",
                "preview_image_data_url": "data:image/png;base64,preview",
            }
        ),
    )

    result = await render_slide_via_pagevra(
        slide_js_path=slide_js_path,
        theme={"accent": "#123456", "bg": "#ffffff", "secondary": "#111111"},
        slide_no=1,
        pagevra_base_url="http://pagevra.test",
    )

    assert result["image_url"] == "data:image/png;base64,preview"
    assert result["html_preview"] is None
    assert result["width"] == 1280
    assert result["height"] == 720
