from __future__ import annotations

import json
import math
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .config import ProjectConfig, ToolSmokeConfig
from .constants import ExitCode
from .errors import UpdaterError


class ToolSmokeTestError(UpdaterError):
    pass


@dataclass(slots=True)
class ToolSmokeRunResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


ProcessRunner = Callable[[Sequence[str], Path], ToolSmokeRunResult]


def default_process_runner(command: Sequence[str], cwd: Path) -> ToolSmokeRunResult:
    completed = subprocess.run(
        list(command),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return ToolSmokeRunResult(
        command=list(command),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def build_tool_smoke_config_payload(
    config: ProjectConfig,
    tool_smoke_config: ToolSmokeConfig,
    *,
    url: str | None = None,
    attempt_timeout_seconds: int | None = None,
) -> dict[str, object]:
    return {
        "url": url or tool_smoke_config.url,
        "timeoutSeconds": attempt_timeout_seconds or tool_smoke_config.attempt_timeout_seconds,
        "overallTimeoutSeconds": tool_smoke_config.timeout_seconds,
        "indexCode": config.mcp.index_code,
        "diagnostic": tool_smoke_config.diagnostic,
        "metadataToolName": tool_smoke_config.metadata_tool_name,
        "metadataQueryArgument": tool_smoke_config.metadata_query_argument,
        "metadataQueries": tool_smoke_config.metadata_queries,
        "codeToolName": tool_smoke_config.code_tool_name,
        "codeQueryArgument": tool_smoke_config.code_query_argument,
        "codeQueries": tool_smoke_config.code_queries,
    }


def write_tool_smoke_config(output_path: Path, payload: dict[str, object]) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def run_tool_smoke_test(
    config: ProjectConfig,
    tool_smoke_config: ToolSmokeConfig,
    *,
    working_directory: Path,
    runner: ProcessRunner = default_process_runner,
    url: str | None = None,
) -> ToolSmokeRunResult:
    deadline = time.monotonic() + tool_smoke_config.timeout_seconds
    attempts = 0
    last_result: ToolSmokeRunResult | None = None

    while True:
        attempts += 1
        remaining_seconds = max(1, math.ceil(deadline - time.monotonic()))
        attempt_timeout_seconds = min(tool_smoke_config.attempt_timeout_seconds, remaining_seconds)
        payload = build_tool_smoke_config_payload(
            config,
            tool_smoke_config,
            url=url,
            attempt_timeout_seconds=attempt_timeout_seconds,
        )
        config_path = write_tool_smoke_config(config.paths.state_root / "tool-smoke-config.json", payload)
        command = [sys.executable, str(tool_smoke_config.tool_path), "--config", str(config_path)]
        if runner is default_process_runner:
            result = _run_default_process_runner_with_timeout(
                command,
                working_directory,
                timeout_seconds=attempt_timeout_seconds,
            )
        else:
            result = runner(command, working_directory)

        if result.returncode == 0:
            return result

        if not _is_retryable_timeout_result(result):
            details = _format_process_failure(result) or "Tool smoke-test failed."
            raise ToolSmokeTestError(details, ExitCode.BUILD_SMOKE_FAILED)

        last_result = result
        remaining_after_attempt = deadline - time.monotonic()
        if remaining_after_attempt <= 0:
            break
        sleep_seconds = min(tool_smoke_config.retry_interval_seconds, math.floor(remaining_after_attempt))
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    details = _format_process_failure(last_result) if last_result is not None else ""
    summary = (
        f"MCP tool smoke-test timed out after {attempts} attempt(s) "
        f"over {tool_smoke_config.timeout_seconds} second(s)."
    )
    combined = "\n".join(part for part in (summary, details) if part)
    raise ToolSmokeTestError(combined, ExitCode.BUILD_SMOKE_FAILED)


def _run_default_process_runner_with_timeout(
    command: Sequence[str],
    cwd: Path,
    *,
    timeout_seconds: int,
) -> ToolSmokeRunResult:
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return ToolSmokeRunResult(
            command=list(command),
            returncode=13,
            stdout="MCP tool smoke-test timed out.",
            stderr=_coerce_subprocess_output(exc.stderr) or _coerce_subprocess_output(exc.stdout),
        )

    return ToolSmokeRunResult(
        command=list(command),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _format_process_failure(result: ToolSmokeRunResult) -> str:
    parts = [part.strip() for part in (result.stdout, result.stderr) if part and part.strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if parts[0] == parts[1]:
        return parts[0]
    return "\n".join(parts)


def _is_retryable_timeout_result(result: ToolSmokeRunResult) -> bool:
    if result.returncode != 13:
        return False
    text = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return "MCP tool smoke-test timed out." in text


def _coerce_subprocess_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
