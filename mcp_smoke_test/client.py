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
    return await _run_smoke_test_internal(
        config,
        session_factory,
        progress_callback=progress_callback,
        request_timeout_seconds=config.timeout_seconds,
    )


async def _run_smoke_test_internal(
    config: SmokeToolConfig,
    session_factory,
    *,
    progress_callback: Callable[[str], None] | None = None,
    request_timeout_seconds: int | None = None,
) -> SmokeTestRunResult:
    _emit_progress(progress_callback, f"connect:start url={config.url}")
    async with _create_session(
        session_factory,
        config.url,
        progress_callback=progress_callback,
        request_timeout_seconds=request_timeout_seconds,
    ) as session:
        _emit_progress(progress_callback, "connect:ok")
        _emit_progress(progress_callback, "list_tools:start")
        tools_response = await _call_session(
            session.list_tools,
            progress_callback=progress_callback,
            stage="list_tools",
        )
        tool_names = [tool.name for tool in getattr(tools_response, "tools", [])]
        _emit_progress(progress_callback, f"list_tools:ok count={len(tool_names)}")

        if config.metadata_tool_name not in tool_names:
            raise SmokeTestError(f"Required metadata tool is missing: {config.metadata_tool_name}")
        stats_ok = await _validate_index_stats(session, config, tool_names, progress_callback)

        metadata_ok = False
        metadata_layer_mismatch = None
        for query in config.metadata_queries:
            _emit_progress(progress_callback, f"call_tool:start name={config.metadata_tool_name} query={query!r}")
            result = await _call_session(
                session.call_tool,
                config.metadata_tool_name,
                {config.metadata_query_argument: query},
                progress_callback=progress_callback,
                stage=f"{config.metadata_tool_name}({query})",
            )
            if _result_has_content(result):
                if config.require_metadata_vector_index and _result_search_layer(result) != "vector+bm25":
                    metadata_layer_mismatch = _result_search_layer(result) or "<missing>"
                    _emit_progress(
                        progress_callback,
                        f"call_tool:fallback name={config.metadata_tool_name} layer={metadata_layer_mismatch}",
                    )
                    continue
                _emit_progress(progress_callback, f"call_tool:ok name={config.metadata_tool_name} query={query!r}")
                metadata_ok = True
                break
            _emit_progress(progress_callback, f"call_tool:empty name={config.metadata_tool_name} query={query!r}")
        if not metadata_ok:
            if metadata_layer_mismatch is not None:
                raise SmokeTestError(
                    f"Metadata tool '{config.metadata_tool_name}' used fallback search_layer={metadata_layer_mismatch}; "
                    "expected vector+bm25."
                )
            raise SmokeTestError(f"Metadata tool '{config.metadata_tool_name}' did not return a non-empty result.")

        code_ok = True
        if config.index_code:
            if config.code_tool_name not in tool_names:
                raise SmokeTestError(f"Required code tool is missing: {config.code_tool_name}")
            code_ok = False
            code_layer_mismatch = None
            for query in config.code_queries:
                _emit_progress(progress_callback, f"call_tool:start name={config.code_tool_name} query={query!r}")
                result = await _call_session(
                    session.call_tool,
                    config.code_tool_name,
                    {config.code_query_argument: query},
                    progress_callback=progress_callback,
                    stage=f"{config.code_tool_name}({query})",
                )
                if _result_has_content(result):
                    if config.require_code_vector_index and _result_search_layer(result) != "vector+bm25":
                        code_layer_mismatch = _result_search_layer(result) or "<missing>"
                        _emit_progress(
                            progress_callback,
                            f"call_tool:fallback name={config.code_tool_name} layer={code_layer_mismatch}",
                        )
                        continue
                    _emit_progress(progress_callback, f"call_tool:ok name={config.code_tool_name} query={query!r}")
                    code_ok = True
                    break
                _emit_progress(progress_callback, f"call_tool:empty name={config.code_tool_name} query={query!r}")
            if not code_ok:
                if code_layer_mismatch is not None:
                    raise SmokeTestError(
                        f"Code tool '{config.code_tool_name}' used fallback search_layer={code_layer_mismatch}; "
                        "expected vector+bm25."
                    )
                raise SmokeTestError(f"Code tool '{config.code_tool_name}' did not return a non-empty result.")

        return SmokeTestRunResult(
            listed_tools=tool_names,
            metadata_ok=metadata_ok,
            code_ok=code_ok,
            stats_ok=stats_ok,
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
        require_metadata_vector_index=bool(payload.get("requireMetadataVectorIndex", True)),
        require_code_vector_index=bool(payload.get("requireCodeVectorIndex", True)),
    )


