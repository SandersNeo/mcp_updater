from __future__ import annotations

import asyncio
import inspect
import json
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit, urlunsplit

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
    progress_callback = _default_progress_callback if config.diagnostic else None
    return await _run_smoke_test_internal(config, session_factory, progress_callback=progress_callback)


async def _run_smoke_test_internal(
    config: SmokeToolConfig,
    session_factory,
    *,
    progress_callback: Callable[[str], None] | None = None,
) -> SmokeTestRunResult:
    _emit_progress(progress_callback, f"connect:start url={config.url}")
    async with _create_session(session_factory, config.url, progress_callback=progress_callback) as session:
        _emit_progress(progress_callback, "connect:ok")
        _emit_progress(progress_callback, "list_tools:start")
        tools_response = await session.list_tools()
        tool_names = [tool.name for tool in getattr(tools_response, "tools", [])]
        _emit_progress(progress_callback, f"list_tools:ok count={len(tool_names)}")

        if config.metadata_tool_name not in tool_names:
            raise SmokeTestError(f"Required metadata tool is missing: {config.metadata_tool_name}")

        metadata_ok = False
        for query in config.metadata_queries:
            _emit_progress(progress_callback, f"call_tool:start name={config.metadata_tool_name} query={query!r}")
            result = await session.call_tool(config.metadata_tool_name, {config.metadata_query_argument: query})
            if _result_has_content(result):
                _emit_progress(progress_callback, f"call_tool:ok name={config.metadata_tool_name} query={query!r}")
                metadata_ok = True
                break
            _emit_progress(progress_callback, f"call_tool:empty name={config.metadata_tool_name} query={query!r}")
        if not metadata_ok:
            raise SmokeTestError(f"Metadata tool '{config.metadata_tool_name}' did not return a non-empty result.")

        code_ok = True
        if config.index_code:
            if config.code_tool_name not in tool_names:
                raise SmokeTestError(f"Required code tool is missing: {config.code_tool_name}")
            code_ok = False
            for query in config.code_queries:
                _emit_progress(progress_callback, f"call_tool:start name={config.code_tool_name} query={query!r}")
                result = await session.call_tool(config.code_tool_name, {config.code_query_argument: query})
                if _result_has_content(result):
                    _emit_progress(progress_callback, f"call_tool:ok name={config.code_tool_name} query={query!r}")
                    code_ok = True
                    break
                _emit_progress(progress_callback, f"call_tool:empty name={config.code_tool_name} query={query!r}")
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
        overall_timeout_seconds=int(payload.get("overallTimeoutSeconds", payload["timeoutSeconds"])),
        index_code=bool(payload["indexCode"]),
        diagnostic=bool(payload.get("diagnostic", False)),
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


def _sdk_session_factory(url: str, *, progress_callback: Callable[[str], None] | None = None):
    return _MCPStreamableHTTPSession(url, progress_callback=progress_callback)


class _MCPStreamableHTTPSession:
    def __init__(self, url: str, progress_callback: Callable[[str], None] | None = None) -> None:
        self.url = _normalize_mcp_url(url)
        self.progress_callback = progress_callback
        self._transport_context = None
        self._session_context = None
        self._session = None
        self._exit_stack = None

    async def __aenter__(self):
        try:
            import httpx
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except ImportError as exc:
            raise SmokeTestError("Python package 'mcp' is not installed.") from exc

        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()
        http_client = await self._exit_stack.enter_async_context(
            httpx.AsyncClient(follow_redirects=True, timeout=20.0)
        )

        self._transport_context = streamable_http_client(self.url, http_client=http_client)
        transport_values = await self._exit_stack.enter_async_context(self._transport_context)
        if len(transport_values) >= 2:
            read_stream, write_stream = transport_values[0], transport_values[1]
        else:
            raise SmokeTestError("Streamable HTTP client did not provide read/write streams.")

        self._session_context = ClientSession(read_stream, write_stream)
        self._session = await self._exit_stack.enter_async_context(self._session_context)
        _emit_progress(self.progress_callback, "initialize:start")
        await self._session.initialize()
        _emit_progress(self.progress_callback, "initialize:ok")
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        if self._exit_stack is not None:
            await self._exit_stack.__aexit__(exc_type, exc, tb)


def _normalize_mcp_url(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path or "/"
    if path.endswith("/mcp"):
        path = f"{path}/"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def _emit_progress(progress_callback: Callable[[str], None] | None, message: str) -> None:
    if progress_callback is not None:
        progress_callback(message)


def _default_progress_callback(message: str) -> None:
    print(f"[diagnostic] {message}", file=sys.stderr, flush=True)


def _create_session(session_factory, url: str, *, progress_callback: Callable[[str], None] | None):
    signature = inspect.signature(session_factory)
    if "progress_callback" in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
    ):
        return session_factory(url, progress_callback=progress_callback)
    return session_factory(url)
