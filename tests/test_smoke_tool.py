from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_project_updater.config import load_project_config
from mcp_project_updater.constants import ExitCode
from mcp_project_updater.smoke_tool import ToolSmokeTestError, ToolSmokeRunResult, build_tool_smoke_config_payload, run_tool_smoke_test
from tests.config_helpers import strip_global_project_blocks, write_runtime_files


class _FakeClock:
    def __init__(self) -> None:
        self.current = 0.0

    def monotonic(self) -> float:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.current += seconds


def _write_config(tmp_path: Path) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    parser_path = tmp_path / "generate_config_report.py"
    parser_path.write_text("print('ok')\n", encoding="utf-8")
    tool_path = tmp_path / "mcp_smoke_test.py"
    tool_path.write_text("print('ok')\n", encoding="utf-8")
    write_runtime_files(tmp_path, parser_path=parser_path, tool_path=tool_path)
    payload = {
        "project": "orders",
        "repo": {"branch": "master", "remote": "origin", "pullMode": "ff-only"},
        "sources": {
            "mainConfigPath": "src/cf",
            "mainConfigRequired": False,
            "extensionPath": "src/cfe",
            "extensionRequired": False,
        },
        "parser": {
            "toolPath": str(parser_path),
            "encoding": "utf-8",
            "warningsAsErrors": False,
            "buildXmlOverrides": True,
            "allowedExitCodes": [0, 1],
        },
        "mcp": {
            "image": "comol/1c_code_metadata_mcp:light",
            "indexStorageRoot": str(tmp_path / "index-storage"),
            "containerPort": 8000,
            "production": {"containerName": "prod", "hostPort": 8100, "url": "http://localhost:8100/mcp"},
            "build": {"containerName": "build", "hostPort": 18100, "url": "http://localhost:18100/mcp"},
            "indexCode": True,
            "indexMetadata": True,
            "indexHelp": False,
            "resetDatabaseOnBuild": True,
            "resetCache": False,
            "useSse": False,
            "useGpu": False,
            "env": {},
            "secretEnv": {},
        },
        "paths": {
            "root": str(tmp_path),
        },
        "smokeTest": {
            "enabled": True,
            "profile": "dev",
            "reportValidation": {"enabled": True, "requiredReportPatterns": ['Имя: "'], "forbiddenReportPatterns": []},
            "infrastructure": {
                "enabled": True,
                "timeoutSeconds": 60,
                "checkIntervalSeconds": 5,
                "acceptableHttpStatusCodes": [200],
                "requireIndexStorageNotEmpty": True,
                "logTailLines": 100,
                "logErrorPatterns": ["Traceback"],
                "logReadyPatterns": ["Started"],
            },
            "toolSmokeTest": {
                "enabled": True,
                "toolPath": str(tool_path),
                "url": "http://localhost:18100/mcp",
                "timeoutSeconds": 300,
                "attemptTimeoutSeconds": 60,
                "retryIntervalSeconds": 10,
                "diagnostic": True,
                "metadataQueries": ["Конфигурации"],
                "codeQueries": ["Процедура"],
            },
        },
        "notifications": {
            "enabled": True,
            "onSuccess": False,
            "onFailure": True,
            "onRollback": True,
            "webhookUrlSecret": "MCP_UPDATE_WEBHOOK_URL",
        },
        "retention": {"keepPreviousIndexes": 1, "keepLogsDays": 30, "keepStagingBuilds": 2},
        "rollback": {"preserveFailedIndex": True},
    }
    strip_global_project_blocks(payload)
    config_path = tmp_path / "project.json"
    config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return config_path


def test_build_tool_smoke_config_payload_uses_defaults(tmp_path: Path) -> None:
    config = load_project_config(_write_config(tmp_path))

    payload = build_tool_smoke_config_payload(config, config.smoke_test.tool_smoke_test, url=config.mcp.build.url)

    assert payload["metadataToolName"] == "metadatasearch"
    assert payload["metadataQueryArgument"] == "query"
    assert payload["codeToolName"] == "codesearch"
    assert payload["codeQueryArgument"] == "query"
    assert payload["diagnostic"] is False
    assert payload["timeoutSeconds"] == 60
    assert payload["overallTimeoutSeconds"] == 300


def test_build_tool_smoke_config_payload_uses_attempt_timeout_when_overall_deadline_disabled(tmp_path: Path) -> None:
    config = load_project_config(_write_config(tmp_path))
    config.smoke_test.tool_smoke_test.timeout_seconds = 0

    payload = build_tool_smoke_config_payload(config, config.smoke_test.tool_smoke_test, url=config.mcp.build.url)

    assert payload["timeoutSeconds"] == 60
    assert payload["overallTimeoutSeconds"] == 60


def test_run_tool_smoke_test_invokes_cli(tmp_path: Path) -> None:
    config = load_project_config(_write_config(tmp_path))
    calls = []

    def runner(command, cwd):
        calls.append(command)
        return ToolSmokeRunResult(list(command), 0, '{"ok":true}', "")

    result = run_tool_smoke_test(
        config,
        config.smoke_test.tool_smoke_test,
        working_directory=config.repo.path,
        runner=runner,
        url=config.mcp.build.url,
    )

    assert result.returncode == 0
    assert calls[0][:2] == [sys.executable, str(config.smoke_test.tool_smoke_test.tool_path)]