async def _validate_index_stats(
    session,
    config: SmokeToolConfig,
    tool_names: list[str],
    progress_callback: Callable[[str], None] | None,
) -> bool:
    if not (config.require_metadata_vector_index or (config.index_code and config.require_code_vector_index)):
        return True
    if "stats" not in tool_names:
        raise SmokeTestError("Required stats tool is missing.")

    _emit_progress(progress_callback, "call_tool:start name=stats")
    result = await _call_session(
        session.call_tool,
        "stats",
        {},
        progress_callback=progress_callback,
        stage="stats",
    )
    payload = _result_json(result)
    if payload.get("status") != "success":
        raise SmokeTestError("Stats tool did not return success.")
    data = payload.get("data")
    collections = data.get("collections") if isinstance(data, dict) else None
    if not isinstance(collections, dict):
        raise SmokeTestError("Stats tool response does not contain collections.")
    if config.require_metadata_vector_index and int(collections.get("metadata") or 0) <= 0:
        raise SmokeTestError("Metadata vector index is empty according to stats.collections.metadata.")
    if config.index_code and config.require_code_vector_index and int(collections.get("code") or 0) <= 0:
        raise SmokeTestError("Code vector index is empty according to stats.collections.code.")
    _emit_progress(progress_callback, "call_tool:ok name=stats")
    return True


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


def _result_json(result: Any) -> dict[str, Any]:
    content = getattr(result, "content", None)
    if not content:
        return {}
    text_parts = []
    for item in content:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            text_parts.append(text)
        elif isinstance(item, dict):
            value = item.get("text")
            if isinstance(value, str):
                text_parts.append(value)
    if not text_parts:
        return {}
    try:
        payload = json.loads("".join(text_parts))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _result_search_layer(result: Any) -> str | None:
    payload = _result_json(result)
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    layer = data.get("search_layer")
    return layer if isinstance(layer, str) else None


def _sdk_session_factory(
    url: str,
    *,
    progress_callback: Callable[[str], None] | None = None,
    request_timeout_seconds: int | None = None,
):
    return _MCPStreamableHTTPSession(
        url,
        progress_callback=progress_callback,
        request_timeout_seconds=request_timeout_seconds,
    )


class _MCPStreamableHTTPSession:
    def __init__(
        self,
        url: str,
        progress_callback: Callable[[str], None] | None = None,
        request_timeout_seconds: int | None = None,
    ) -> None:
        self.url = _normalize_mcp_url(url)
        self.progress_callback = progress_callback
        self.request_timeout_seconds = request_timeout_seconds
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
        timeout = httpx.Timeout(
            connect=min(float(self.request_timeout_seconds or 30), 30.0),
            read=None,
            write=None,
            pool=None,
        )
        http_client = await self._exit_stack.enter_async_context(
            httpx.AsyncClient(follow_redirects=True, timeout=timeout)
        )

        try:
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
        except SmokeTestError:
            await self._cleanup_on_failure()
            raise
        except Exception as exc:
            await self._cleanup_on_failure()
            raise SmokeTestError(f"MCP session initialization failed: {exc.__class__.__name__}: {exc}") from exc

    async def __aexit__(self, exc_type, exc, tb):
        if self._exit_stack is not None:
            await self._exit_stack.__aexit__(exc_type, exc, tb)

    async def _cleanup_on_failure(self) -> None:
        if self._exit_stack is not None:
            await self._exit_stack.__aexit__(None, None, None)
            self._exit_stack = None


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


def _create_session(
    session_factory,
    url: str,
    *,
    progress_callback: Callable[[str], None] | None,
    request_timeout_seconds: int | None,
):
    signature = inspect.signature(session_factory)
    supports_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
    )
    kwargs = {}
    if "progress_callback" in signature.parameters or supports_kwargs:
        kwargs["progress_callback"] = progress_callback
    if "request_timeout_seconds" in signature.parameters or supports_kwargs:
        kwargs["request_timeout_seconds"] = request_timeout_seconds
    if kwargs:
        return session_factory(url, **kwargs)
    return session_factory(url)


async def _call_session(callable_obj, *args, progress_callback: Callable[[str], None] | None, stage: str):
    try:
        return await callable_obj(*args)
    except SmokeTestError:
        raise
    except Exception as exc:
        _emit_progress(progress_callback, f"{stage}:error type={exc.__class__.__name__} message={exc}")
        raise SmokeTestError(f"MCP request failed during {stage}: {exc.__class__.__name__}: {exc}") from exc
