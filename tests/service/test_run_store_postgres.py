from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from service.infra.postgres_store.schema_migrations import (
    POSTGRES_STORE_MIGRATIONS,
    apply_postgres_store_migrations,
)
from service.infra.store import PostgresRunStore, RunStore, now_iso
from service.models import (
    CreateRunRequest,
    EventType,
    RunEvent,
    RunRecord,
    RunStatus,
    TemplateRecord,
)


class _FakeAcquire:
    def __init__(self, conn) -> None:
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeTransaction:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakePostgresState:
    def __init__(self) -> None:
        self.runs: dict[str, str] = {}
        self.run_events: dict[str, dict[int, str]] = {}
        self.templates: dict[str, str] = {}
        self.migrations: list[str] = []
        self.executed_sql: list[str] = []
        self.create_pool_calls = 0
        self.pool_args: list[tuple[str, int, int]] = []


class _FakeConnection:
    def __init__(self, state: _FakePostgresState) -> None:
        self.state = state

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction()

    async def execute(self, sql: str, *args) -> None:
        normalized = " ".join(sql.split())
        self.state.executed_sql.append(normalized)
        if "CREATE TABLE IF NOT EXISTS diego_store_migrations" in normalized:
            return None
        if "CREATE TABLE IF NOT EXISTS diego_runs" in normalized:
            return None
        if "CREATE TABLE IF NOT EXISTS diego_run_events" in normalized:
            return None
        if "CREATE INDEX IF NOT EXISTS idx_diego_run_events_run_seq" in normalized:
            return None
        if "CREATE TABLE IF NOT EXISTS diego_templates" in normalized:
            return None
        if normalized.startswith("INSERT INTO diego_store_migrations(version)"):
            version = str(args[0])
            if version not in self.state.migrations:
                self.state.migrations.append(version)
            return None
        if normalized.startswith("INSERT INTO diego_runs(run_id, run_json)"):
            run_id, run_json = str(args[0]), str(args[1])
            self.state.runs[run_id] = run_json
            self.state.run_events.setdefault(run_id, {})
            return None
        if normalized.startswith("DELETE FROM diego_run_events WHERE run_id=$1"):
            self.state.run_events[str(args[0])] = {}
            return None
        if normalized.startswith("INSERT INTO diego_run_events(run_id, seq, event_json)"):
            run_id, seq, event_json = str(args[0]), int(args[1]), str(args[2])
            self.state.run_events.setdefault(run_id, {})[seq] = event_json
            return None
        if normalized.startswith("UPDATE diego_runs SET run_json=$2::jsonb"):
            run_id, run_json = str(args[0]), str(args[1])
            self.state.runs[run_id] = run_json
            return None
        if normalized.startswith("INSERT INTO diego_templates(template_id, template_json)"):
            template_id, template_json = str(args[0]), str(args[1])
            self.state.templates[template_id] = template_json
            return None
        raise AssertionError(f"unexpected execute SQL: {normalized}")

    async def fetch(self, sql: str, *args):
        normalized = " ".join(sql.split())
        if normalized == "SELECT version FROM diego_store_migrations ORDER BY version ASC":
            return [{"version": version} for version in self.state.migrations]
        if normalized.startswith(
            "SELECT event_json FROM diego_run_events WHERE run_id=$1 ORDER BY seq ASC"
        ):
            run_id = str(args[0])
            return [
                {"event_json": payload}
                for _seq, payload in sorted(
                    self.state.run_events.get(run_id, {}).items(), key=lambda item: item[0]
                )
            ]
        if normalized.startswith(
            "SELECT run_id FROM diego_runs ORDER BY created_at ASC, run_id ASC"
        ):
            return [{"run_id": run_id} for run_id in self.state.runs]
        raise AssertionError(f"unexpected fetch SQL: {normalized}")

    async def fetchrow(self, sql: str, *args):
        normalized = " ".join(sql.split())
        if normalized in {
            "SELECT run_json FROM diego_runs WHERE run_id=$1",
            "SELECT run_json FROM diego_runs WHERE run_id=$1 FOR UPDATE",
        }:
            run_id = str(args[0])
            payload = self.state.runs.get(run_id)
            return None if payload is None else {"run_json": payload}
        if normalized == "SELECT template_json FROM diego_templates WHERE template_id=$1":
            template_id = str(args[0])
            payload = self.state.templates.get(template_id)
            return None if payload is None else {"template_json": payload}
        raise AssertionError(f"unexpected fetchrow SQL: {normalized}")

    async def fetchval(self, sql: str, *args):
        normalized = " ".join(sql.split())
        if normalized.startswith(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM diego_run_events WHERE run_id=$1"
        ):
            run_id = str(args[0])
            current = self.state.run_events.get(run_id, {})
            return (max(current) if current else 0) + 1
        raise AssertionError(f"unexpected fetchval SQL: {normalized}")


