from __future__ import annotations

import http.client
from pathlib import Path

import pytest

from mcp_project_updater.config import InfrastructureSmokeConfig
from mcp_project_updater.docker_ops import DockerCommandResult
from mcp_project_updater.smoke_infrastructure import (
    InfrastructureSmokeContext,
    InfrastructureSmokeError,
    run_infrastructure_smoke_test,
)


def _smoke_config() -> InfrastructureSmokeConfig:
    return InfrastructureSmokeConfig(
        enabled=True,
        timeout_seconds=2,
        check_interval_seconds=0,
        http_ready_url="http://localhost:18100/mcp",
        acceptable_http_status_codes=[200, 400, 404, 405],
        require_chroma_not_empty=True,
        log_tail_lines=50,
        log_error_patterns=["Traceback", "Exception"],
        log_ready_patterns=["Started"],
    )


def test_run_infrastructure_smoke_test_success(tmp_path: Path) -> None:
    chroma = tmp_path / "chroma"
    chroma.mkdir()
    (chroma / "file.bin").write_text("x", encoding="utf-8")
    commands = []

    def runner(command, cwd):
        commands.append(command)
        if command[:2] == ["docker", "inspect"]:
            return DockerCommandResult(0, '[{"State":{"Status":"running","Restarting":false}}]', "")
        return DockerCommandResult(0, "clean logs", "")

    result = run_infrastructure_smoke_test(
        _smoke_config(),
        InfrastructureSmokeContext(
            container_name="build",
            host_port=18100,
            url="http://localhost:18100/mcp",
            chroma_path=chroma,
        ),
        runner=runner,
        http_status_getter=lambda url: 404,
        port_checker=lambda host, port: True,
        sleep=lambda seconds: None,
    )

    assert result.http_status_code == 404


def test_run_infrastructure_smoke_test_detects_error_pattern(tmp_path: Path) -> None:
    chroma = tmp_path / "chroma"
    chroma.mkdir()
    (chroma / "file.bin").write_text("x", encoding="utf-8")

    def runner(command, cwd):
        if command[:2] == ["docker", "inspect"]:
            return DockerCommandResult(0, '[{"State":{"Status":"running","Restarting":false}}]', "")
        return DockerCommandResult(0, "Traceback happened", "")

    with pytest.raises(InfrastructureSmokeError):
        run_infrastructure_smoke_test(
            _smoke_config(),
            InfrastructureSmokeContext(
                container_name="build",
                host_port=18100,
                url="http://localhost:18100/mcp",
                chroma_path=chroma,
            ),
            runner=runner,
            http_status_getter=lambda url: 200,
            port_checker=lambda host, port: True,
            sleep=lambda seconds: None,
        )


def test_run_infrastructure_smoke_test_handles_remote_disconnect_as_retryable_failure(tmp_path: Path) -> None:
    chroma = tmp_path / "chroma"
    chroma.mkdir()
    (chroma / "file.bin").write_text("x", encoding="utf-8")

    def runner(command, cwd):
        if command[:2] == ["docker", "inspect"]:
            return DockerCommandResult(0, '[{"State":{"Status":"running","Restarting":false}}]', "")
        return DockerCommandResult(0, "clean logs", "")

    ticks = iter([0.0, 0.5, 1.0, 2.1])

    with pytest.raises(InfrastructureSmokeError) as exc:
        run_infrastructure_smoke_test(
            _smoke_config(),
            InfrastructureSmokeContext(
                container_name="build",
                host_port=18100,
                url="http://localhost:18100/mcp",
                chroma_path=chroma,
            ),
            runner=runner,
            http_status_getter=lambda url: (_ for _ in ()).throw(http.client.RemoteDisconnected("Remote end closed connection without response")),
            port_checker=lambda host, port: True,
            monotonic=lambda: next(ticks),
            sleep=lambda seconds: None,
        )

    assert "HTTP readiness check failed" in str(exc.value)
