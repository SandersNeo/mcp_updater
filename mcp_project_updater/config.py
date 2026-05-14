from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .constants import DEFAULT_SMOKE_PROFILE
from .errors import ConfigValidationError


def _expect_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigValidationError(f"Field '{field_name}' must be an object.")
    return value


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


def _expect_list_of_ints(value: Any, field_name: str) -> list[int]:
    if not isinstance(value, list) or any(not isinstance(item, int) or isinstance(item, bool) for item in value):
        raise ConfigValidationError(f"Field '{field_name}' must be a list of integers.")
    return list(value)


def _expect_path_string(value: Any, field_name: str) -> Path:
    return Path(_expect_string(value, field_name))


def _expect_optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigValidationError(f"Field '{field_name}' must be a string when provided.")
    stripped = value.strip()
    return stripped or None


@dataclass(slots=True)
class RepoAuthConfig:
    type: str
    token_env: str | None
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
    main_config_path: str
    main_config_required: bool
    extension_path: str
    extension_required: bool


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


@dataclass(slots=True)
class PathsConfig:
    staging_root: Path
    chroma_root: Path
    state_root: Path
    logs_root: Path


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
    require_chroma_not_empty: bool
    log_tail_lines: int
    log_error_patterns: list[str]
    log_ready_patterns: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ToolSmokeConfig:
    enabled: bool
    tool_path: Path
    url: str
    timeout_seconds: int
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
    webhook_url_env: str


@dataclass(slots=True)
class RetentionConfig:
    keep_previous_indexes: int
    keep_logs_days: int
    keep_staging_builds: int