class _FakePool:
    def __init__(self, state: _FakePostgresState) -> None:
        self._conn = _FakeConnection(state)

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self._conn)


def _install_fake_asyncpg(monkeypatch: pytest.MonkeyPatch) -> _FakePostgresState:
    state = _FakePostgresState()

    async def create_pool(database_url: str, min_size: int = 1, max_size: int = 8):
        state.create_pool_calls += 1
        state.pool_args.append((database_url, min_size, max_size))
        return _FakePool(state)

    monkeypatch.setitem(
        sys.modules,
        "asyncpg",
        SimpleNamespace(create_pool=create_pool),
    )
    return state


def _make_run(tmp_path: Path, run_id: str = "run-1") -> RunRecord:
    return RunRecord(
        run_id=run_id,
        trace_id=f"trace-{run_id}",
        status=RunStatus.OUTLINE_DRAFTING,
        input=CreateRunRequest(topic="Store Contract", project_id="project-1"),
        artifact_dir=str(tmp_path / "artifacts" / run_id),
    )


def _make_template(tmp_path: Path, template_id: str = "template-1") -> TemplateRecord:
    return TemplateRecord(
        template_id=template_id,
        filename="template.pptx",
        path=str(tmp_path / "templates" / "template.pptx"),
        created_at=now_iso(),
    )


def _exercise_store_contract(store, tmp_path: Path) -> None:
    async def scenario() -> None:
        run = _make_run(tmp_path)
        await store.add_run(run)
        loaded = await store.get_run(run.run_id)
        assert loaded is not None
        assert loaded.run_id == run.run_id
        assert loaded.input.project_id == "project-1"

        updated = await store.update_run(
            run.run_id,
            lambda record: setattr(record, "status", RunStatus.AWAITING_OUTLINE_CONFIRM),
        )
        assert updated.status == RunStatus.AWAITING_OUTLINE_CONFIRM

        event = RunEvent(
            seq=0,
            event=EventType.OUTLINE_COMPLETED,
            ts=now_iso(),
            payload={"outline_version": 1},
        )
        await store.append_event(run.run_id, event)
        waited = await store.wait_for_event(run.run_id, cursor=0, timeout=0.2)
        assert len(waited.events) == 1
        assert waited.events[0].event == EventType.OUTLINE_COMPLETED

        listed = await store.list_runs()
        assert [item.run_id for item in listed] == [run.run_id]

        template = _make_template(tmp_path)
        await store.add_template(template)
        loaded_template = await store.get_template(template.template_id)
        assert loaded_template is not None
        assert loaded_template.filename == template.filename

    asyncio.run(scenario())


def test_memory_run_store_should_satisfy_run_store_contract(tmp_path: Path) -> None:
    _exercise_store_contract(RunStore(base_dir=tmp_path), tmp_path)


def test_postgres_run_store_should_satisfy_run_store_contract_with_fake_asyncpg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _install_fake_asyncpg(monkeypatch)
    store = PostgresRunStore(
        base_dir=tmp_path,
        database_url="postgresql://diego:test@db/diego",
    )

    _exercise_store_contract(store, tmp_path)

    assert state.create_pool_calls == 1
    assert state.pool_args == [("postgresql://diego:test@db/diego", 1, 8)]
    assert state.migrations == [POSTGRES_STORE_MIGRATIONS[0][0]]


def test_postgres_run_store_initialize_should_apply_schema_migrations_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _install_fake_asyncpg(monkeypatch)
    store = PostgresRunStore(
        base_dir=tmp_path,
        database_url="postgresql://diego:test@db/diego",
    )

    async def scenario() -> None:
        await store.initialize()
        await store.initialize()

    asyncio.run(scenario())

    assert state.create_pool_calls == 1
    assert state.migrations == [POSTGRES_STORE_MIGRATIONS[0][0]]
    assert sum(
        1
        for sql in state.executed_sql
        if "CREATE TABLE IF NOT EXISTS diego_store_migrations" in sql
    ) == 1


def test_apply_postgres_store_migrations_should_create_generation_run_tables(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _install_fake_asyncpg(monkeypatch)
    conn = _FakeConnection(state)

    async def scenario() -> None:
        await apply_postgres_store_migrations(conn)

    asyncio.run(scenario())

    assert state.migrations == [POSTGRES_STORE_MIGRATIONS[0][0]]
    sql_text = "\n".join(state.executed_sql)
    assert "diego_runs" in sql_text
    assert "diego_run_events" in sql_text
    assert "diego_templates" in sql_text
    assert "diego_store_migrations" in sql_text
