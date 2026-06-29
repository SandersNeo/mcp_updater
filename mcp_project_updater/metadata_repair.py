from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from mcp_smoke_test.client import SmokeTestError, _MCPStreamableHTTPSession, _result_json

from .constants import ExitCode
from .errors import UpdaterError


class MetadataIndexRepairError(UpdaterError):
    pass


@dataclass(slots=True)
class MetadataIndexRepairResult:
    metadata_count: int
    code_count: int


def run_metadata_index_repair(
    url: str,
    *,
    timeout_seconds: int,
    retry_interval_seconds: int,
    require_code_index: bool,
) -> MetadataIndexRepairResult:
    try:
        return asyncio.run(
            _run_metadata_index_repair(
                url,
                timeout_seconds=timeout_seconds,
                retry_interval_seconds=retry_interval_seconds,
                require_code_index=require_code_index,
            )
        )
    except SmokeTestError as exc:
        raise MetadataIndexRepairError(str(exc), ExitCode.BUILD_SMOKE_FAILED) from exc
    except UpdaterError:
        raise
    except Exception as exc:
        raise MetadataIndexRepairError(
            f"Metadata repair failed: {exc.__class__.__name__}: {exc}",
            ExitCode.BUILD_SMOKE_FAILED,
        ) from exc


async def _run_metadata_index_repair(
    url: str,
    *,
    timeout_seconds: int,
    retry_interval_seconds: int,
    require_code_index: bool,
) -> MetadataIndexRepairResult:
    deadline = time.monotonic() + max(1, timeout_seconds)
    async with _MCPStreamableHTTPSession(url, request_timeout_seconds=timeout_seconds) as session:
        tools_response = await session.list_tools()
        tool_names = {tool.name for tool in getattr(tools_response, "tools", [])}
        missing_tools = {"stats", "reindex"} - tool_names
        if missing_tools:
            raise MetadataIndexRepairError(
                f"Metadata repair requires MCP tools: {', '.join(sorted(missing_tools))}.",
                ExitCode.BUILD_SMOKE_FAILED,
            )

        await _wait_until_not_indexing(
            session,
            deadline=deadline,
            retry_interval_seconds=retry_interval_seconds,
            stage="before repair",
        )

        reindex_result = await session.call_tool("reindex", {"force": True})
        reindex_payload = _result_json(reindex_result)
        if reindex_payload and reindex_payload.get("status") not in {"success", "accepted"}:
            raise MetadataIndexRepairError(
                f"Metadata repair reindex(force=true) failed: {reindex_payload}",
                ExitCode.BUILD_SMOKE_FAILED,
            )

        return await _wait_for_repair_result(
            session,
            deadline=deadline,
            retry_interval_seconds=retry_interval_seconds,
            require_code_index=require_code_index,
        )


async def _wait_until_not_indexing(
    session,
    *,
    deadline: float,
    retry_interval_seconds: int,
    stage: str,
) -> None:
    while time.monotonic() < deadline:
        stats = await _load_stats(session)
        if not _indexing_is_running(stats):
            return
        await asyncio.sleep(max(1, retry_interval_seconds))
    raise MetadataIndexRepairError(f"Timed out waiting for indexing to finish {stage}.", ExitCode.BUILD_SMOKE_FAILED)


async def _wait_for_repair_result(
    session,
    *,
    deadline: float,
    retry_interval_seconds: int,
    require_code_index: bool,
) -> MetadataIndexRepairResult:
    last_counts: tuple[int, int] | None = None
    while time.monotonic() < deadline:
        stats = await _load_stats(session)
        metadata_count, code_count = _collection_counts(stats)
        last_counts = (metadata_count, code_count)
        if metadata_count > 0 and (not require_code_index or code_count > 0) and not _indexing_is_running(stats):
            return MetadataIndexRepairResult(metadata_count=metadata_count, code_count=code_count)
        await asyncio.sleep(max(1, retry_interval_seconds))

    if last_counts is None:
        details = "stats were not available"
    else:
        details = f"metadata={last_counts[0]} code={last_counts[1]}"
    raise MetadataIndexRepairError(
        f"Metadata repair did not produce required vector indexes before timeout: {details}.",
        ExitCode.BUILD_SMOKE_FAILED,
    )


async def _load_stats(session) -> dict[str, Any]:
    result = await session.call_tool("stats", {})
    payload = _result_json(result)
    if payload.get("status") != "success":
        raise MetadataIndexRepairError("Stats tool did not return success during metadata repair.", ExitCode.BUILD_SMOKE_FAILED)
    data = payload.get("data")
    if not isinstance(data, dict):
        raise MetadataIndexRepairError("Stats tool response does not contain data during metadata repair.", ExitCode.BUILD_SMOKE_FAILED)
    return data


def _collection_counts(stats_data: dict[str, Any]) -> tuple[int, int]:
    collections = stats_data.get("collections")
    if not isinstance(collections, dict):
        raise MetadataIndexRepairError("Stats tool response does not contain collections.", ExitCode.BUILD_SMOKE_FAILED)
    return int(collections.get("metadata") or 0), int(collections.get("code") or 0)


def _indexing_is_running(stats_data: dict[str, Any]) -> bool:
    indexing = stats_data.get("indexing")
    if not isinstance(indexing, dict):
        return False
    running = indexing.get("running")
    if isinstance(running, bool):
        return running
    status = indexing.get("status")
    if isinstance(status, str) and status.lower() in {"running", "in_progress", "started"}:
        return True
    current_phase = indexing.get("current_phase")
    if isinstance(current_phase, str) and current_phase:
        return True
    per_phase = indexing.get("per_phase")
    if isinstance(per_phase, dict):
        for phase in per_phase.values():
            if isinstance(phase, dict) and str(phase.get("status", "")).lower() == "running":
                return True
    return False
