from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from mcp_project_updater.constants import ExitCode
from mcp_project_updater.docker_ops import (
    DockerCommandResult,
    DockerOperationError,
    default_docker_runner,
    ensure_docker_available,
    inspect_container,
    read_container_logs,
    remove_container,
)


def test_ensure_docker_available_returns_version() -> None:
    version = ensure_docker_available(lambda command, cwd: DockerCommandResult(0, "26.1.0\n", ""))

    assert version == "26.1.0"


def test_ensure_docker_available_raises() -> None:
    with pytest.raises(DockerOperationError) as exc:
        ensure_docker_available(lambda command, cwd: DockerCommandResult(1, "", "docker down"))

    assert exc.value.exit_code == ExitCode.DOCKER_UNAVAILABLE


def test_remove_container_ignores_missing_container() -> None:
    remove_container("missing", runner=lambda command, cwd: DockerCommandResult(1, "", "No such container: missing"))


def test_inspect_container_returns_none_for_missing() -> None:
    result = inspect_container("missing", runner=lambda command, cwd: DockerCommandResult(1, "", "Error: No such object"))

    assert result is None


def test_read_container_logs_returns_combined_output() -> None:
    logs = read_container_logs(
        "build",
        tail_lines=10,
        runner=lambda command, cwd: DockerCommandResult(0, "hello", "world"),
    )

    assert logs == "helloworld"


def test_default_docker_runner_decodes_non_cp1251_bytes(monkeypatch, tmp_path: Path) -> None:
    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0] if args else kwargs.get("args"),
            returncode=0,
            stdout=b"hello\x98world",
            stderr=b"",
        )

    monkeypatch.setattr("mcp_project_updater.docker_ops.subprocess.run", _fake_run)

    result = default_docker_runner(["docker", "version"], tmp_path)

    assert result.stdout == "hello\ufffdworld"