@dataclass(slots=True)
class RollbackConfig:
    preserve_failed_index: bool = True


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
    sources_raw = _expect_mapping(raw.get("sources"), "sources")
    parser_raw = _expect_mapping(raw.get("parser"), "parser")
    mcp_raw = _expect_mapping(raw.get("mcp"), "mcp")
    production_raw = _expect_mapping(mcp_raw.get("production"), "mcp.production")
    build_raw = _expect_mapping(mcp_raw.get("build"), "mcp.build")
    paths_raw = _expect_mapping(raw.get("paths"), "paths")
    smoke_raw = _expect_mapping(raw.get("smokeTest"), "smokeTest")
    report_raw = _expect_mapping(smoke_raw.get("reportValidation"), "smokeTest.reportValidation")
    infrastructure_raw = _expect_mapping(smoke_raw.get("infrastructure"), "smokeTest.infrastructure")
    tool_raw = _expect_mapping(smoke_raw.get("toolSmokeTest"), "smokeTest.toolSmokeTest")
    notifications_raw = _expect_mapping(raw.get("notifications"), "notifications")
    retention_raw = _expect_mapping(raw.get("retention"), "retention")
    rollback_raw = _expect_mapping(raw.get("rollback", {}), "rollback")

    return ProjectConfig(
        project=_expect_string(raw.get("project"), "project"),
        repo=RepoConfig(
            path=_expect_path_string(repo_raw.get("path"), "repo.path"),
            branch=_expect_string(repo_raw.get("branch"), "repo.branch"),
            remote=_expect_string(repo_raw.get("remote"), "repo.remote"),
            pull_mode=_expect_string(repo_raw.get("pullMode"), "repo.pullMode"),
            clone_url=_expect_optional_string(repo_raw.get("cloneUrl"), "repo.cloneUrl"),
            auth=RepoAuthConfig(
                type=_expect_string(_expect_mapping(repo_raw.get("auth", {}), "repo.auth").get("type", "none"), "repo.auth.type"),
                token_env=_expect_optional_string(
                    _expect_mapping(repo_raw.get("auth", {}), "repo.auth").get("tokenEnv"),
                    "repo.auth.tokenEnv",
                ),
                username=_expect_optional_string(
                    _expect_mapping(repo_raw.get("auth", {}), "repo.auth").get("username", "oauth2"),
                    "repo.auth.username",
                ),
            ),
        ),
        sources=SourcesConfig(
            main_config_path=_expect_string(sources_raw.get("mainConfigPath"), "sources.mainConfigPath"),
            main_config_required=_expect_bool(sources_raw.get("mainConfigRequired"), "sources.mainConfigRequired"),
            extension_path=_expect_string(sources_raw.get("extensionPath"), "sources.extensionPath"),
            extension_required=_expect_bool(sources_raw.get("extensionRequired"), "sources.extensionRequired"),
        ),
        parser=ParserConfig(
            tool_path=_expect_path_string(parser_raw.get("toolPath"), "parser.toolPath"),
            encoding=_expect_string(parser_raw.get("encoding"), "parser.encoding"),
            warnings_as_errors=_expect_bool(parser_raw.get("warningsAsErrors"), "parser.warningsAsErrors"),
            build_xml_overrides=_expect_bool(parser_raw.get("buildXmlOverrides"), "parser.buildXmlOverrides"),
            allowed_exit_codes=_expect_list_of_ints(parser_raw.get("allowedExitCodes"), "parser.allowedExitCodes"),
        ),
        mcp=MCPConfig(
            image=_expect_string(mcp_raw.get("image"), "mcp.image"),
            container_port=_expect_int(mcp_raw.get("containerPort"), "mcp.containerPort"),
            production=MCPInstanceConfig(
                container_name=_expect_string(production_raw.get("containerName"), "mcp.production.containerName"),
                host_port=_expect_int(production_raw.get("hostPort"), "mcp.production.hostPort"),
                url=_expect_string(production_raw.get("url"), "mcp.production.url"),
            ),
            build=MCPInstanceConfig(
                container_name=_expect_string(build_raw.get("containerName"), "mcp.build.containerName"),
                host_port=_expect_int(build_raw.get("hostPort"), "mcp.build.hostPort"),
                url=_expect_string(build_raw.get("url"), "mcp.build.url"),
            ),
            index_code=_expect_bool(mcp_raw.get("indexCode"), "mcp.indexCode"),
            index_metadata=_expect_bool(mcp_raw.get("indexMetadata"), "mcp.indexMetadata"),
            index_help=_expect_bool(mcp_raw.get("indexHelp"), "mcp.indexHelp"),
            reset_database_on_build=_expect_bool(mcp_raw.get("resetDatabaseOnBuild"), "mcp.resetDatabaseOnBuild"),
            reset_cache=_expect_bool(mcp_raw.get("resetCache"), "mcp.resetCache"),
            use_sse=_expect_bool(mcp_raw.get("useSse"), "mcp.useSse"),
            use_gpu=_expect_bool(mcp_raw.get("useGpu"), "mcp.useGpu"),
            env={str(key): str(value) for key, value in _expect_mapping(mcp_raw.get("env"), "mcp.env").items()},
            secret_env={str(key): str(value) for key, value in _expect_mapping(mcp_raw.get("secretEnv"), "mcp.secretEnv").items()},
        ),
        paths=PathsConfig(
            staging_root=_expect_path_string(paths_raw.get("stagingRoot"), "paths.stagingRoot"),
            chroma_root=_expect_path_string(paths_raw.get("chromaRoot"), "paths.chromaRoot"),
            state_root=_expect_path_string(paths_raw.get("stateRoot"), "paths.stateRoot"),
            logs_root=_expect_path_string(paths_raw.get("logsRoot"), "paths.logsRoot"),
        ),
        smoke_test=SmokeTestConfig(
            enabled=_expect_bool(smoke_raw.get("enabled"), "smokeTest.enabled"),
            profile=str(smoke_raw.get("profile", DEFAULT_SMOKE_PROFILE)),
            report_validation=ReportValidationConfig(
                enabled=_expect_bool(report_raw.get("enabled"), "smokeTest.reportValidation.enabled"),
                required_report_patterns=[str(item) for item in report_raw.get("requiredReportPatterns", [])],
                forbidden_report_patterns=[str(item) for item in report_raw.get("forbiddenReportPatterns", [])],
            ),
            infrastructure=InfrastructureSmokeConfig(
                enabled=_expect_bool(infrastructure_raw.get("enabled"), "smokeTest.infrastructure.enabled"),
                timeout_seconds=_expect_int(infrastructure_raw.get("timeoutSeconds"), "smokeTest.infrastructure.timeoutSeconds"),
                check_interval_seconds=_expect_int(infrastructure_raw.get("checkIntervalSeconds"), "smokeTest.infrastructure.checkIntervalSeconds"),
                acceptable_http_status_codes=_expect_list_of_ints(
                    infrastructure_raw.get("acceptableHttpStatusCodes"),
                    "smokeTest.infrastructure.acceptableHttpStatusCodes",
                ),
                require_chroma_not_empty=_expect_bool(
                    infrastructure_raw.get("requireChromaNotEmpty"),
                    "smokeTest.infrastructure.requireChromaNotEmpty",
                ),
                log_tail_lines=_expect_int(infrastructure_raw.get("logTailLines"), "smokeTest.infrastructure.logTailLines"),
                log_error_patterns=[str(item) for item in infrastructure_raw.get("logErrorPatterns", [])],
                log_ready_patterns=[str(item) for item in infrastructure_raw.get("logReadyPatterns", [])],
            ),
            tool_smoke_test=ToolSmokeConfig(
                enabled=_expect_bool(tool_raw.get("enabled"), "smokeTest.toolSmokeTest.enabled"),
                tool_path=_expect_path_string(tool_raw.get("toolPath"), "smokeTest.toolSmokeTest.toolPath"),
                url=_expect_string(tool_raw.get("url"), "smokeTest.toolSmokeTest.url"),
                timeout_seconds=_expect_int(tool_raw.get("timeoutSeconds"), "smokeTest.toolSmokeTest.timeoutSeconds"),
                metadata_tool_name=_expect_string(
                    tool_raw.get("metadataToolName", "metadatasearch"),
                    "smokeTest.toolSmokeTest.metadataToolName",
                ),
                metadata_query_argument=_expect_string(
                    tool_raw.get("metadataQueryArgument", "query"),
                    "smokeTest.toolSmokeTest.metadataQueryArgument",
                ),
                metadata_queries=[str(item) for item in tool_raw.get("metadataQueries", [])],
                code_tool_name=_expect_string(
                    tool_raw.get("codeToolName", "codesearch"),
                    "smokeTest.toolSmokeTest.codeToolName",
                ),
                code_query_argument=_expect_string(
                    tool_raw.get("codeQueryArgument", "query"),
                    "smokeTest.toolSmokeTest.codeQueryArgument",
                ),
                code_queries=[str(item) for item in tool_raw.get("codeQueries", [])],
            ),
        ),
        notifications=NotificationsConfig(
            enabled=_expect_bool(notifications_raw.get("enabled"), "notifications.enabled"),
            on_success=_expect_bool(notifications_raw.get("onSuccess"), "notifications.onSuccess"),
            on_failure=_expect_bool(notifications_raw.get("onFailure"), "notifications.onFailure"),
            on_rollback=_expect_bool(notifications_raw.get("onRollback"), "notifications.onRollback"),
            webhook_url_env=_expect_string(notifications_raw.get("webhookUrlEnv"), "notifications.webhookUrlEnv"),
        ),
        retention=RetentionConfig(
            keep_previous_indexes=_expect_int(retention_raw.get("keepPreviousIndexes"), "retention.keepPreviousIndexes"),
            keep_logs_days=_expect_int(retention_raw.get("keepLogsDays"), "retention.keepLogsDays"),
            keep_staging_builds=_expect_int(retention_raw.get("keepStagingBuilds"), "retention.keepStagingBuilds"),
        ),
        rollback=RollbackConfig(
            preserve_failed_index=bool(rollback_raw.get("preserveFailedIndex", True)),
        ),
        config_path=config_path,
    )


