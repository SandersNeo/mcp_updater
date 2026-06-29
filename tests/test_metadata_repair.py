from __future__ import annotations

import json

import pytest

from mcp_project_updater.constants import ExitCode
from mcp_project_updater.metadata_repair import MetadataIndexRepairError, run_metadata_index_repair


class _FakeText:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResult:
    def __init__(self, payload) -> None:
        self.content = [_FakeText(json.dumps(payload))]


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeListToolsResult:
    def __init__(self, names: list[str]) -> None:
        self.tools = [_FakeTool(name) for name in names]


class _FakeSession:
    def __init__(self, *, tools: list[str], stats_payloads: list[dict]) -> None:
        self.tools = tools
        self.stats_payloads = stats_payloads
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def list_tools(self):
        return _FakeListToolsResult(self.tools)

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "stats":
            return _FakeResult(self.stats_payloads.pop(0))
        if name == "reindex":
            return _FakeResult({"status": "accepted"})
        raise AssertionError(name)


def _stats_payload(*, metadata: int, code: int, running: bool = False) -> dict:
    return {
        "status": "success",
        "data": {
            "collections": {
                "metadata": metadata,
                "code": code,
            },
            "indexing": {
                "running": running,
            },
        },
    }


def test_run_metadata_index_repair_calls_force_reindex(monkeypatch) -> None:
    session = _FakeSession(
        tools=["stats", "reindex"],
        stats_payloads=[
            _stats_payload(metadata=0, code=10),
            _stats_payload(metadata=5, code=10),
        ],
    )
    monkeypatch.setattr("mcp_project_updater.metadata_repair._MCPStreamableHTTPSession", lambda *args, **kwargs: session)

    result = run_metadata_index_repair(
        "http://localhost:18100/mcp",
        timeout_seconds=10,
        retry_interval_seconds=1,
        require_code_index=True,
    )

    assert result.metadata_count == 5
    assert result.code_count == 10
    assert ("reindex", {"force": True}) in session.calls


def test_run_metadata_index_repair_requires_reindex_tool(monkeypatch) -> None:
    session = _FakeSession(
        tools=["stats"],
        stats_payloads=[_stats_payload(metadata=0, code=10)],
    )
    monkeypatch.setattr("mcp_project_updater.metadata_repair._MCPStreamableHTTPSession", lambda *args, **kwargs: session)

    with pytest.raises(MetadataIndexRepairError) as exc:
        run_metadata_index_repair(
            "http://localhost:18100/mcp",
            timeout_seconds=10,
            retry_interval_seconds=1,
            require_code_index=True,
        )

    assert exc.value.exit_code == ExitCode.BUILD_SMOKE_FAILED
    assert "reindex" in str(exc.value)
