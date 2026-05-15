from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_project_updater.config import load_project_config
from mcp_project_updater.errors import ConfigValidationError


def _write_config(tmp_path: Path, payload: dict, *, create_repo: bool = True) -> Path:
    root_path = tmp_path / "runtime"
    repo_path = root_path / "repo"
    if create_repo:
        repo_path.mkdir(parents=True)

    parser_path = tmp_path / "generate_config_report.py"
    parser_path.write_text("print('ok')\n", encoding="utf-8")
    tool_path = tmp_path / "mcp_smoke_test.py"
    tool_path.write_text("print('ok')\n", encoding="utf-8")

    global_secrets = tmp_path / "secrets.global.json"
    project_secrets = root_path / "secrets.local.json"
    project_secrets.parent.mkdir(parents=True, exist_ok=True)
    global_secrets.write_text(
        json.dumps({"ONERPA_LICENSE_KEY": "license-value", "OPENROUTER_API_KEY": "openrouter-value"}),
        encoding="utf-8",
    )
    project_secrets.write_text(
        json.dumps({"GITLAB_TOKEN": "gitlab-value", "MCP_UPDATE_WEBHOOK_URL": "https://example.com/webhook"}),
        encoding="utf-8",
    )

    config_path = tmp_path / "project.json"

    payload["parser"]["toolPath"] = str(parser_path)
    payload["smokeTest"]["toolSmokeTest"]["toolPath"] = str(tool_path)
    payload["smokeTest"]["toolSmokeTest"].pop("url", None)
    payload["paths"]["root"] = str(root_path)
    settings_payload = {
        "parser": payload["parser"],
        "mcp": {
            "env": {
                "OPENAI_API_BASE": "https://openrouter.ai/api/v1",
                "OPENAI_MODEL": "qwen/qwen3-embedding-8b",
            },
            "secretEnv": {
                "LICENSE_KEY": "ONERPA_LICENSE_KEY",
                "OPENAI_API_KEY": "OPENROUTER_API_KEY",
            },
        },
        "smokeTest": payload["smokeTest"],
    }
    (tmp_path / "settings.global.json").write_text(
        json.dumps(settings_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    payload = dict(payload)
    payload.pop("parser", None)
    payload.pop("smokeTest", None)

    config_path.write_text(json.dumps(payload), encoding="utf-8")
    return config_path


def _base_payload() -> dict:
    return {
        "project": "orders",
        "repo": {
            "branch": "master",
            "remote": "origin",
            "pullMode": "ff-only",
            "cloneUrl": None,
            "auth": {
                "type": "none",
                "tokenSecret": None,
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
            "image": "comol/1c_code_metadata_mcp:light",
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
            "env": {},
            "secretEnv": {},
        },
        "paths": {
            "root": "",
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
                "timeoutSeconds": 300,
                "attemptTimeoutSeconds": 60,
                "retryIntervalSeconds": 15,
                "diagnostic": False,
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
    assert config.smoke_test.tool_smoke_test.diagnostic is False
    assert config.smoke_test.tool_smoke_test.timeout_seconds == 300
    assert config.smoke_test.tool_smoke_test.attempt_timeout_seconds == 60
    assert config.smoke_test.tool_smoke_test.retry_interval_seconds == 15
    assert config.repo.path == config.paths.root / "repo"
    assert config.paths.staging_root == config.paths.root / "staging"
    assert config.paths.chroma_root == config.paths.root / "chroma"
    assert config.paths.state_root == config.paths.root / "state"
    assert config.paths.logs_root == config.paths.root / "logs"
    assert config.secrets.global_file == config.paths.root.parent / "secrets.global.json"
    assert config.secrets.project_file == config.paths.root / "secrets.local.json"
    assert config.settings.global_file == config.paths.root.parent / "settings.global.json"
    assert config.mcp.env["OPENAI_API_BASE"] == "https://openrouter.ai/api/v1"
    assert config.mcp.env["OPENAI_MODEL"] == "qwen/qwen3-embedding-8b"
    assert config.mcp.secret_env["OPENAI_API_KEY"] == "OPENROUTER_API_KEY"


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


def test_gitlab_token_auth_requires_token_secret(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["repo"]["auth"] = {
        "type": "gitlab-token",
        "username": "oauth2",
    }
    config_path = _write_config(tmp_path, payload)

    with pytest.raises(ConfigValidationError):
        load_project_config(config_path)


def test_project_level_parser_is_rejected(tmp_path: Path) -> None:
    payload = _base_payload()
    config_path = _write_config(tmp_path, payload)
    written = json.loads(config_path.read_text(encoding="utf-8"))
    written["parser"] = {"toolPath": "C:/bad.py"}
    config_path.write_text(json.dumps(written), encoding="utf-8")

    with pytest.raises(ConfigValidationError):
        load_project_config(config_path)


def test_global_tool_smoke_url_is_rejected(tmp_path: Path) -> None:
    payload = _base_payload()
    config_path = _write_config(tmp_path, payload)
    settings_path = tmp_path / "settings.global.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings["smokeTest"]["toolSmokeTest"]["url"] = "http://localhost:18100/mcp"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")

    with pytest.raises(ConfigValidationError):
        load_project_config(config_path)


def test_http_ready_url_is_not_required_anymore(tmp_path: Path) -> None:
    payload = _base_payload()
    config_path = _write_config(tmp_path, payload)

    config = load_project_config(config_path)

    assert config.smoke_test.infrastructure.acceptable_http_status_codes == [200, 400, 404, 405]