def _validate_project_config(config: ProjectConfig) -> None:
    if not config.parser.tool_path.exists():
        raise ConfigValidationError(f"Parser tool path does not exist: {config.parser.tool_path}")

    if not config.repo.path.exists() and not config.repo.clone_url:
        raise ConfigValidationError(
            "Repository path does not exist and 'repo.cloneUrl' is not configured."
        )

    if config.repo.auth.type not in {"none", "gitlab-token"}:
        raise ConfigValidationError("Field 'repo.auth.type' must be either 'none' or 'gitlab-token'.")

    if config.repo.auth.type == "gitlab-token" and not config.repo.auth.token_env:
        raise ConfigValidationError("Field 'repo.auth.tokenEnv' must be set when repo.auth.type='gitlab-token'.")

    required_paths = {
        "paths.stagingRoot": config.paths.staging_root,
        "paths.chromaRoot": config.paths.chroma_root,
        "paths.stateRoot": config.paths.state_root,
        "paths.logsRoot": config.paths.logs_root,
    }
    for field_name, value in required_paths.items():
        if not str(value):
            raise ConfigValidationError(f"Field '{field_name}' must not be empty.")

    if config.mcp.container_port <= 0:
        raise ConfigValidationError("Field 'mcp.containerPort' must be greater than 0.")

    if config.mcp.production.host_port <= 0:
        raise ConfigValidationError("Field 'mcp.production.hostPort' must be greater than 0.")

    if config.mcp.build.host_port <= 0:
        raise ConfigValidationError("Field 'mcp.build.hostPort' must be greater than 0.")

    if config.mcp.production.host_port == config.mcp.build.host_port:
        raise ConfigValidationError("Production and build host ports must be different.")

    if config.mcp.production.container_name == config.mcp.build.container_name:
        raise ConfigValidationError("Production and build container names must be different.")

    if config.smoke_test.profile not in {"dev", "production"}:
        raise ConfigValidationError("Field 'smokeTest.profile' must be either 'dev' or 'production'.")

    if config.smoke_test.profile == "production" and not config.smoke_test.tool_smoke_test.enabled:
        raise ConfigValidationError("toolSmokeTest.enabled=false is not allowed when smokeTest.profile=production.")

    if config.notifications.enabled and (config.notifications.on_failure or config.notifications.on_rollback):
        if not config.notifications.webhook_url_env:
            raise ConfigValidationError("Field 'notifications.webhookUrlEnv' must be set when notifications are enabled.")
