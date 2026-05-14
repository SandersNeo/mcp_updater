from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from mcp_smoke_test.client import SmokeTestError, _normalize_mcp_url, load_smoke_config, run_smoke_test
from mcp_smoke_test.result import SmokeToolConfig


class _FakeText:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResult:
    def __init__(self, content) -> None:
        self.content = content


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeListToolsResult:
    def __init__(self, tools) -> None:
        self.tools = tools


class _FakeSession:
    def __init__(self, tools, responses) -> None:
        self._tools = tools
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def list_tools(self):
        return _FakeListToolsResult([_FakeTool(name) for name in self._tools])

    async def call_tool(self, name, arguments):
        return self._responses[(name, next(iter(arguments.values())))]


def test_load_smoke_config(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "url": "http://localhost:18100/mcp",
                "timeoutSeconds": 60,
                "overallTimeoutSeconds": 300,
                "indexCode": True,
                "diagnostic": True,
                "metadataQueries": ["Конфигурации"],
                "codeQueries": ["Процедура"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    config = load_smoke_config(path)

    assert config.metadata_tool_name == "metadatasearch"
    assert config.code_tool_name == "codesearch"
    assert config.diagnostic is True
    assert config.overall_timeout_seconds == 300


def test_run_smoke_test_success() -> None:
    config = SmokeToolConfig(
        url="http://localhost:18100/mcp",
        timeout_seconds=5,
        overall_timeout_seconds=30,
        index_code=True,
        diagnostic=False,
        metadata_tool_name="metadatasearch",
        metadata_query_argument="query",
        metadata_queries=["Конфигурации"],
        code_tool_name="codesearch",
        code_query_argument="query",
        code_queries=["Процедура"],
    )

    async def _run():
        return await run_smoke_test(
            config,
            session_factory=lambda url: _FakeSession(
                ["metadatasearch", "codesearch"],
                {
                    ("metadatasearch", "Конфигурации"): _FakeResult([_FakeText("ok")]),
                    ("codesearch", "Процедура"): _FakeResult([_FakeText("ok")]),
                },
            ),
        )

    result = asyncio.run(_run())

    assert result.metadata_ok is True
    assert result.code_ok is True


def test_run_smoke_test_fails_when_tool_missing() -> None:
    config = SmokeToolConfig(
        url="http://localhost:18100/mcp",
        timeout_seconds=5,
        overall_timeout_seconds=30,
        index_code=False,
        diagnostic=False,
        metadata_tool_name="metadatasearch",
        metadata_query_argument="query",
        metadata_queries=["Конфигурации"],
        code_tool_name="codesearch",
        code_query_argument="query",
        code_queries=["Процедура"],
    )

    async def _run():
        return await run_smoke_test(
            config,
            session_factory=lambda url: _FakeSession([], {}),
        )

    with pytest.raises(SmokeTestError):
        asyncio.run(_run())


def test_normalize_mcp_url_adds_trailing_slash_for_mcp_path() -> None:
    assert _normalize_mcp_url("http://localhost:18100/mcp") == "http://localhost:18100/mcp/"
    assert _normalize_mcp_url("http://localhost:18100/mcp/") == "http://localhost:18100/mcp/"


def test_run_smoke_test_emits_diagnostics(capsys: pytest.CaptureFixture[str]) -> None:
    config = SmokeToolConfig(
        url="http://localhost:18100/mcp",
        timeout_seconds=5,
        overall_timeout_seconds=30,
        index_code=True,
        diagnostic=True,
        metadata_tool_name="metadatasearch",
        metadata_query_argument="query",
        metadata_queries=["metadata"],
        code_tool_name="codesearch",
        code_query_argument="query",
        code_queries=["code"],
    )

    async def _run():
        return await run_smoke_test(
            config,
            session_factory=lambda url: _FakeSession(
                ["metadatasearch", "codesearch"],
                {
                    ("metadatasearch", "metadata"): _FakeResult([_FakeText("ok")]),
                    ("codesearch", "code"): _FakeResult([_FakeText("ok")]),
                },
            ),
        )

    result = asyncio.run(_run())
    captured = capsys.readouterr()

    assert result.metadata_ok is True
    assert result.code_ok is True
    assert "[diagnostic] list_tools:start" in captured.err
    assert "[diagnostic] call_tool:ok name=metadatasearch query='metadata'" in captured.err
