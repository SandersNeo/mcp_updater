from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_project_updater.config import load_project_config
from mcp_project_updater.constants import ExitCode
from mcp_project_updater.docker_ops import DockerCommandResult
from mcp_project_updater.mcp_container import (
    MissingSecretEnvError,
    build_build_container_command,
    build_production_container_command,
    format_container_command_for_log,
    prepare_index_storage_build,
    start_build_container,
    start_production_container,
)
from mcp_project_updater.staging import prepare_build_staging
from tests.config_helpers import strip_global_project_blocks, write_runtime_files


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
                "httpReadyUrl": "http://localhost:18100/mcp",
                "acceptableHttpStatusCodes": [200],
                "requireIndexStorageNotEmpty": True,
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
            "webhookUrlSecret": "MCP_UPDATE_WEBHOOK_URL",
        },
        "retention": {"keepPreviousIndexes": 1, "keepLogsDays": 30, "keepStagingBuilds": 2},
        "rollback": {"preserveFailedIndex": True},
    }
    strip_global_project_blocks(payload)
    config_path = tmp_path / "project.json"
    config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return config_path


def test_prepare_index_storage_build_resets_directory(tmp_path: Path) -> None:
    build_dir = tmp_path / "index-storage" / "build"
    build_dir.mkdir(parents=True)
    (build_dir / "old.txt").write_text("x", encoding="utf-8")

    prepared = prepare_index_storage_build(tmp_path / "index-storage")

    assert prepared.exists()
    assert not any(prepared.iterdir())


def test_prepare_index_storage_build_can_seed_from_current(tmp_path: Path) -> None:
    current_dir = tmp_path / "index-storage" / "current"
    current_dir.mkdir(parents=True)
    (current_dir / "db.bin").write_text("current", encoding="utf-8")

    prepared = prepare_index_storage_build(tmp_path / "index-storage", seed_source=current_dir)

    assert (prepared / "db.bin").read_text(encoding="utf-8") == "current"


def test_build_build_container_command_requires_secret_env(tmp_path: Path, monkeypatch) -> None:
    config = load_project_config(_write_config(tmp_path))
    config.mcp.secrets.clear()
    build_paths = prepare_build_staging(config.paths.staging_root, config.project)

    with pytest.raises(MissingSecretEnvError) as exc:
        build_build_container_command(
            config.mcp,
            build_paths,
            config.paths,
            reset_database=True,
            index_metadata=True,
            index_code=True,
            index_help=False,
        )

    assert exc.value.exit_code == ExitCode.MISSING_REQUIRED_SECRET


def test_start_build_container_runs_remove_and_run(tmp_path: Path, monkeypatch) -> None:
    config = load_project_config(_write_config(tmp_path))
    build_paths = prepare_build_staging(config.paths.staging_root, config.project)
    calls = []

    def runner(command, cwd):
        calls.append(command)
        if command[:3] == ["docker", "rm", "-f"]:
            return DockerCommandResult(1, "", "No such container")
        return DockerCommandResult(0, "container-id\n", "")

    result = start_build_container(config.mcp, build_paths, config.paths, runner=runner)

    assert result.container_id == "container-id"
    assert calls[0][:3] == ["docker", "rm", "-f"]
    assert calls[1][:4] == ["docker", "run", "-d", "--init"]
    assert any(part == "RESET_DATABASE=true" for part in calls[1])
    assert any(part == "INDEX_METADATA=true" for part in calls[1])
    assert any(part == "INDEX_CODE=true" for part in calls[1])
    assert "REINDEX_INTERVAL_SEC=0" not in calls[1]
    assert f"{config.paths.index_storage_root / 'build'}:/app/chroma_db" in calls[1]
    assert "OPENAI_API_BASE=https://openrouter.ai/api/v1" not in calls[1]
    assert "OPENAI_MODEL=qwen/qwen3-embedding-8b" not in calls[1]
    assert not any(part.startswith("OPENAI_API_KEY=") for part in calls[1])


def test_start_build_container_can_disable_metadata_and_seed_from_current(tmp_path: Path, monkeypatch) -> None:
    config = load_project_config(_write_config(tmp_path))
    build_paths = prepare_build_staging(config.paths.staging_root, config.project)
    current_index_storage = config.paths.index_storage_root / "current"
    current_index_storage.mkdir(parents=True)
    (current_index_storage / "db.bin").write_text("seed", encoding="utf-8")
    calls = []

    def runner(command, cwd):
        calls.append(command)
        if command[:3] == ["docker", "rm", "-f"]:
            return DockerCommandResult(1, "", "No such container")
        return DockerCommandResult(0, "container-id\n", "")

    start_build_container(
        config.mcp,
        build_paths,
        config.paths,
        runner=runner,
        reset_database=False,
        seed_index_storage_from=current_index_storage,
        index_metadata=False,
        index_code=False,
        index_help=False,
    )

    assert (config.paths.index_storage_root / "build" / "db.bin").read_text(encoding="utf-8") == "seed"
    assert calls[1][:4] == ["docker", "run", "-d", "--init"]
    assert any(part == "RESET_DATABASE=false" for part in calls[1])
    assert any(part == "INDEX_METADATA=false" for part in calls[1])
    assert any(part == "INDEX_CODE=false" for part in calls[1])
    assert any(part == "INDEX_HELP=false" for part in calls[1])