def test_run_tool_smoke_test_raises_on_failure(tmp_path: Path) -> None:
    config = load_project_config(_write_config(tmp_path))

    with pytest.raises(ToolSmokeTestError) as exc:
        run_tool_smoke_test(
            config,
            config.smoke_test.tool_smoke_test,
            working_directory=config.repo.path,
            runner=lambda command, cwd: ToolSmokeRunResult(list(command), 13, "", "boom"),
            url=config.mcp.build.url,
        )

    assert exc.value.exit_code == ExitCode.BUILD_SMOKE_FAILED


def test_run_tool_smoke_test_reports_timeout_cleanly(tmp_path: Path, monkeypatch) -> None:
    config = load_project_config(_write_config(tmp_path))
    config.smoke_test.tool_smoke_test.timeout_seconds = 3
    config.smoke_test.tool_smoke_test.attempt_timeout_seconds = 1
    config.smoke_test.tool_smoke_test.retry_interval_seconds = 1
    clock = _FakeClock()

    def _fake_run(*args, **kwargs):
        clock.current += kwargs["timeout"]
        raise subprocess.TimeoutExpired(cmd=kwargs.get("args", args[0] if args else "python"), timeout=60)

    monkeypatch.setattr("mcp_project_updater.smoke_tool.subprocess.run", _fake_run)
    monkeypatch.setattr("mcp_project_updater.smoke_tool.time.monotonic", clock.monotonic)
    monkeypatch.setattr("mcp_project_updater.smoke_tool.time.sleep", clock.sleep)

    with pytest.raises(ToolSmokeTestError) as exc:
        run_tool_smoke_test(
            config,
            config.smoke_test.tool_smoke_test,
            working_directory=config.repo.path,
            url=config.mcp.build.url,
        )

    assert "MCP tool smoke-test timed out after 2 attempt(s) over 3 second(s)." in str(exc.value)


def test_run_tool_smoke_test_includes_stderr_diagnostics_on_timeout(tmp_path: Path, monkeypatch) -> None:
    config = load_project_config(_write_config(tmp_path))
    config.smoke_test.tool_smoke_test.timeout_seconds = 3
    config.smoke_test.tool_smoke_test.attempt_timeout_seconds = 1
    config.smoke_test.tool_smoke_test.retry_interval_seconds = 1
    clock = _FakeClock()

    def _fake_run(*args, **kwargs):
        clock.current += kwargs["timeout"]
        raise subprocess.TimeoutExpired(
            cmd=kwargs.get("args", args[0] if args else "python"),
            timeout=60,
            stderr=b"[diagnostic] list_tools:start",
        )

    monkeypatch.setattr("mcp_project_updater.smoke_tool.subprocess.run", _fake_run)
    monkeypatch.setattr("mcp_project_updater.smoke_tool.time.monotonic", clock.monotonic)
    monkeypatch.setattr("mcp_project_updater.smoke_tool.time.sleep", clock.sleep)

    with pytest.raises(ToolSmokeTestError) as exc:
        run_tool_smoke_test(
            config,
            config.smoke_test.tool_smoke_test,
            working_directory=config.repo.path,
            url=config.mcp.build.url,
        )

    assert "[diagnostic] list_tools:start" in str(exc.value)


def test_run_tool_smoke_test_retries_timeout_until_success(tmp_path: Path, monkeypatch) -> None:
    config = load_project_config(_write_config(tmp_path))
    attempts = {"count": 0}
    clock = _FakeClock()

    def _fake_run(*args, **kwargs):
        attempts["count"] += 1
        clock.current += kwargs["timeout"]
        if attempts["count"] < 3:
            raise subprocess.TimeoutExpired(
                cmd=kwargs.get("args", args[0] if args else "python"),
                timeout=60,
                stderr=b"[diagnostic] call_tool:start name=codesearch query='x'",
            )
        return subprocess.CompletedProcess(args[0], 0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr("mcp_project_updater.smoke_tool.subprocess.run", _fake_run)
    monkeypatch.setattr("mcp_project_updater.smoke_tool.time.monotonic", clock.monotonic)
    monkeypatch.setattr("mcp_project_updater.smoke_tool.time.sleep", clock.sleep)

    result = run_tool_smoke_test(
        config,
        config.smoke_test.tool_smoke_test,
        working_directory=config.repo.path,
        url=config.mcp.build.url,
    )

    assert result.returncode == 0
    assert attempts["count"] == 3


def test_run_tool_smoke_test_without_overall_timeout_retries_until_success(tmp_path: Path, monkeypatch) -> None:
    config = load_project_config(_write_config(tmp_path))
    config.smoke_test.tool_smoke_test.timeout_seconds = 0
    config.smoke_test.tool_smoke_test.attempt_timeout_seconds = 1
    config.smoke_test.tool_smoke_test.retry_interval_seconds = 1
    attempts = {"count": 0}
    clock = _FakeClock()

    def _fake_run(*args, **kwargs):
        attempts["count"] += 1
        clock.current += kwargs["timeout"]
        if attempts["count"] < 3:
            raise subprocess.TimeoutExpired(
                cmd=kwargs.get("args", args[0] if args else "python"),
                timeout=60,
                stderr=b"[diagnostic] list_tools:start",
            )
        return subprocess.CompletedProcess(args[0], 0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr("mcp_project_updater.smoke_tool.subprocess.run", _fake_run)
    monkeypatch.setattr("mcp_project_updater.smoke_tool.time.monotonic", clock.monotonic)
    monkeypatch.setattr("mcp_project_updater.smoke_tool.time.sleep", clock.sleep)

    result = run_tool_smoke_test(
        config,
        config.smoke_test.tool_smoke_test,
        working_directory=config.repo.path,
        url=config.mcp.build.url,
    )

    assert result.returncode == 0
    assert attempts["count"] == 3
