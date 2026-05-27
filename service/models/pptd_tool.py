from __future__ import annotations

from pydantic import BaseModel


class PptdCheckRequest(BaseModel):
    pptd_path: str


class PptdCompileRequest(BaseModel):
    pptd_path: str
    output_path: str


class PptdScreenshotRequest(BaseModel):
    pptx_path: str
    output_dir: str
    pages: str = "all"
