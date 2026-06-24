from __future__ import annotations

import json
import platform
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .constants import DEFAULT_SMOKE_PROFILE
from .errors import ConfigValidationError
from .secrets import SecretsConfig, load_secrets
from .settings import SettingsConfig, get_mapping, load_global_settings


ALLOWED_MCP_IMAGES = {
    "comol/1c_code_metadata_mcp:light",
    "comol/1c_code_metadata_mcp:latest",
}
DEFAULT_INDEX_CONTAINER_PATH = "/app/chroma_db"
DEFAULT_CONTAINER_PORT = 8000
DEFAULT_BUILD_HOST_PORT_OFFSET = 10000
DEFAULT_PRODUCTION_CONTAINER_NAME_TEMPLATE = "mcp-{project}"
DEFAULT_BUILD_CONTAINER_NAME_TEMPLATE = "mcp-{project}-build"
DEFAULT_URL_SCHEME = "http"
DEFAULT_URL_HOST = "localhost"
DEFAULT_URL_PATH = "/mcp"
DOCKER_CONTAINER_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


def _expect_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigValidationError(f"Field '{field_name}' must be an object.")
    return value


def _expect_optional_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    return _expect_mapping(value, field_name)


def _expect_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigValidationError(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


def _expect_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigValidationError(f"Field '{field_name}' must be a boolean.")
    return value


def _expect_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigValidationError(f"Field '{field_name}' must be an integer.")
    return value


def _expect_optional_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    return _expect_int(value, field_name)


def _expect_list_of_ints(value: Any, field_name: str) -> list[int]:
    if not isinstance(value, list) or any(not isinstance(item, int) or isinstance(item, bool) for item in value):
        raise ConfigValidationError(f"Field '{field_name}' must be a list of integers.")
    return list(value)


def _expect_path_string(value: Any, field_name: str) -> Path:
    return Path(_expect_string(value, field_name))


def _expect_optional_path_string(value: Any, field_name: str) -> Path | None:
    if value is None:
        return None
    return _expect_path_string(value, field_name)


def _expect_optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigValidationError(f"Field '{field_name}' must be a string when provided.")
    stripped = value.strip()
    return stripped or None


def _expect_settings_mapping(settings: SettingsConfig, path: tuple[str, ...], field_name: str) -> dict[str, Any]:
    mapping = get_mapping(settings, path)
    if not mapping:
        raise ConfigValidationError(
            f"Settings file '{settings.global_file}' must define non-empty object '{field_name}'."
        )
    return mapping


def _reject_project_level_global_blocks(raw: dict[str, Any]) -> None:
    for field_name in ("parser", "smokeTest"):
        if field_name in raw:
            raise ConfigValidationError(
                f"Field '{field_name}' belongs in settings.global.json and must not be set in project.json."
            )


@dataclass(slots=True)
class RepoAuthConfig:
    type: str
    token_secret: str | None
    username: str | None


@dataclass(slots=True)
class RepoConfig:
    path: Path
    branch: str
    remote: str
    pull_mode: str
    clone_url: str | None
    auth: RepoAuthConfig


@dataclass(slots=True)
class SourcesConfig:
    main_config_path: str | None
    main_config_required: bool
    extension_path: str | None
    extension_required: bool
    native_report_path: str | None


@dataclass(slots=True)
class ParserConfig:
    tool_path: Path
    encoding: str
    warnings_as_errors: bool
    build_xml_overrides: bool
    allowed_exit_codes: list[int]


@dataclass(slots=True)
class MCPInstanceConfig:
    container_name: str
    host_port: int
    url: str


@dataclass(slots=True)
class MCPConfig:
    image: str
    container_port: int
    index_container_path: str
    production: MCPInstanceConfig
    build: MCPInstanceConfig
    index_code: bool
    index_metadata: bool
    index_help: bool
    reset_database_on_build: bool
    reset_cache: bool
    use_sse: bool
    use_gpu: bool
    env: dict[str, str]
    secret_env: dict[str, str]
    secrets: dict[str, str]


@dataclass(slots=True)
class PathsConfig:
    root: Path
    staging_root: Path
    index_storage_root: Path
    state_root: Path
    logs_root: Path

    @property
    def chroma_root(self) -> Path:
        return self.index_storage_root


@dataclass(slots=True)
class ReportValidationConfig:
    enabled: bool
    required_report_patterns: list[str]
    forbidden_report_patterns: list[str]


@dataclass(slots=True)
class InfrastructureSmokeConfig:
    enabled: bool
    timeout_seconds: int
    check_interval_seconds: int
    acceptable_http_status_codes: list[int]
    require_index_storage_not_empty: bool
    log_tail_lines: int
    log_error_patterns: list[str]
    log_ready_patterns: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ToolSmokeConfig:
    enabled: bool
    tool_path: Path
    timeout_seconds: int
    attempt_timeout_seconds: int
    retry_interval_seconds: int
    diagnostic: bool
    metadata_tool_name: str
    metadata_query_argument: str
    metadata_queries: list[str]
    code_tool_name: str
    code_query_argument: str
    code_queries: list[str]


@dataclass(slots=True)
class SmokeTestConfig:
    enabled: bool
    profile: str
    report_validation: ReportValidationConfig
    infrastructure: InfrastructureSmokeConfig
    tool_smoke_test: ToolSmokeConfig


@dataclass(slots=True)
class NotificationsConfig:
    enabled: bool
    on_success: bool
    on_failure: bool
    on_rollback: bool
    webhook_url_secret: str
    secrets: dict[str, str]


@dataclass(slots=True)
class RetentionConfig:
    keep_previous_indexes: int
    keep_logs_days: int
    keep_staging_builds: int


@dataclass(slots=True)
class RollbackConfig:
    preserve_failed_index: bool = True


@dataclass(slots=True)
class ProjectDefaultsConfig:
    index_storage_root_template: str | None
    production_container_name_template: str
    build_container_name_template: str
    url_scheme: str
    url_host: str
    url_path: str
    build_host_port_offset: int
    container_port: int


@dataclass(slots=True)
class ProjectConfig:
    project: str
    repo: RepoConfig
    sources: SourcesConfig
    parser: ParserConfig
    mcp: MCPConfig
    paths: PathsConfig
    smoke_test: SmokeTestConfig
    notifications: NotificationsConfig
    retention: RetentionConfig
    rollback: RollbackConfig
    secrets: SecretsConfig
    secrets_values: dict[str, str]
    settings: SettingsConfig
    config_path: Path


def load_project_config(config_path: str | Path) -> ProjectConfig:
    path = Path(config_path)
    if not path.exists():
        raise ConfigValidationError(f"Config file does not exist: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigValidationError(f"Invalid JSON in config file: {exc}") from exc

    config = _parse_project_config(raw, path)
    _validate_project_config(config)
    return config


def _parse_project_config(raw: dict[str, Any], config_path: Path) -> ProjectConfig:
    repo_raw = _expect_mapping(raw.get("repo"), "repo")
    project_name = _expect_string(raw.get("project"), "project")
    paths_raw = _expect_optional_mapping(raw.get("paths"), "paths")
    paths_root = _expect_optional_path_string(paths_raw.get("root"), "paths.root") or config_path.parent
    settings_config = load_global_settings(paths_root.parent / "settings.global.json")
    project_defaults = _parse_project_defaults(settings_config)
    _reject_project_level_global_blocks(raw)
    sources_raw = _expect_mapping(raw.get("sources"), "sources")
    parser_raw = _expect_settings_mapping(settings_config, ("parser",), "settings.parser")
    mcp_raw = _expect_mapping(raw.get("mcp"), "mcp")
    production_raw = _expect_optional_mapping(mcp_raw.get("production"), "mcp.production")
    build_raw = _expect_optional_mapping(mcp_raw.get("build"), "mcp.build")
    smoke_raw = _expect_settings_mapping(settings_config, ("smokeTest",), "settings.smokeTest")
    report_raw = _expect_mapping(smoke_raw.get("reportValidation"), "settings.smokeTest.reportValidation")
    infrastructure_raw = _expect_mapping(smoke_raw.get("infrastructure"), "settings.smokeTest.infrastructure")
    tool_raw = _expect_mapping(smoke_raw.get("toolSmokeTest"), "settings.smokeTest.toolSmokeTest")
    notifications_raw = _expect_mapping(raw.get("notifications"), "notifications")
    retention_raw = _expect_mapping(raw.get("retention"), "retention")
    rollback_raw = _expect_mapping(raw.get("rollback", {}), "rollback")
    main_config_required = _expect_bool(sources_raw.get("mainConfigRequired"), "sources.mainConfigRequired")
    extension_required = _expect_bool(sources_raw.get("extensionRequired"), "sources.extensionRequired")
    index_storage_root = _resolve_index_storage_root(mcp_raw, project_defaults, project_name)
    production_host_port = _resolve_production_host_port(mcp_raw, production_raw)
    build_host_port = _expect_optional_int(build_raw.get("hostPort"), "mcp.build.hostPort")
    if build_host_port is None:
        build_host_port = production_host_port + project_defaults.build_host_port_offset
    production_container_name = _expect_optional_string(
        production_raw.get("containerName"),
        "mcp.production.containerName",
    ) or _render_project_template(
        project_defaults.production_container_name_template,
        project_name,
        "settings.projectDefaults.productionContainerNameTemplate",
    )
    build_container_name = _expect_optional_string(
        build_raw.get("containerName"),
        "mcp.build.containerName",
    ) or _render_project_template(
        project_defaults.build_container_name_template,
        project_name,
        "settings.projectDefaults.buildContainerNameTemplate",
    )
    production_url = _expect_optional_string(
        production_raw.get("url"),
        "mcp.production.url",
    ) or _build_default_mcp_url(project_defaults, production_host_port)
    build_url = _expect_optional_string(
        build_raw.get("url"),
        "mcp.build.url",
    ) or _build_default_mcp_url(project_defaults, build_host_port)

    tool_timeout_seconds = _expect_int(tool_raw.get("timeoutSeconds"), "settings.smokeTest.toolSmokeTest.timeoutSeconds")
    if "url" in tool_raw:
        raise ConfigValidationError(
            "Field 'settings.smokeTest.toolSmokeTest.url' is forbidden; use mcp.build.url and mcp.production.url."
        )
    secrets_config = SecretsConfig(
        global_file=paths_root.parent / "secrets.global.json",
        project_file=paths_root / "secrets.local.json",
    )

    secrets_values = load_secrets(secrets_config)
    global_mcp_env = {str(key): str(value) for key, value in get_mapping(settings_config, ("mcp", "env")).items()}
    project_mcp_env_raw = _expect_mapping(mcp_raw.get("env", {}), "mcp.env")
    project_mcp_env = {str(key): str(value) for key, value in project_mcp_env_raw.items()}
    default_mcp_env = {"METADATA_PATH": "/app/metadata", "CODE_PATH": "/app/code"}
    global_mcp_secret_env = {
        str(key): str(value) for key, value in get_mapping(settings_config, ("mcp", "secretEnv")).items()
    }
    project_mcp_secret_env = {
        str(key): str(value) for key, value in _expect_mapping(mcp_raw.get("secretEnv", {}), "mcp.secretEnv").items()
    }

    return ProjectConfig(
        project=project_name,
        repo=RepoConfig(
            path=paths_root / "repo",
            branch=_expect_string(repo_raw.get("branch"), "repo.branch"),
            remote=_expect_string(repo_raw.get("remote"), "repo.remote"),
            pull_mode=_expect_string(repo_raw.get("pullMode"), "repo.pullMode"),
            clone_url=_expect_optional_string(repo_raw.get("cloneUrl"), "repo.cloneUrl"),
            auth=RepoAuthConfig(
                type=_expect_string(_expect_mapping(repo_raw.get("auth", {}), "repo.auth").get("type", "none"), "repo.auth.type"),
                token_secret=_expect_optional_string(
                    _expect_mapping(repo_raw.get("auth", {}), "repo.auth").get("tokenSecret"),
                    "repo.auth.tokenSecret",
                ),
                username=_expect_optional_string(
                    _expect_mapping(repo_raw.get("auth", {}), "repo.auth").get("username", "oauth2"),
                    "repo.auth.username",
                ),
            ),
        ),
        sources=SourcesConfig(
            main_config_path=_expect_optional_string(sources_raw.get("mainConfigPath"), "sources.mainConfigPath"),
            main_config_required=main_config_required,
            extension_path=_expect_optional_string(sources_raw.get("extensionPath"), "sources.extensionPath"),
            extension_required=extension_required,
            native_report_path=_expect_optional_string(sources_raw.get("nativeReportPath"), "sources.nativeReportPath"),
        ),
        parser=ParserConfig(
            tool_path=_expect_path_string(parser_raw.get("toolPath"), "settings.parser.toolPath"),
            encoding=_expect_string(parser_raw.get("encoding"), "settings.parser.encoding"),
            warnings_as_errors=_expect_bool(parser_raw.get("warningsAsErrors"), "settings.parser.warningsAsErrors"),
            build_xml_overrides=_expect_bool(parser_raw.get("buildXmlOverrides"), "settings.parser.buildXmlOverrides"),
            allowed_exit_codes=_expect_list_of_ints(parser_raw.get("allowedExitCodes"), "settings.parser.allowedExitCodes"),
        ),
        mcp=MCPConfig(
            image=_expect_string(mcp_raw.get("image"), "mcp.image"),
            container_port=_expect_int(mcp_raw.get("containerPort"), "mcp.containerPort")
            if "containerPort" in mcp_raw
            else project_defaults.container_port,
            index_container_path=_expect_optional_string(
                mcp_raw.get("indexContainerPath"),
                "mcp.indexContainerPath",
            )
            or DEFAULT_INDEX_CONTAINER_PATH,
            production=MCPInstanceConfig(
                container_name=production_container_name,
                host_port=production_host_port,
                url=production_url,
            ),
            build=MCPInstanceConfig(
                container_name=build_container_name,
                host_port=build_host_port,
                url=build_url,
            ),
            index_code=_expect_bool(mcp_raw.get("indexCode"), "mcp.indexCode") if "indexCode" in mcp_raw else True,
            index_metadata=_expect_bool(mcp_raw.get("indexMetadata"), "mcp.indexMetadata") if "indexMetadata" in mcp_raw else True,
            index_help=_expect_bool(mcp_raw.get("indexHelp"), "mcp.indexHelp") if "indexHelp" in mcp_raw else False,
            reset_database_on_build=_expect_bool(mcp_raw.get("resetDatabaseOnBuild"), "mcp.resetDatabaseOnBuild")
            if "resetDatabaseOnBuild" in mcp_raw
            else True,
            reset_cache=_expect_bool(mcp_raw.get("resetCache"), "mcp.resetCache") if "resetCache" in mcp_raw else False,
            use_sse=_expect_bool(mcp_raw.get("useSse"), "mcp.useSse") if "useSse" in mcp_raw else False,
            use_gpu=_expect_bool(mcp_raw.get("useGpu"), "mcp.useGpu") if "useGpu" in mcp_raw else False,
            env={**default_mcp_env, **global_mcp_env, **project_mcp_env},
            secret_env={**global_mcp_secret_env, **project_mcp_secret_env},
            secrets=secrets_values,
        ),
        paths=PathsConfig(
            root=paths_root,
            staging_root=paths_root / "staging",
            index_storage_root=index_storage_root,
            state_root=paths_root / "state",
            logs_root=paths_root / "logs",
        ),
        smoke_test=SmokeTestConfig(
            enabled=_expect_bool(smoke_raw.get("enabled"), "settings.smokeTest.enabled"),
            profile=str(smoke_raw.get("profile", DEFAULT_SMOKE_PROFILE)),
            report_validation=ReportValidationConfig(
                enabled=_expect_bool(report_raw.get("enabled"), "settings.smokeTest.reportValidation.enabled"),
                required_report_patterns=[str(item) for item in report_raw.get("requiredReportPatterns", [])],
                forbidden_report_patterns=[str(item) for item in report_raw.get("forbiddenReportPatterns", [])],
            ),
            infrastructure=InfrastructureSmokeConfig(
                enabled=_expect_bool(infrastructure_raw.get("enabled"), "settings.smokeTest.infrastructure.enabled"),
                timeout_seconds=_expect_int(infrastructure_raw.get("timeoutSeconds"), "settings.smokeTest.infrastructure.timeoutSeconds"),
                check_interval_seconds=_expect_int(infrastructure_raw.get("checkIntervalSeconds"), "settings.smokeTest.infrastructure.checkIntervalSeconds"),
                acceptable_http_status_codes=_expect_list_of_ints(
                    infrastructure_raw.get("acceptableHttpStatusCodes"),
                    "settings.smokeTest.infrastructure.acceptableHttpStatusCodes",
                ),
                require_index_storage_not_empty=_expect_infrastructure_storage_required(infrastructure_raw),
                log_tail_lines=_expect_int(infrastructure_raw.get("logTailLines"), "settings.smokeTest.infrastructure.logTailLines"),
                log_error_patterns=[str(item) for item in infrastructure_raw.get("logErrorPatterns", [])],
                log_ready_patterns=[str(item) for item in infrastructure_raw.get("logReadyPatterns", [])],
            ),
            tool_smoke_test=ToolSmokeConfig(
                enabled=_expect_bool(tool_raw.get("enabled"), "settings.smokeTest.toolSmokeTest.enabled"),
                tool_path=_expect_path_string(tool_raw.get("toolPath"), "settings.smokeTest.toolSmokeTest.toolPath"),
                timeout_seconds=tool_timeout_seconds,
                attempt_timeout_seconds=_expect_int(
                    tool_raw.get("attemptTimeoutSeconds", min(tool_timeout_seconds, 60)),
                    "settings.smokeTest.toolSmokeTest.attemptTimeoutSeconds",
                ),
                retry_interval_seconds=_expect_int(
                    tool_raw.get("retryIntervalSeconds", 15),
                    "settings.smokeTest.toolSmokeTest.retryIntervalSeconds",
                ),
                diagnostic=_expect_bool(tool_raw.get("diagnostic", False), "settings.smokeTest.toolSmokeTest.diagnostic"),
                metadata_tool_name=_expect_string(
                    tool_raw.get("metadataToolName", "metadatasearch"),
                    "settings.smokeTest.toolSmokeTest.metadataToolName",
                ),
                metadata_query_argument=_expect_string(
                    tool_raw.get("metadataQueryArgument", "query"),
                    "settings.smokeTest.toolSmokeTest.metadataQueryArgument",
                ),
                metadata_queries=[str(item) for item in tool_raw.get("metadataQueries", [])],
                code_tool_name=_expect_string(
                    tool_raw.get("codeToolName", "codesearch"),
                    "settings.smokeTest.toolSmokeTest.codeToolName",
                ),
                code_query_argument=_expect_string(
                    tool_raw.get("codeQueryArgument", "query"),
                    "settings.smokeTest.toolSmokeTest.codeQueryArgument",
                ),
                code_queries=[str(item) for item in tool_raw.get("codeQueries", [])],
            ),
        ),
        notifications=NotificationsConfig(
            enabled=_expect_bool(notifications_raw.get("enabled"), "notifications.enabled"),
            on_success=_expect_bool(notifications_raw.get("onSuccess"), "notifications.onSuccess"),
            on_failure=_expect_bool(notifications_raw.get("onFailure"), "notifications.onFailure"),
            on_rollback=_expect_bool(notifications_raw.get("onRollback"), "notifications.onRollback"),
            webhook_url_secret=_expect_string(notifications_raw.get("webhookUrlSecret"), "notifications.webhookUrlSecret"),
            secrets=secrets_values,
        ),
        retention=RetentionConfig(
            keep_previous_indexes=_expect_int(retention_raw.get("keepPreviousIndexes"), "retention.keepPreviousIndexes"),
            keep_logs_days=_expect_int(retention_raw.get("keepLogsDays"), "retention.keepLogsDays"),
            keep_staging_builds=_expect_int(retention_raw.get("keepStagingBuilds"), "retention.keepStagingBuilds"),
        ),
        rollback=RollbackConfig(
            preserve_failed_index=bool(rollback_raw.get("preserveFailedIndex", True)),
        ),
        secrets=secrets_config,
        secrets_values=secrets_values,
        settings=settings_config,
        config_path=config_path,
    )


def _validate_project_config(config: ProjectConfig) -> None:
    if not config.sources.native_report_path and not config.parser.tool_path.exists():
        raise ConfigValidationError(f"Parser tool path does not exist: {config.parser.tool_path}")

    if not config.repo.path.exists() and not config.repo.clone_url:
        raise ConfigValidationError(
            "Repository path does not exist and 'repo.cloneUrl' is not configured."
        )

    if config.repo.auth.type not in {"none", "gitlab-token"}:
        raise ConfigValidationError("Field 'repo.auth.type' must be either 'none' or 'gitlab-token'.")

    if config.repo.auth.type == "gitlab-token" and not config.repo.auth.token_secret:
        raise ConfigValidationError("Field 'repo.auth.tokenSecret' must be set when repo.auth.type='gitlab-token'.")

    if config.repo.auth.type == "gitlab-token" and config.repo.auth.token_secret not in config.secrets_values:
        raise ConfigValidationError(f"Git token secret is missing from secrets files: {config.repo.auth.token_secret}")

    if not str(config.paths.root):
        raise ConfigValidationError("Field 'paths.root' must not be empty.")

    _validate_index_storage_root(config.paths.index_storage_root)

    if config.sources.main_config_required and not config.sources.main_config_path:
        raise ConfigValidationError("Field 'sources.mainConfigPath' must be set when sources.mainConfigRequired=true.")

    if config.sources.extension_required and not config.sources.extension_path:
        raise ConfigValidationError("Field 'sources.extensionPath' must be set when sources.extensionRequired=true.")

    if not config.sources.main_config_path and not config.sources.extension_path:
        raise ConfigValidationError("At least one of sources.mainConfigPath or sources.extensionPath must be set.")

    if config.mcp.container_port <= 0:
        raise ConfigValidationError("Field 'mcp.containerPort' must be greater than 0.")

    _validate_index_container_path(config.mcp.index_container_path)

    if config.mcp.image not in ALLOWED_MCP_IMAGES:
        allowed = ", ".join(sorted(ALLOWED_MCP_IMAGES))
        raise ConfigValidationError(f"Field 'mcp.image' must be one of: {allowed}.")

    if config.mcp.production.host_port <= 0:
        raise ConfigValidationError("Field 'mcp.production.hostPort' must be greater than 0.")

    if config.mcp.build.host_port <= 0:
        raise ConfigValidationError("Field 'mcp.build.hostPort' must be greater than 0.")

    if config.mcp.production.host_port == config.mcp.build.host_port:
        raise ConfigValidationError("Production and build host ports must be different.")

    if config.mcp.production.container_name == config.mcp.build.container_name:
        raise ConfigValidationError("Production and build container names must be different.")

    _validate_docker_container_name(config.mcp.production.container_name, "mcp.production.containerName")
    _validate_docker_container_name(config.mcp.build.container_name, "mcp.build.containerName")

    if config.smoke_test.profile not in {"dev", "production"}:
        raise ConfigValidationError("Field 'smokeTest.profile' must be either 'dev' or 'production'.")

    if config.smoke_test.profile == "production" and not config.smoke_test.tool_smoke_test.enabled:
        raise ConfigValidationError("toolSmokeTest.enabled=false is not allowed when smokeTest.profile=production.")

    if config.smoke_test.tool_smoke_test.timeout_seconds <= 0:
        raise ConfigValidationError("Field 'smokeTest.toolSmokeTest.timeoutSeconds' must be greater than 0.")

    if config.smoke_test.tool_smoke_test.attempt_timeout_seconds <= 0:
        raise ConfigValidationError("Field 'smokeTest.toolSmokeTest.attemptTimeoutSeconds' must be greater than 0.")

    if config.smoke_test.tool_smoke_test.retry_interval_seconds < 0:
        raise ConfigValidationError("Field 'smokeTest.toolSmokeTest.retryIntervalSeconds' must be greater than or equal to 0.")

    if config.notifications.enabled and (config.notifications.on_success or config.notifications.on_failure or config.notifications.on_rollback):
        if not config.notifications.webhook_url_secret:
            raise ConfigValidationError("Field 'notifications.webhookUrlSecret' must be set when notifications are enabled.")
        if config.notifications.webhook_url_secret not in config.secrets_values:
            raise ConfigValidationError(f"Notification webhook secret is missing from secrets files: {config.notifications.webhook_url_secret}")

    for secret_name in config.mcp.secret_env.values():
        if secret_name not in config.secrets_values:
            raise ConfigValidationError(f"MCP secret is missing from secrets files: {secret_name}")


def _expect_infrastructure_storage_required(infrastructure_raw: dict[str, Any]) -> bool:
    if "requireIndexStorageNotEmpty" in infrastructure_raw:
        return _expect_bool(
            infrastructure_raw.get("requireIndexStorageNotEmpty"),
            "settings.smokeTest.infrastructure.requireIndexStorageNotEmpty",
        )
    if "requireChromaNotEmpty" in infrastructure_raw:
        return _expect_bool(
            infrastructure_raw.get("requireChromaNotEmpty"),
            "settings.smokeTest.infrastructure.requireChromaNotEmpty",
        )
    raise ConfigValidationError("Field 'settings.smokeTest.infrastructure.requireIndexStorageNotEmpty' must be a boolean.")


def _parse_project_defaults(settings: SettingsConfig) -> ProjectDefaultsConfig:
    defaults_raw = get_mapping(settings, ("projectDefaults",))
    build_host_port_offset = _expect_optional_int(
        defaults_raw.get("buildHostPortOffset"),
        "settings.projectDefaults.buildHostPortOffset",
    )
    if build_host_port_offset is None:
        build_host_port_offset = DEFAULT_BUILD_HOST_PORT_OFFSET
    if build_host_port_offset <= 0:
        raise ConfigValidationError("Field 'settings.projectDefaults.buildHostPortOffset' must be greater than 0.")

    container_port = _expect_optional_int(
        defaults_raw.get("containerPort"),
        "settings.projectDefaults.containerPort",
    )
    if container_port is None:
        container_port = DEFAULT_CONTAINER_PORT
    if container_port <= 0:
        raise ConfigValidationError("Field 'settings.projectDefaults.containerPort' must be greater than 0.")

    url_path = _expect_optional_string(defaults_raw.get("urlPath"), "settings.projectDefaults.urlPath") or DEFAULT_URL_PATH
    if not url_path.startswith("/"):
        raise ConfigValidationError("Field 'settings.projectDefaults.urlPath' must start with '/'.")

    return ProjectDefaultsConfig(
        index_storage_root_template=_expect_optional_string(
            defaults_raw.get("indexStorageRootTemplate"),
            "settings.projectDefaults.indexStorageRootTemplate",
        ),
        production_container_name_template=_expect_optional_string(
            defaults_raw.get("productionContainerNameTemplate"),
            "settings.projectDefaults.productionContainerNameTemplate",
        )
        or DEFAULT_PRODUCTION_CONTAINER_NAME_TEMPLATE,
        build_container_name_template=_expect_optional_string(
            defaults_raw.get("buildContainerNameTemplate"),
            "settings.projectDefaults.buildContainerNameTemplate",
        )
        or DEFAULT_BUILD_CONTAINER_NAME_TEMPLATE,
        url_scheme=_expect_optional_string(defaults_raw.get("urlScheme"), "settings.projectDefaults.urlScheme")
        or DEFAULT_URL_SCHEME,
        url_host=_expect_optional_string(defaults_raw.get("urlHost"), "settings.projectDefaults.urlHost") or DEFAULT_URL_HOST,
        url_path=url_path,
        build_host_port_offset=build_host_port_offset,
        container_port=container_port,
    )


def _resolve_index_storage_root(
    mcp_raw: dict[str, Any],
    project_defaults: ProjectDefaultsConfig,
    project_name: str,
) -> Path:
    explicit_value = _expect_optional_path_string(mcp_raw.get("indexStorageRoot"), "mcp.indexStorageRoot")
    if explicit_value is not None:
        return explicit_value
    if not project_defaults.index_storage_root_template:
        raise ConfigValidationError(
            "Field 'mcp.indexStorageRoot' must be set when "
            "'settings.projectDefaults.indexStorageRootTemplate' is not configured."
        )
    return Path(
        _render_project_template(
            project_defaults.index_storage_root_template,
            project_name,
            "settings.projectDefaults.indexStorageRootTemplate",
        )
    )


def _resolve_production_host_port(mcp_raw: dict[str, Any], production_raw: dict[str, Any]) -> int:
    compact_host_port = _expect_optional_int(mcp_raw.get("hostPort"), "mcp.hostPort")
    production_host_port = _expect_optional_int(production_raw.get("hostPort"), "mcp.production.hostPort")
    if compact_host_port is not None and production_host_port is not None and compact_host_port != production_host_port:
        raise ConfigValidationError("Fields 'mcp.hostPort' and 'mcp.production.hostPort' must match when both are set.")
    resolved = production_host_port if production_host_port is not None else compact_host_port
    if resolved is None:
        raise ConfigValidationError("Field 'mcp.hostPort' or 'mcp.production.hostPort' must be set.")
    return resolved


def _render_project_template(template: str, project_name: str, field_name: str) -> str:
    rendered = template.replace("{project}", project_name)
    if not rendered.strip():
        raise ConfigValidationError(f"Field '{field_name}' rendered an empty value.")
    return rendered


def _build_default_mcp_url(project_defaults: ProjectDefaultsConfig, host_port: int) -> str:
    return f"{project_defaults.url_scheme}://{project_defaults.url_host}:{host_port}{project_defaults.url_path}"


def _validate_index_storage_root(path: Path) -> None:
    value = str(path)
    if platform.system().lower() == "windows":
        if not _is_wsl_unc_path(value):
            raise ConfigValidationError(
                "Field 'mcp.indexStorageRoot' must be a WSL-mounted UNC path on Windows "
                "(\\\\wsl.localhost\\... or \\\\wsl$\\...)."
            )
    elif not path.is_absolute():
        raise ConfigValidationError("Field 'mcp.indexStorageRoot' must be an absolute path.")

    if not _is_path_or_parent_accessible(path):
        raise ConfigValidationError(
            f"Field 'mcp.indexStorageRoot' or its parent path must be accessible: {path}"
        )


def _validate_index_container_path(value: str) -> None:
    if not value.startswith("/") or "\\" in value or ":" in value:
        raise ConfigValidationError(
            "Field 'mcp.indexContainerPath' must be an absolute Unix-style container path."
        )


def _validate_docker_container_name(value: str, field_name: str) -> None:
    if not DOCKER_CONTAINER_NAME_PATTERN.match(value):
        raise ConfigValidationError(f"Field '{field_name}' must be a valid Docker container name.")


def _is_path_or_parent_accessible(path: Path) -> bool:
    return path.exists() or path.parent.exists()


def _is_wsl_unc_path(value: str) -> bool:
    normalized = value.replace("/", "\\").lower()
    return normalized.startswith("\\\\wsl.localhost\\") or normalized.startswith("\\\\wsl$\\")
