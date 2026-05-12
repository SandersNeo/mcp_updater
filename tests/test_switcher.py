from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_project_updater.config import load_project_config
from mcp_project_updater.docker_ops import DockerCommandResult
from mcp_project_updater.state import StateStore
from mcp_project_updater.switcher import ProductionSmokeTestFailed, perform_switch


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


def _missing_container_runner(command, cwd):
    if command[:3] == ["docker", "rm", "-f"]:
        return DockerCommandResult(1, "", "No such container")
    return DockerCommandResult(0, "", "")


def test_perform_switch_first_time_updates_current(tmp_path: Path, monkeypatch) -> None:
    config = load_project_config(_write_config(tmp_path))
    state_store = StateStore(config.paths.state_root)
    (config.paths.staging_root / "build" / "metadata").mkdir(parents=True)
    (config.paths.staging_root / "build" / "metadata" / "Report.txt").write_text("x", encoding="utf-8")
    (config.paths.chroma_root / "build").mkdir(parents=True)
    (config.paths.chroma_root / "build" / "db.bin").write_text("x", encoding="utf-8")

    monkeypatch.setattr("mcp_project_updater.switcher.start_production_container", lambda *args, **kwargs: None)
    monkeypatch.setattr("mcp_project_updater.switcher.write_container_logs", lambda *args, **kwargs: None)

    perform_switch(
        config,
        state_store,
        "abc123",
        tmp_path / "production.log",
        docker_runner=_missing_container_runner,
        production_smoke_runner=lambda current_config: object(),
    )

    assert (config.paths.staging_root / "current").exists()
    assert (config.paths.chroma_root / "current").exists()
    assert state_store.read_current_commit() == "abc123"
    assert state_store.read_last_indexed_commit() == "abc123"
    assert state_store.read_previous_commit() is None


def test_perform_switch_moves_old_current_to_previous(tmp_path: Path, monkeypatch) -> None:
    config = load_project_config(_write_config(tmp_path))
    state_store = StateStore(config.paths.state_root)
    state_store.write_current_commit("old-commit")

    (config.paths.staging_root / "current").mkdir(parents=True)
    (config.paths.staging_root / "current" / "old.txt").write_text("old", encoding="utf-8")
    (config.paths.staging_root / "build").mkdir(parents=True)
    (config.paths.staging_root / "build" / "new.txt").write_text("new", encoding="utf-8")

    (config.paths.chroma_root / "current").mkdir(parents=True)
    (config.paths.chroma_root / "current" / "old.bin").write_text("old", encoding="utf-8")
    (config.paths.chroma_root / "build").mkdir(parents=True)
    (config.paths.chroma_root / "build" / "new.bin").write_text("new", encoding="utf-8")

    monkeypatch.setattr("mcp_project_updater.switcher.start_production_container", lambda *args, **kwargs: None)
    monkeypatch.setattr("mcp_project_updater.switcher.write_container_logs", lambda *args, **kwargs: None)

    perform_switch(
        config,
        state_store,
        "new-commit",
        tmp_path / "production.log",
        docker_runner=_missing_container_runner,
        production_smoke_runner=lambda current_config: object(),
    )

    assert (config.paths.staging_root / "previous" / "old.txt").read_text(encoding="utf-8") == "old"
    assert (config.paths.staging_root / "current" / "new.txt").read_text(encoding="utf-8") == "new"
    assert state_store.read_previous_commit() == "old-commit"
    assert state_store.read_current_commit() == "new-commit"


def test_perform_switch_failed_production_smoke_triggers_rollback(tmp_path: Path, monkeypatch) -> None:
    config = load_project_config(_write_config(tmp_path))
    state_store = StateStore(config.paths.state_root)
    (config.paths.staging_root / "build").mkdir(parents=True)
    (config.paths.chroma_root / "build").mkdir(parents=True)
    called = {"rollback": False}

    monkeypatch.setattr("mcp_project_updater.switcher.start_production_container", lambda *args, **kwargs: None)
    monkeypatch.setattr("mcp_project_updater.switcher.write_container_logs", lambda *args, **kwargs: None)

    with pytest.raises(ProductionSmokeTestFailed):
        perform_switch(
            config,
            state_store,
            "abc123",
            tmp_path / "production.log",
            docker_runner=_missing_container_runner,
            production_smoke_runner=lambda current_config: (_ for _ in ()).throw(Exception("boom")),
            rollback_runner=lambda *args, **kwargs: called.__setitem__("rollback", True),
        )

    assert called["rollback"] is True
