from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_project_updater.config import load_project_config
from mcp_project_updater.constants import ExitCode
from mcp_project_updater.docker_ops import DockerCommandResult
from mcp_project_updater.mcp_container import MissingSecretEnvError, build_build_container_command, prepare_chroma_build, start_build_container
from mcp_project_updater.staging import prepare_build_staging


def _write_config(tmp_path: Path) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    parser_path = tmp_path / "generate_config_report.py"
    parser_path.write_text("print('ok')\n", encoding="utf-8")
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
            "secretEnv": {"LICENSE_KEY": "TEST_LICENSE_ENV"},
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
                "toolPath": str(tmp_path / "mcp_smoke_test.py"),
                "url": "http://localhost:18100/mcp",
                "timeoutSeconds": 60,
                "metadataToolName": "metadatasearch",
                "metadataQueryArgument": "query",
                "metadataQueries": ["Конфигурации"],
                "codeToolName": "codesearch",
                "codeQueryArgument": "query",
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
    tool_path = tmp_path / "mcp_smoke_test.py"
    tool_path.write_text("print('ok')\n", encoding="utf-8")
    config_path = tmp_path / "project.json"
    config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return config_path


def test_prepare_chroma_build_resets_directory(tmp_path: Path) -> None:
    build_dir = tmp_path / "chroma" / "build"
    build_dir.mkdir(parents=True)
    (build_dir / "old.txt").write_text("x", encoding="utf-8")

    prepared = prepare_chroma_build(tmp_path / "chroma")

    assert prepared.exists()
    assert not any(prepared.iterdir())


def test_build_build_container_command_requires_secret_env(tmp_path: Path, monkeypatch) -> None:
    config = load_project_config(_write_config(tmp_path))
    build_paths = prepare_build_staging(config.paths.staging_root, config.project)

    monkeypatch.delenv("TEST_LICENSE_ENV", raising=False)

    with pytest.raises(MissingSecretEnvError) as exc:
        build_build_container_command(config.mcp, build_paths, config.paths)

    assert exc.value.exit_code == ExitCode.MISSING_REQUIRED_SECRET


def test_start_build_container_runs_remove_and_run(tmp_path: Path, monkeypatch) -> None:
    config = load_project_config(_write_config(tmp_path))
    build_paths = prepare_build_staging(config.paths.staging_root, config.project)
    monkeypatch.setenv("TEST_LICENSE_ENV", "secret")
    calls = []

    def runner(command, cwd):
        calls.append(command)
        if command[:3] == ["docker", "rm", "-f"]:
            return DockerCommandResult(1, "", "No such container")
        return DockerCommandResult(0, "container-id\n", "")

    result = start_build_container(config.mcp, build_paths, config.paths, runner=runner)

    assert result.container_id == "container-id"
    assert calls[0][:3] == ["docker", "rm", "-f"]
    assert calls[1][:3] == ["docker", "run", "-d"]
