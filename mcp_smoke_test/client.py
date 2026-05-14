from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .result import SmokeTestRunResult, SmokeToolConfig


class SmokeTestError(Exception):
    pass


class MCPClientProtocol(Protocol):
    async def list_tools(self): ...
    async def call_tool(self, name: str, arguments: dict[str, Any]): ...


@dataclass(slots=True)
class SessionFactoryConfig:
    url: str


async def run_smoke_test(config: SmokeToolConfig, session_factory=None) -> SmokeTestRunResult:
    session_factory = session_factory or _sdk_session_factory
    return await _run_smoke_test_internal(config, session_factory)


async def _run_smoke_test_internal(config: SmokeToolConfig, session_factory) -> SmokeTestRunResult:
    async with session_factory(config.url) as session:
        tools_response = await session.list_tools()
        tool_names = [tool.name for tool in getattr(tools_response, "tools", [])]

        if config.metadata_tool_name not in tool_names:
            raise SmokeTestError(f"Required metadata tool is missing: {config.metadata_tool_name}")

        metadata_ok = False
        for query in config.metadata_queries:
            result = await session.call_tool(config.metadata_tool_name, {config.metadata_query_argument: query})
            if _result_has_content(result):
                metadata_ok = True
                break
        if not metadata_ok:
            raise SmokeTestError(f"Metadata tool '{config.metadata_tool_name}' did not return a non-empty result.")

        code_ok = True
        if config.index_code:
            if config.code_tool_name not in tool_names:
                raise SmokeTestError(f"Required code tool is missing: {config.code_tool_name}")
            code_ok = False
            for query in config.code_queries:
                result = await session.call_tool(config.code_tool_name, {config.code_query_argument: query})
                if _result_has_content(result):
                    code_ok = True
                    break
            if not code_ok:
                raise SmokeTestError(f"Code tool '{config.code_tool_name}' did not return a non-empty result.")

        return SmokeTestRunResult(
            listed_tools=tool_names,
            metadata_ok=metadata_ok,
            code_ok=code_ok,
        )


def load_smoke_config(config_path: Path) -> SmokeToolConfig:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return SmokeToolConfig(
        url=str(payload["url"]),
        timeout_seconds=int(payload["timeoutSeconds"]),
        index_code=bool(payload["indexCode"]),
        metadata_tool_name=str(payload.get("metadataToolName", "metadatasearch")),
        metadata_query_argument=str(payload.get("metadataQueryArgument", "query")),
        metadata_queries=[str(item) for item in payload.get("metadataQueries", [])],
        code_tool_name=str(payload.get("codeToolName", "codesearch")),
        code_query_argument=str(payload.get("codeQueryArgument", "query")),
        code_queries=[str(item) for item in payload.get("codeQueries", [])],
    )


def _result_has_content(result: Any) -> bool:
    content = getattr(result, "content", None)
    if not content:
        return False

    for item in content:
        text = getattr(item, "text", None)
        if isinstance(text, str) and text.strip():
            return True
        if isinstance(item, dict):
            for key in ("text", "content", "result"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    return True
    return False


def _sdk_session_factory(url: str):
    return _MCPStreamableHTTPSession(url)


class _MCPStreamableHTTPSession:
    def __init__(self, url: str) -> None:
        self.url = url
        self._transport_context = None
        self._session_context = None
        self._session = None

    async def __aenter__(self):
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except ImportError as exc:
            raise SmokeTestError("Python package 'mcp' is not installed.") from exc

        self._transport_context = streamable_http_client(self.url)
        transport_values = await self._transport_context.__aenter__()
        if len(transport_values) >= 2:
            read_stream, write_stream = transport_values[0], transport_values[1]
        else:
            raise SmokeTestError("Streamable HTTP client did not provide read/write streams.")

        self._session_context = ClientSession(read_stream, write_stream)
        self._session = await self._session_context.__aenter__()
        await self._session.initialize()
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        if self._session_context is not None:
            await self._session_context.__aexit__(exc_type, exc, tb)
        if self._transport_context is not None:
            await self._transport_context.__aexit__(exc_type, exc, tb)