def test_build_production_container_command_uses_restart_policy(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["mcp"]["indexMetadata"] = True
    payload["mcp"]["indexCode"] = True
    payload["mcp"]["indexHelp"] = True
    config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    config = load_project_config(config_path)

    command = build_production_container_command(config.mcp, config.paths)

    assert command[:4] == ["docker", "run", "-d", "--init"]
    assert "--restart" in command
    restart_index = command.index("--restart")
    assert command[restart_index + 1] == "unless-stopped"
    assert "RESET_DATABASE=false" in command
    assert "INDEX_METADATA=false" in command
    assert "INDEX_CODE=false" in command
    assert "INDEX_HELP=false" in command
    assert "REINDEX_INTERVAL_SEC=0" in command
    assert "INDEX_METADATA=true" not in command
    assert "INDEX_CODE=true" not in command
    assert "INDEX_HELP=true" not in command
    assert f"{config.paths.index_storage_root / 'current'}:/app/chroma_db" in command


def test_start_production_container_logs_disabled_indexing_flags(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    config_path = _write_config(tmp_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["mcp"]["indexMetadata"] = True
    payload["mcp"]["indexCode"] = True
    payload["mcp"]["indexHelp"] = True
    config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    config = load_project_config(config_path)

    def runner(command, cwd):
        return DockerCommandResult(0, "container-id\n", "")

    with caplog.at_level("INFO"):
        start_production_container(config.mcp, config.paths, runner=runner)

    assert "index_metadata=False" in caplog.text
    assert "index_code=False" in caplog.text
    assert "index_help=False" in caplog.text
    assert "reindex_interval_sec=0" in caplog.text


def test_build_container_command_uses_configured_index_container_path(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["mcp"]["indexContainerPath"] = "/app/zvec_db"
    config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    config = load_project_config(config_path)
    build_paths = prepare_build_staging(config.paths.staging_root, config.project)

    build_command = build_build_container_command(
        config.mcp,
        build_paths,
        config.paths,
        reset_database=True,
        index_metadata=True,
        index_code=True,
        index_help=False,
    )
    production_command = build_production_container_command(config.mcp, config.paths)

    assert f"{config.paths.index_storage_root / 'build'}:/app/zvec_db" in build_command
    assert f"{config.paths.index_storage_root / 'current'}:/app/zvec_db" in production_command
    assert f"{config.paths.index_storage_root / 'build'}:/app/chroma_db" not in build_command
    assert f"{config.paths.index_storage_root / 'current'}:/app/chroma_db" not in production_command


def test_project_level_openai_api_key_is_passed_to_container(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["mcp"]["secretEnv"] = {"OPENAI_API_KEY": "OPENROUTER_API_KEY"}
    config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    project_secrets_path = tmp_path / "secrets.local.json"
    project_secrets = json.loads(project_secrets_path.read_text(encoding="utf-8"))
    project_secrets["OPENROUTER_API_KEY"] = "project-openrouter-key"
    project_secrets_path.write_text(json.dumps(project_secrets), encoding="utf-8")
    config = load_project_config(config_path)
    build_paths = prepare_build_staging(config.paths.staging_root, config.project)

    command = build_build_container_command(
        config.mcp,
        build_paths,
        config.paths,
        reset_database=True,
        index_metadata=True,
        index_code=True,
        index_help=False,
    )

    assert "OPENAI_API_KEY=project-openrouter-key" in command


def test_project_level_openai_env_is_passed_to_container(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["mcp"]["env"] = {
        "OPENAI_API_BASE": "https://openrouter.ai/api/v1",
        "OPENAI_MODEL": "qwen/qwen3-embedding-8b",
    }
    config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    config = load_project_config(config_path)
    build_paths = prepare_build_staging(config.paths.staging_root, config.project)

    command = build_build_container_command(
        config.mcp,
        build_paths,
        config.paths,
        reset_database=True,
        index_metadata=True,
        index_code=True,
        index_help=False,
    )

    assert "OPENAI_API_BASE=https://openrouter.ai/api/v1" in command
    assert "OPENAI_MODEL=qwen/qwen3-embedding-8b" in command


def test_format_container_command_for_log_redacts_sensitive_environment_values() -> None:
    command = [
        "docker",
        "run",
        "-e",
        "INDEX_HELP=false",
        "-e",
        "OPENAI_API_KEY=secret-value",
        "-e",
        "LICENSE_KEY=license-value",
        "-e",
        "NORMAL=value",
        "image:latest",
    ]

    formatted = format_container_command_for_log(command)

    assert "INDEX_HELP=false" in formatted
    assert "OPENAI_API_KEY=<redacted>" in formatted
    assert "LICENSE_KEY=<redacted>" in formatted
    assert "NORMAL=value" in formatted
    assert "secret-value" not in formatted
    assert "license-value" not in formatted
