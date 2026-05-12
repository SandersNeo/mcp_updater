from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_project_updater.config import load_project_config
from mcp_project_updater.constants import ExitCode
from mcp_project_updater.smoke_tool import ToolSmokeTestError, ToolSmokeRunResult, build_tool_smoke_config_payload, run_tool_smoke_test


def _write_config(tmp_path: Path) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    parser_path = tmp_path / "generate_config_report.py"
    parser_path.write_text("print('ok')\n", encoding="utf-8")
    tool_path = tmp_path / "mcp_smoke_test.py"
    tool_path.write_text("print('ok')\n", encoding="utf-8")
    payload = {
        "project": "orders",
        "repo": {"path": str(repo_path), "branch": "master", "remote": "origin", "pullMode": "ff-only"},
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
            "image": "example/image:latest",
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
            "env": {"METADATA_PATH": "/app/metadata", "CODE_PATH": "/app/code"},
            "secretEnv": {"LICENSE_KEY": "ENV_LICENSE"},
        },
        "paths": {
            "stagingRoot": str(tmp_path / "staging"),
            "chromaRoot": str(tmp_path / "chroma"),
            "stateRoot": str(tmp_path / "state"),
            "logsRoot": str(tmp_path / "logs"),
        },
        "smokeTest": {
            "enabled": True,
            "profile": "dev",
            "reportValidation": {"enabled": True, "requiredReportPatterns": ['Имя: "'], "forbiddenReportPatterns": []},
            "infrastructure": {
                "enabled": True,
                "timeoutSeconds": 60,
                "checkIntervalSeconds": 5,
                "httpReadyUrl": "http://localhost:18100/mcp",
                "acceptableHttpStatusCodes": [200],
                "requireChromaNotEmpty": True,
                "logTailLines": 100,
                "logErrorPatterns": ["Traceback"],
                "logReadyPatterns": ["Started"],
            },
            "toolSmokeTest": {
                "enabled": True,
                "toolPath": str(tool_path),
                "url": "http://localhost:18100/mcp",
                "timeoutSeconds": 60,
                "metadataQueries": ["Конфигурации"],
                "codeQueries": ["Процедура"],
            },
        },
        "notifications": {
            "enabled": True,
            "onSuccess": False,
            "onFailure": True,
            "onRollback": True,
            "webhookUrlEnv": "MCP_UPDATE_WEBHOOK_URL",
        },
        "retention": {"keepPreviousIndexes": 1, "keepLogsDays": 30, "keepStagingBuilds": 2},
        "rollback": {"preserveFailedIndex": True},
    }
    config_path = tmp_path / "project.json"
    config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return config_path


def test_build_tool_smoke_config_payload_uses_defaults(tmp_path: Path) -> None:
    config = load_project_config(_write_config(tmp_path))

    payload = build_tool_smoke_config_payload(config, config.smoke_test.tool_smoke_test)

    assert payload["metadataToolName"] == "metadatasearch"
    assert payload["metadataQueryArgument"] == "query"
    assert payload["codeToolName"] == "codesearch"
    assert payload["codeQueryArgument"] == "query"


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
    assert calls[0][:2] == ["python", str(config.smoke_test.tool_smoke_test.tool_path)]


def test_run_tool_smoke_test_raises_on_failure(tmp_path: Path) -> None:
    config = load_project_config(_write_config(tmp_path))

    with pytest.raises(ToolSmokeTestError) as exc:
        run_tool_smoke_test(
            config,
            config.smoke_test.tool_smoke_test,
            working_directory=config.repo.path,
            runner=lambda command, cwd: ToolSmokeRunResult(list(command), 13, "", "boom"),
        )

    assert exc.value.exit_code == ExitCode.BUILD_SMOKE_FAILED
