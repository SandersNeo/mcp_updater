from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_project_updater.config import load_project_config
from mcp_project_updater.errors import ConfigValidationError


def _write_config(tmp_path: Path, payload: dict, *, create_repo: bool = True) -> Path:
    repo_path = tmp_path / "repo"
    if create_repo:
        repo_path.mkdir()

    parser_path = tmp_path / "generate_config_report.py"
    parser_path.write_text("print('ok')\n", encoding="utf-8")

    logs_path = tmp_path / "logs"
    config_path = tmp_path / "project.json"

    payload["repo"]["path"] = str(repo_path)
    payload["parser"]["toolPath"] = str(parser_path)
    payload["paths"]["logsRoot"] = str(logs_path)
    payload["paths"]["stagingRoot"] = str(tmp_path / "staging")
    payload["paths"]["chromaRoot"] = str(tmp_path / "chroma")
    payload["paths"]["stateRoot"] = str(tmp_path / "state")

    config_path.write_text(json.dumps(payload), encoding="utf-8")
    return config_path


def _base_payload() -> dict:
    return {
        "project": "orders",
        "repo": {
            "path": "",
            "branch": "master",
            "remote": "origin",
            "pullMode": "ff-only",
            "cloneUrl": None,
            "auth": {
                "type": "none",
                "tokenEnv": None,
                "username": "oauth2",
            },
        },
        "sources": {
            "mainConfigPath": "src/cf",
            "mainConfigRequired": False,
            "extensionPath": "src/cfe",
            "extensionRequired": False,
        },
        "parser": {
            "toolPath": "",
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
            "env": {
                "METADATA_PATH": "/app/metadata",
                "CODE_PATH": "/app/code",
            },
            "secretEnv": {
                "LICENSE_KEY": "ONERPA_LICENSE_KEY",
            },
        },
        "paths": {
            "stagingRoot": "",
            "chromaRoot": "",
            "stateRoot": "",
            "logsRoot": "",
        },
        "smokeTest": {
            "enabled": True,
            "profile": "dev",
            "reportValidation": {
                "enabled": True,
                "requiredReportPatterns": ["^\\s*-\\s*Конфигурации\\."],
                "forbiddenReportPatterns": ["src/cf"],
            },
            "infrastructure": {
                "enabled": True,
                "timeoutSeconds": 60,
                "checkIntervalSeconds": 5,
                "httpReadyUrl": "http://localhost:18100/mcp",
                "acceptableHttpStatusCodes": [200, 400, 404, 405],
                "requireChromaNotEmpty": True,
                "logTailLines": 200,
                "logErrorPatterns": ["Traceback"],
                "logReadyPatterns": ["Started"],
            },
            "toolSmokeTest": {
                "enabled": True,
                "toolPath": "C:/tools/mcp_smoke_test.py",
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


def test_load_project_config_defaults_and_validation(tmp_path: Path) -> None:
    payload = _base_payload()
    config_path = _write_config(tmp_path, payload)

    config = load_project_config(config_path)

    assert config.project == "orders"
    assert config.smoke_test.profile == "dev"
    assert config.rollback.preserve_failed_index is True
    assert config.mcp.production.host_port == 8100


def test_profile_defaults_to_dev(tmp_path: Path) -> None:
    payload = _base_payload()
    del payload["smokeTest"]["profile"]
    config_path = _write_config(tmp_path, payload)

    config = load_project_config(config_path)

    assert config.smoke_test.profile == "dev"


def test_production_profile_requires_tool_smoke(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["smokeTest"]["profile"] = "production"
    payload["smokeTest"]["toolSmokeTest"]["enabled"] = False
    config_path = _write_config(tmp_path, payload)

    with pytest.raises(ConfigValidationError):
        load_project_config(config_path)


def test_rollback_preserve_failed_index_defaults_to_true(tmp_path: Path) -> None:
    payload = _base_payload()
    del payload["rollback"]
    config_path = _write_config(tmp_path, payload)

    config = load_project_config(config_path)

    assert config.rollback.preserve_failed_index is True


def test_missing_repo_path_is_allowed_when_clone_url_is_configured(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["repo"]["cloneUrl"] = "https://gitlab.example.com/team/orders.git"
    config_path = _write_config(tmp_path, payload, create_repo=False)

    config = load_project_config(config_path)

    assert config.repo.clone_url == "https://gitlab.example.com/team/orders.git"
    assert config.repo.path.exists() is False


def test_gitlab_token_auth_requires_token_env(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["repo"]["auth"] = {
        "type": "gitlab-token",
        "username": "oauth2",
    }
    config_path = _write_config(tmp_path, payload)

    with pytest.raises(ConfigValidationError):
        load_project_config(config_path)
