from __future__ import annotations

import json
import subprocess
import sys
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
) -> dict[str, object]:
    return {
        "url": url or tool_smoke_config.url,
        "timeoutSeconds": tool_smoke_config.timeout_seconds,
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
    payload = build_tool_smoke_config_payload(config, tool_smoke_config, url=url)
    config_path = write_tool_smoke_config(config.paths.state_root / "tool-smoke-config.json", payload)
    command = [sys.executable, str(tool_smoke_config.tool_path), "--config", str(config_path)]
    if runner is default_process_runner:
        result = _run_default_process_runner_with_timeout(
            command,
            working_directory,
            timeout_seconds=tool_smoke_config.timeout_seconds,
        )
    else:
        result = runner(command, working_directory)
    if result.returncode != 0:
        details = _format_process_failure(result) or "Tool smoke-test failed."
        raise ToolSmokeTestError(details, ExitCode.BUILD_SMOKE_FAILED)
    return result


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


def _coerce_subprocess_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
