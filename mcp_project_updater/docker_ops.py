from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from .constants import ExitCode
from .errors import UpdaterError


class DockerOperationError(UpdaterError):
    pass


@dataclass(slots=True)
class DockerCommandResult:
    returncode: int
    stdout: str
    stderr: str


DockerCommandRunner = Callable[[Sequence[str], Path], DockerCommandResult]


def default_docker_runner(command: Sequence[str], cwd: Path) -> DockerCommandResult:
    completed = subprocess.run(
        list(command),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return DockerCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def ensure_docker_available(runner: DockerCommandRunner = default_docker_runner) -> str:
    result = runner(["docker", "version", "--format", "{{.Server.Version}}"], Path.cwd())
    if result.returncode != 0:
        raise DockerOperationError(_render_error(result, "Docker is unavailable."), ExitCode.DOCKER_UNAVAILABLE)
    return result.stdout.strip()


def remove_container(
    container_name: str,
    *,
    runner: DockerCommandRunner = default_docker_runner,
    error_code: int = ExitCode.BUILD_CONTAINER_FAILED,
) -> None:
    result = runner(["docker", "rm", "-f", container_name], Path.cwd())
    if result.returncode == 0:
        return

    combined = f"{result.stdout}\n{result.stderr}".lower()
    if "no such container" in combined:
        return

    raise DockerOperationError(_render_error(result, f"Failed to remove container '{container_name}'."), error_code)


def run_docker_command(
    command: Sequence[str],
    *,
    runner: DockerCommandRunner = default_docker_runner,
    cwd: Path | None = None,
    error_code: int = ExitCode.BUILD_CONTAINER_FAILED,
    failure_message: str = "Docker command failed.",
) -> DockerCommandResult:
    result = runner(command, cwd or Path.cwd())
    if result.returncode != 0:
        raise DockerOperationError(_render_error(result, failure_message), error_code)
    return result


def inspect_container(container_name: str, runner: DockerCommandRunner = default_docker_runner) -> dict[str, Any] | None:
    result = runner(["docker", "inspect", container_name], Path.cwd())
    if result.returncode != 0:
        combined = f"{result.stdout}\n{result.stderr}".lower()
        if "no such object" in combined or "no such container" in combined:
            return None
        raise DockerOperationError(_render_error(result, f"Failed to inspect container '{container_name}'."), ExitCode.BUILD_SMOKE_FAILED)

    payload = json.loads(result.stdout)
    if not payload:
        return None
    return payload[0]


def read_container_logs(
    container_name: str,
    *,
    tail_lines: int | None = None,
    runner: DockerCommandRunner = default_docker_runner,
) -> str:
    command = ["docker", "logs"]
    if tail_lines is not None:
        command.extend(["--tail", str(tail_lines)])
    command.append(container_name)

    result = runner(command, Path.cwd())
    if result.returncode != 0:
        combined = f"{result.stdout}\n{result.stderr}".lower()
        if "no such container" in combined:
            return ""
        raise DockerOperationError(_render_error(result, f"Failed to read logs for container '{container_name}'."), ExitCode.BUILD_SMOKE_FAILED)

    return f"{result.stdout}{result.stderr}"


def write_container_logs(
    container_name: str,
    output_path: Path,
    *,
    runner: DockerCommandRunner = default_docker_runner,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    logs = read_container_logs(container_name, runner=runner)
    output_path.write_text(logs, encoding="utf-8")
    return output_path


def _render_error(result: DockerCommandResult, fallback: str) -> str:
    stderr = result.stderr.strip()
    stdout = result.stdout.strip()
    return stderr or stdout or fallback
