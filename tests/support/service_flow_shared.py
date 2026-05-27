from __future__ import annotations

import asyncio
import json
import posixpath
import re
import subprocess
import time
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient

import service.llm as llm_client_mod
import service.run.orchestrator as orchestrator_mod
from service.api.app import create_app
from service.config import Settings, load_settings
from service.llm import GeneratedSlide, LLMTimeoutError, MockLLMClient, OutlineFormatError, SlideSpec
from service.models import CreateRunRequest, EventType, GenerationMode, OutlineDocument, OutlineNode, RunRecord, RunStatus, SlidePageType
from service.run.orchestrator import RunOrchestrator
from service.infra.store import RunStore

from .llm_doubles import *
from .runtime_helpers import fake_subprocess_run, make_client, make_settings, wait_status
from .template_builders import *


@pytest.fixture(autouse=True)
def patch_tools(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(orchestrator_mod.subprocess, "run", fake_subprocess_run)
    yield
