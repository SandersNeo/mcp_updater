from __future__ import annotations

import json
from pathlib import Path

from mcp_project_updater.cli import CliOptions, run_rollback, run_update
from mcp_project_updater.config import load_project_config
from mcp_project_updater.constants import ExitCode
from mcp_project_updater.docker_ops import DockerCommandResult
from mcp_project_updater.git_ops import RepoValidationResult
from mcp_project_updater.state import StateStore


class FakeDockerRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.container_counter = 0

    def __call__(self, command: list[str], cwd: Path) -> DockerCommandResult:
        self.commands.append(list(command))
        if command[:2] == ["docker", "rm"]:
            return DockerCommandResult(returncode=0, stdout="", stderr="")
        if command[:3] == ["docker", "logs", "mcp-orders"]:
            return DockerCommandResult(returncode=0, stdout="production ready\n", stderr="")
        if command[:3] == ["docker", "logs", "mcp-orders-build"]:
            return DockerCommandResult(returncode=0, stdout="build ready\n", stderr="")
        if command[:2] == ["docker", "logs"]:
            return DockerCommandResult(returncode=0, stdout="container ready\n", stderr="")
        if command[:2] == ["docker", "run"]:
            self.container_counter += 1
            return DockerCommandResult(returncode=0, stdout=f"cid-{self.container_counter}\n", stderr="")
        raise AssertionError(f"Unexpected docker command: {command}")


def test_run_update_integration_updates_state_and_current_artifacts(tmp_path: Path, monkeypatch) -> None:
    config_path = _write_config(tmp_path)
    config = load_project_config(config_path)
    state_store = StateStore(config.paths.state_root)
    log_path = config.paths.logs_root / "integration-update.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")

    (config.repo.path / "src" / "cf" / "module.bsl").write_text("Procedure Test() EndProcedure\n", encoding="utf-8")
    monkeypatch.setenv("ONERPA_LICENSE_KEY", "secret-value")

    fake_runner = FakeDockerRunner()
    monkeypatch.setattr("mcp_project_updater.cli.ensure_repo_available", lambda repo, no_git_pull: None)
    monkeypatch.setattr("mcp_project_updater.cli.validate_repo", _fake_repo_validation)
    monkeypatch.setattr("mcp_project_updater.cli.determine_target_commit", lambda *args, **kwargs: "commit-001")
    monkeypatch.setattr("mcp_project_updater.cli.run_parser", _fake_run_parser)
    monkeypatch.setattr("mcp_project_updater.cli.ensure_docker_available", lambda: "26.1.0")
    monkeypatch.setattr("mcp_project_updater.cli.run_infrastructure_smoke_test", _fake_infrastructure_smoke)
    monkeypatch.setattr("mcp_project_updater.cli.run_tool_smoke_test", _fake_tool_smoke)
    monkeypatch.setattr("mcp_project_updater.cli.default_docker_runner", fake_runner)
    monkeypatch.setattr(
        "mcp_project_updater.switcher.run_production_smoke_test",
        lambda current_config, *, docker_runner: object(),
    )

    result = run_update(
        config,
        CliOptions(
            config_path=config_path,
            force=False,
            no_git_pull=False,
            rollback=False,
            verbose=False,
            dry_run=False,
        ),
        log_path=log_path,
    )

    assert result == ExitCode.SUCCESS
    assert state_store.read_current_commit() == "commit-001"
    assert state_store.read_last_indexed_commit() == "commit-001"
    assert (config.paths.staging_root / "current" / "code" / "cf" / "module.bsl").exists()
    assert (config.paths.chroma_root / "current").is_dir()
    assert (config.paths.logs_root / "integration-mcp-build.log").exists()
    assert (config.paths.logs_root / "integration-mcp-production.log").exists()


def test_run_rollback_integration_swaps_current_and_previous(tmp_path: Path, monkeypatch) -> None:
    config_path = _write_config(tmp_path)
    config = load_project_config(config_path)
    state_store = StateStore(config.paths.state_root)
    log_path = config.paths.logs_root / "integration-update.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")

    monkeypatch.setenv("ONERPA_LICENSE_KEY", "secret-value")
    monkeypatch.setattr("mcp_project_updater.cli.default_docker_runner", FakeDockerRunner())
    monkeypatch.setattr(
        "mcp_project_updater.cli.run_production_smoke_test",
        lambda current_config, *, docker_runner: object(),
    )
    monkeypatch.setattr("mcp_project_updater.cli.send_notification", lambda *args, **kwargs: None)

    _create_artifact_tree(config.paths.staging_root / "current", marker="current-version")
    _create_artifact_tree(config.paths.staging_root / "previous", marker="previous-version")
    _create_artifact_tree(config.paths.chroma_root / "current", marker="current-chroma")
    _create_artifact_tree(config.paths.chroma_root / "previous", marker="previous-chroma")
    state_store.write_current_commit("commit-current")
    state_store.write_previous_commit("commit-previous")

    result = run_rollback(
        config,
        state_store,
        log_path=log_path,
        last_indexed_commit_at_start="commit-current",
    )

    assert result == ExitCode.SUCCESS
    assert state_store.read_current_commit() == "commit-previous"
    assert state_store.read_previous_commit() == "commit-current"
    assert (config.paths.staging_root / "current" / "marker.txt").read_text(encoding="utf-8") == "previous-version"
    assert (config.paths.staging_root / "previous" / "marker.txt").read_text(encoding="utf-8") == "current-version"
    assert (config.paths.logs_root / "integration-mcp-production.log").exists()


