from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_project_updater.config import load_project_config
from mcp_project_updater.errors import ConfigValidationError


def _write_config(
    tmp_path: Path,
    payload: dict,
    *,
    create_repo: bool = True,
    explicit_paths_root: bool = True,
    explicit_index_storage_root: bool = True,
    include_project_defaults: bool = False,
) -> Path:
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
        json.dumps({"ONERPA_LICENSE_KEY": "license-value"}),
        encoding="utf-8",
    )
    project_secrets.write_text(
        json.dumps({"GITLAB_TOKEN": "gitlab-value", "MCP_UPDATE_WEBHOOK_URL": "https://example.com/webhook"}),
        encoding="utf-8",
    )

    config_path = tmp_path / "project.json" if explicit_paths_root else root_path / "project.json"

    payload["parser"]["toolPath"] = str(parser_path)
    payload["smokeTest"]["toolSmokeTest"]["toolPath"] = str(tool_path)
    payload["smokeTest"]["toolSmokeTest"].pop("url", None)
    if explicit_paths_root:
        payload.setdefault("paths", {})["root"] = str(root_path)
    else:
        payload.pop("paths", None)
    if explicit_index_storage_root:
        payload["mcp"]["indexStorageRoot"] = payload["mcp"].get("indexStorageRoot") or str(root_path / "index-storage")
    else:
        payload["mcp"].pop("indexStorageRoot", None)
    settings_payload = {
        "parser": payload["parser"],
        "mcp": {
            "env": {},
            "secretEnv": {
                "LICENSE_KEY": "ONERPA_LICENSE_KEY",
            },
        },
        "smokeTest": payload["smokeTest"],
    }
    if include_project_defaults:
        (tmp_path / "indexes").mkdir(parents=True, exist_ok=True)
        settings_payload["projectDefaults"] = {
            "indexStorageRootTemplate": str(tmp_path / "indexes" / "{project}"),
            "productionContainerNameTemplate": "mcp-{project}",
            "buildContainerNameTemplate": "mcp-{project}-build",
            "urlScheme": "http",
            "urlHost": "localhost",
            "urlPath": "/mcp",
            "buildHostPortOffset": 10000,
            "containerPort": 8000,
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
            "nativeReportPath": None,
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
            "indexStorageRoot": "",
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
                "acceptableHttpStatusCodes": [200, 400, 404, 405, 406],
                "requireIndexStorageNotEmpty": True,
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
    assert config.mcp.index_container_path == "/app/chroma_db"
    assert config.paths.staging_root == config.paths.root / "staging"
    assert config.paths.index_storage_root == config.paths.root / "index-storage"
    assert config.paths.chroma_root == config.paths.index_storage_root
    assert config.paths.chroma_root != config.paths.root / "chroma"
    assert config.paths.state_root == config.paths.root / "state"
    assert config.paths.logs_root == config.paths.root / "logs"
    assert config.secrets.global_file == config.paths.root.parent / "secrets.global.json"
    assert config.secrets.project_file == config.paths.root / "secrets.local.json"
    assert config.settings.global_file == config.paths.root.parent / "settings.global.json"
    assert "OPENAI_API_BASE" not in config.mcp.env
    assert "OPENAI_MODEL" not in config.mcp.env
    assert "OPENAI_API_KEY" not in config.mcp.secret_env
    assert config.smoke_test.infrastructure.require_index_storage_not_empty is True


def test_paths_root_defaults_to_project_config_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _base_payload()
    config_path = _write_config(
        tmp_path,
        payload,
        explicit_paths_root=False,
        explicit_index_storage_root=False,
        include_project_defaults=True,
    )
    monkeypatch.setattr("mcp_project_updater.config.platform.system", lambda: "Linux")

    config = load_project_config(config_path)

    assert config.paths.root == config_path.parent
    assert config.repo.path == config_path.parent / "repo"
    assert config.settings.global_file == config_path.parent.parent / "settings.global.json"
    assert config.secrets.project_file == config_path.parent / "secrets.local.json"


def test_explicit_paths_root_preserves_settings_location(tmp_path: Path) -> None:
    payload = _base_payload()
    config_path = _write_config(tmp_path, payload)

    config = load_project_config(config_path)

    assert config.paths.root == tmp_path / "runtime"
    assert config.settings.global_file == tmp_path / "settings.global.json"


def test_index_storage_root_can_be_derived_from_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _base_payload()
    config_path = _write_config(
        tmp_path,
        payload,
        explicit_index_storage_root=False,
        include_project_defaults=True,
    )
    monkeypatch.setattr("mcp_project_updater.config.platform.system", lambda: "Linux")

    config = load_project_config(config_path)

    assert config.paths.index_storage_root == tmp_path / "indexes" / "orders"


def test_compact_mcp_settings_derive_instances_and_urls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _base_payload()
    payload["mcp"] = {
        "image": "comol/1c_code_metadata_mcp:latest",
        "hostPort": 8100,
    }
    config_path = _write_config(
        tmp_path,
        payload,
        explicit_index_storage_root=False,
        include_project_defaults=True,
    )
    monkeypatch.setattr("mcp_project_updater.config.platform.system", lambda: "Linux")

    config = load_project_config(config_path)

    assert config.mcp.container_port == 8000
    assert config.mcp.production.container_name == "mcp-orders"
    assert config.mcp.build.container_name == "mcp-orders-build"
    assert config.mcp.production.host_port == 8100
    assert config.mcp.build.host_port == 18100
    assert config.mcp.production.url == "http://localhost:8100/mcp"
    assert config.mcp.build.url == "http://localhost:18100/mcp"


def test_compact_host_port_conflict_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _base_payload()
    payload["mcp"]["hostPort"] = 8100
    payload["mcp"]["production"]["hostPort"] = 8200
    config_path = _write_config(tmp_path, payload)
    monkeypatch.setattr("mcp_project_updater.config.platform.system", lambda: "Linux")

    with pytest.raises(ConfigValidationError, match="mcp.hostPort"):
        load_project_config(config_path)


def test_explicit_instance_settings_override_derived_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _base_payload()
    payload["mcp"] = {
        "image": "comol/1c_code_metadata_mcp:latest",
        "hostPort": 8100,
        "production": {
            "containerName": "custom-prod",
            "url": "http://prod.example/mcp",
        },
        "build": {
            "containerName": "custom-build",
            "hostPort": 19000,
            "url": "http://build.example/mcp",
        },
    }
    config_path = _write_config(
        tmp_path,
        payload,
        explicit_index_storage_root=False,
        include_project_defaults=True,
    )
    monkeypatch.setattr("mcp_project_updater.config.platform.system", lambda: "Linux")

    config = load_project_config(config_path)

    assert config.mcp.production.container_name == "custom-prod"
    assert config.mcp.production.host_port == 8100
    assert config.mcp.production.url == "http://prod.example/mcp"
    assert config.mcp.build.container_name == "custom-build"
    assert config.mcp.build.host_port == 19000
    assert config.mcp.build.url == "http://build.example/mcp"


def test_common_mcp_flags_default_for_compact_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _base_payload()
    payload["mcp"] = {
        "image": "comol/1c_code_metadata_mcp:latest",
        "hostPort": 8100,
    }
    config_path = _write_config(
        tmp_path,
        payload,
        explicit_index_storage_root=False,
        include_project_defaults=True,
    )
    monkeypatch.setattr("mcp_project_updater.config.platform.system", lambda: "Linux")

    config = load_project_config(config_path)

    assert config.mcp.index_code is True
    assert config.mcp.index_metadata is True
    assert config.mcp.index_help is False
    assert config.mcp.reset_database_on_build is True
    assert config.mcp.reset_cache is False
    assert config.mcp.use_sse is False
    assert config.mcp.use_gpu is False


def test_openai_env_is_optional_without_project_mapping(tmp_path: Path) -> None:
    payload = _base_payload()
    config_path = _write_config(tmp_path, payload)

    config = load_project_config(config_path)

    assert "OPENAI_API_BASE" not in config.mcp.env
    assert "OPENAI_MODEL" not in config.mcp.env


def test_project_level_openai_env_is_supported(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["mcp"]["env"] = {
        "OPENAI_API_BASE": "https://openrouter.ai/api/v1",
        "OPENAI_MODEL": "qwen/qwen3-embedding-8b",
    }
    config_path = _write_config(tmp_path, payload)

    config = load_project_config(config_path)

    assert config.mcp.env["OPENAI_API_BASE"] == "https://openrouter.ai/api/v1"
    assert config.mcp.env["OPENAI_MODEL"] == "qwen/qwen3-embedding-8b"


def test_openai_api_key_is_optional_without_project_mapping(tmp_path: Path) -> None:
    payload = _base_payload()
    config_path = _write_config(tmp_path, payload)
    global_secrets_path = tmp_path / "secrets.global.json"
    global_secrets = json.loads(global_secrets_path.read_text(encoding="utf-8"))
    global_secrets.pop("OPENROUTER_API_KEY", None)
    global_secrets_path.write_text(json.dumps(global_secrets), encoding="utf-8")

    config = load_project_config(config_path)

    assert "OPENAI_API_KEY" not in config.mcp.secret_env
    assert "OPENROUTER_API_KEY" not in config.secrets_values


def test_project_level_openai_api_key_mapping_is_supported(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["mcp"]["secretEnv"] = {"OPENAI_API_KEY": "OPENROUTER_API_KEY"}
    config_path = _write_config(tmp_path, payload)
    project_secrets_path = tmp_path / "runtime" / "secrets.local.json"
    project_secrets = json.loads(project_secrets_path.read_text(encoding="utf-8"))
    project_secrets["OPENROUTER_API_KEY"] = "project-openrouter-key"
    project_secrets_path.write_text(json.dumps(project_secrets), encoding="utf-8")

    config = load_project_config(config_path)

    assert config.mcp.secret_env["OPENAI_API_KEY"] == "OPENROUTER_API_KEY"
    assert config.secrets_values["OPENROUTER_API_KEY"] == "project-openrouter-key"


def test_project_level_openai_api_key_mapping_requires_secret(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["mcp"]["secretEnv"] = {"OPENAI_API_KEY": "OPENROUTER_API_KEY"}
    config_path = _write_config(tmp_path, payload)

    with pytest.raises(ConfigValidationError, match="OPENROUTER_API_KEY"):
        load_project_config(config_path)


def test_missing_index_storage_root_is_rejected(tmp_path: Path) -> None:
    payload = _base_payload()
    del payload["mcp"]["indexStorageRoot"]
    config_path = _write_config(tmp_path, payload)
    written = json.loads(config_path.read_text(encoding="utf-8"))
    del written["mcp"]["indexStorageRoot"]
    config_path.write_text(json.dumps(written), encoding="utf-8")

    with pytest.raises(ConfigValidationError, match="mcp.indexStorageRoot"):
        load_project_config(config_path)


def test_windows_index_storage_root_must_be_wsl_unc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _base_payload()
    payload["mcp"]["indexStorageRoot"] = "C:/mcp/index-storage"
    config_path = _write_config(tmp_path, payload)
    monkeypatch.setattr("mcp_project_updater.config.platform.system", lambda: "Windows")

    with pytest.raises(ConfigValidationError, match="WSL-mounted UNC path"):
        load_project_config(config_path)


def test_windows_wsl_index_storage_root_is_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _base_payload()
    payload["mcp"]["indexStorageRoot"] = r"\\wsl.localhost\Ubuntu\mcp\orders"
    config_path = _write_config(tmp_path, payload)
    monkeypatch.setattr("mcp_project_updater.config.platform.system", lambda: "Windows")
    monkeypatch.setattr("mcp_project_updater.config._is_path_or_parent_accessible", lambda path: True)

    config = load_project_config(config_path)

    assert str(config.paths.index_storage_root) == r"\\wsl.localhost\Ubuntu\mcp\orders"


def test_linux_index_storage_root_must_be_absolute(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["mcp"]["indexStorageRoot"] = "relative/index-storage"
    config_path = _write_config(tmp_path, payload)

    with pytest.raises(ConfigValidationError, match="absolute path"):
        load_project_config(config_path)


def test_linux_absolute_index_storage_root_is_allowed(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["mcp"]["indexStorageRoot"] = str(tmp_path / "linux-index-storage")
    config_path = _write_config(tmp_path, payload)

    config = load_project_config(config_path)

    assert config.paths.index_storage_root == tmp_path / "linux-index-storage"


def test_index_container_path_override_is_supported(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["mcp"]["indexContainerPath"] = "/app/zvec_db"
    config_path = _write_config(tmp_path, payload)

    config = load_project_config(config_path)

    assert config.mcp.index_container_path == "/app/zvec_db"


def test_explicit_default_index_container_path_is_supported(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["mcp"]["indexContainerPath"] = "/app/chroma_db"
    config_path = _write_config(tmp_path, payload)

    config = load_project_config(config_path)

    assert config.mcp.index_container_path == "/app/chroma_db"


@pytest.mark.parametrize("index_container_path", ["app/chroma_db", r"C:\app\chroma_db", "/app\\chroma_db"])
def test_invalid_index_container_path_is_rejected(tmp_path: Path, index_container_path: str) -> None:
    payload = _base_payload()
    payload["mcp"]["indexContainerPath"] = index_container_path
    config_path = _write_config(tmp_path, payload)

    with pytest.raises(ConfigValidationError, match="mcp.indexContainerPath"):
        load_project_config(config_path)


def test_legacy_require_chroma_not_empty_alias_is_supported(tmp_path: Path) -> None:
    payload = _base_payload()
    infrastructure = payload["smokeTest"]["infrastructure"]
    del infrastructure["requireIndexStorageNotEmpty"]
    infrastructure["requireChromaNotEmpty"] = False
    config_path = _write_config(tmp_path, payload)

    config = load_project_config(config_path)

    assert config.smoke_test.infrastructure.require_index_storage_not_empty is False


def test_missing_index_storage_smoke_setting_uses_new_error_name(tmp_path: Path) -> None:
    payload = _base_payload()
    infrastructure = payload["smokeTest"]["infrastructure"]
    del infrastructure["requireIndexStorageNotEmpty"]
    config_path = _write_config(tmp_path, payload)

    with pytest.raises(ConfigValidationError, match="requireIndexStorageNotEmpty"):
        load_project_config(config_path)


def test_stable_latest_image_is_allowed(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["mcp"]["image"] = "comol/1c_code_metadata_mcp:latest"
    config_path = _write_config(tmp_path, payload)

    config = load_project_config(config_path)

    assert config.mcp.image == "comol/1c_code_metadata_mcp:latest"


def test_beta_image_is_rejected(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["mcp"]["image"] = "comol/1c_code_metadata_mcp:latest-beta"
    config_path = _write_config(tmp_path, payload)

    with pytest.raises(ConfigValidationError, match="mcp.image"):
        load_project_config(config_path)


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

    assert config.smoke_test.infrastructure.acceptable_http_status_codes == [200, 400, 404, 405, 406]


def test_extension_only_project_is_allowed(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["sources"]["mainConfigPath"] = None
    payload["sources"]["mainConfigRequired"] = False
    payload["sources"]["extensionPath"] = "src/cfe"
    payload["sources"]["extensionRequired"] = True
    config_path = _write_config(tmp_path, payload)

    config = load_project_config(config_path)

    assert config.sources.main_config_path is None
    assert config.sources.extension_path == "src/cfe"


def test_main_only_project_is_allowed(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["sources"]["mainConfigPath"] = "src/cf"
    payload["sources"]["mainConfigRequired"] = True
    payload["sources"]["extensionPath"] = None
    payload["sources"]["extensionRequired"] = False
    config_path = _write_config(tmp_path, payload)

    config = load_project_config(config_path)

    assert config.sources.main_config_path == "src/cf"
    assert config.sources.extension_path is None


def test_native_report_path_is_loaded(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["sources"]["nativeReportPath"] = "native/Report.txt"
    config_path = _write_config(tmp_path, payload)

    config = load_project_config(config_path)

    assert config.sources.native_report_path == "native/Report.txt"


def test_native_report_allows_missing_parser_tool(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["sources"]["nativeReportPath"] = "native/Report.txt"
    config_path = _write_config(tmp_path, payload)
    settings_path = tmp_path / "settings.global.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings["parser"]["toolPath"] = str(tmp_path / "missing_parser.py")
    settings_path.write_text(json.dumps(settings), encoding="utf-8")

    config = load_project_config(config_path)

    assert config.parser.tool_path.name == "missing_parser.py"


def test_required_main_source_path_must_be_configured(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["sources"]["mainConfigPath"] = None
    payload["sources"]["mainConfigRequired"] = True
    config_path = _write_config(tmp_path, payload)

    with pytest.raises(ConfigValidationError):
        load_project_config(config_path)


def test_at_least_one_source_path_must_be_configured(tmp_path: Path) -> None:
    payload = _base_payload()
    payload["sources"]["mainConfigPath"] = None
    payload["sources"]["mainConfigRequired"] = False
    payload["sources"]["extensionPath"] = None
    payload["sources"]["extensionRequired"] = False
    config_path = _write_config(tmp_path, payload)

    with pytest.raises(ConfigValidationError):
        load_project_config(config_path)