def test_run_rollback_returns_warning_when_notification_fails(tmp_path: Path, monkeypatch) -> None:
    config_path = _write_config(tmp_path)
    config = load_project_config(config_path)
    state_store = StateStore(config.paths.state_root)
    log_path = config.paths.logs_root / "integration-update.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")

    monkeypatch.setenv("ONERPA_LICENSE_KEY", "secret-value")
    monkeypatch.setattr("mcp_project_updater.cli.default_docker_runner", FakeDockerRunner())
    monkeypatch.setattr(
        "mcp_project_updater.cli.run_production_smoke_test",
        lambda current_config, *, docker_runner: object(),
    )
    monkeypatch.setattr(
        "mcp_project_updater.cli.send_notification",
        lambda *args, **kwargs: (_ for _ in ()).throw(Exception("boom")),
    )

    _create_artifact_tree(config.paths.staging_root / "current", marker="current-version")
    _create_artifact_tree(config.paths.staging_root / "previous", marker="previous-version")
    _create_artifact_tree(config.paths.chroma_root / "current", marker="current-chroma")
    _create_artifact_tree(config.paths.chroma_root / "previous", marker="previous-chroma")
    state_store.write_current_commit("commit-current")
    state_store.write_previous_commit("commit-previous")
    state_store.write_last_indexed_commit("indexed-commit")

    result = run_rollback(
        config,
        state_store,
        log_path=log_path,
        last_indexed_commit_at_start="indexed-commit",
    )

    assert result == ExitCode.SUCCESS_WITH_WARNINGS
    assert state_store.read_current_commit() == "commit-previous"
    assert state_store.read_previous_commit() == "commit-current"
    assert state_store.read_last_indexed_commit() == "indexed-commit"


def _write_config(tmp_path: Path) -> Path:
    repo_path = tmp_path / "repo"
    (repo_path / "src" / "cf").mkdir(parents=True)
    parser_path = tmp_path / "generate_config_report.py"
    parser_path.write_text("print('ok')\n", encoding="utf-8")

    payload = {
        "project": "orders",
        "repo": {
            "path": str(repo_path),
            "branch": "master",
            "remote": "origin",
            "pullMode": "ff-only",
        },
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
            "production": {
                "containerName": "mcp-orders",
                "hostPort": 8100,
                "url": "http://localhost:8100/mcp",
            },
            "build": {
                "containerName": "mcp-orders-build",
                "hostPort": 18100,
                "url": "http://localhost:18100/mcp",
            },
            "indexCode": True,
            "indexMetadata": True,
            "indexHelp": False,
            "resetDatabaseOnBuild": True,
            "resetCache": False,
            "useSse": False,
            "useGpu": False,
            "env": {"METADATA_PATH": "/app/metadata", "CODE_PATH": "/app/code"},
            "secretEnv": {"LICENSE_KEY": "ONERPA_LICENSE_KEY"},
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
            "reportValidation": {
                "enabled": True,
                "requiredReportPatterns": ['Имя: "', 'Синоним: "'],
                "forbiddenReportPatterns": [],
            },
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
        "retention": {
            "keepPreviousIndexes": 1,
            "keepLogsDays": 30,
            "keepStagingBuilds": 2,
        },
        "rollback": {
            "preserveFailedIndex": True,
        },
    }

    tool_path = Path(payload["smokeTest"]["toolSmokeTest"]["toolPath"])
    tool_path.write_text("print('ok')\n", encoding="utf-8")

    config_path = tmp_path / "project.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    return config_path


def _fake_repo_validation(repo_path: Path) -> RepoValidationResult:
    return RepoValidationResult(
        inside_work_tree=True,
        tracked_changes=[],
        untracked_changes=[],
    )


def _fake_run_parser(parser_config, parser_config_path: Path, *, verbose: bool, working_directory: Path):
    report_path = parser_config_path.parent / "metadata" / "Report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        '\t- Конфигурации.Orders\nИмя: "Orders"\nСиноним: "Orders"\n',
        encoding="utf-8",
    )
    return type("ParserResult", (), {"returncode": 0})()


def _fake_infrastructure_smoke(smoke_config, context, runner):
    return type("SmokeResult", (), {"http_status_code": 200})()


def _fake_tool_smoke(config, tool_smoke_config, working_directory: Path, url: str):
    return type("ToolSmokeResult", (), {"stdout": '{"ok":true}'})()


def _create_artifact_tree(root: Path, *, marker: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "marker.txt").write_text(marker, encoding="utf-8")
