from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass
from pathlib import Path

from .config import MCPConfig, MCPInstanceConfig, PathsConfig
from .constants import ExitCode
from .docker_ops import DockerCommandResult, DockerCommandRunner, remove_container, run_docker_command
from .errors import UpdaterError
from .filesystem_cleanup import FilesystemCleanupError, remove_path_if_exists
from .staging import BuildPaths

logger = logging.getLogger(__name__)


class MissingSecretEnvError(UpdaterError):
    def __init__(self, secret_name: str) -> None:
        super().__init__(f"Required secret is missing from secrets files: {secret_name}", ExitCode.MISSING_REQUIRED_SECRET)


@dataclass(slots=True)
class BuildContainerStartResult:
    command: list[str]
    container_id: str


@dataclass(slots=True)
class ContainerStartResult:
    command: list[str]
    container_id: str


def prepare_index_storage_build(index_storage_root: Path, *, seed_source: Path | None = None) -> Path:
    build_path = index_storage_root / "build"
    try:
        remove_path_if_exists(
            build_path,
            allowed_root=index_storage_root,
            description="build index storage",
        )
    except FilesystemCleanupError as exc:
        raise UpdaterError(str(exc), ExitCode.BUILD_CONTAINER_FAILED) from exc
    if seed_source is not None and seed_source.exists():
        import shutil

        shutil.copytree(seed_source, build_path)
    else:
        build_path.mkdir(parents=True, exist_ok=True)
    return build_path


def prepare_chroma_build(chroma_root: Path, *, seed_source: Path | None = None) -> Path:
    return prepare_index_storage_build(chroma_root, seed_source=seed_source)


def resolve_secret_environment(secret_env_mapping: dict[str, str], secrets: dict[str, str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for container_var, source_secret_name in secret_env_mapping.items():
        value = secrets.get(source_secret_name)
        if value is None or value == "":
            raise MissingSecretEnvError(source_secret_name)
        resolved[container_var] = value
    return resolved


def build_container_environment(mcp_config: MCPConfig, extra_env: dict[str, str]) -> dict[str, str]:
    environment = {str(key): str(value) for key, value in mcp_config.env.items()}
    environment.update(extra_env)
    return environment


def format_container_command_for_log(command: list[str]) -> str:
    sanitized: list[str] = []
    redact_next_env = False
    for part in command:
        if redact_next_env:
            sanitized.append(_redact_env_assignment(part))
            redact_next_env = False
            continue
        sanitized.append(part)
        if part == "-e":
            redact_next_env = True
    return shlex.join(sanitized)


def build_runtime_container_command(
    mcp_config: MCPConfig,
    instance_config: MCPInstanceConfig,
    *,
    metadata_path: Path,
    code_path: Path,
    index_storage_path: Path,
    reset_database: bool,
    index_metadata: bool,
    index_code: bool,
    index_help: bool,
    restart_policy: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> list[str]:
    resolved_secret_env = resolve_secret_environment(mcp_config.secret_env, mcp_config.secrets)
    container_env = build_container_environment(
        mcp_config,
        {
            **resolved_secret_env,
            "RESET_DATABASE": _bool_to_env(reset_database),
            "RESET_CACHE": _bool_to_env(mcp_config.reset_cache),
            "USESSE": _bool_to_env(mcp_config.use_sse),
            "INDEX_METADATA": _bool_to_env(index_metadata),
            "INDEX_CODE": _bool_to_env(index_code),
            "INDEX_HELP": _bool_to_env(index_help),
        },
    )
    if extra_env:
        container_env.update(extra_env)

    command: list[str] = [
        "docker",
        "run",
        "-d",
        "--init",
        "--name",
        instance_config.container_name,
    ]

    if restart_policy:
        command.extend(["--restart", restart_policy])

    for key, value in container_env.items():
        command.extend(["-e", f"{key}={value}"])

    if mcp_config.use_gpu:
        command.extend(["--gpus", "all"])

    command.extend(
        [
            "-p",
            f"{instance_config.host_port}:{mcp_config.container_port}",
            "-v",
            f"{metadata_path}:/app/metadata",
            "-v",
            f"{code_path}:/app/code",
            "-v",
            f"{index_storage_path}:{mcp_config.index_container_path}",
            mcp_config.image,
        ]
    )
    return command


def build_build_container_command(
    mcp_config: MCPConfig,
    build_paths: BuildPaths,
    paths_config: PathsConfig,
    *,
    reset_database: bool,
    index_metadata: bool,
    index_code: bool,
    index_help: bool,
) -> list[str]:
    return build_runtime_container_command(
        mcp_config,
        mcp_config.build,
        metadata_path=build_paths.metadata,
        code_path=build_paths.code,
        index_storage_path=paths_config.index_storage_root / "build",
        reset_database=reset_database,
        index_metadata=index_metadata,
        index_code=index_code,
        index_help=index_help,
        restart_policy=None,
    )


def build_production_container_command(
    mcp_config: MCPConfig,
    paths_config: PathsConfig,
) -> list[str]:
    return build_runtime_container_command(
        mcp_config,
        mcp_config.production,
        metadata_path=paths_config.staging_root / "current" / "metadata",
        code_path=paths_config.staging_root / "current" / "code",
        index_storage_path=paths_config.index_storage_root / "current",
        reset_database=False,
        index_metadata=False,
        index_code=False,
        index_help=False,
        restart_policy="unless-stopped",
        extra_env={"REINDEX_INTERVAL_SEC": "0"},
    )


def start_production_container(
    mcp_config: MCPConfig,
    paths_config: PathsConfig,
    *,
    runner: DockerCommandRunner,
) -> ContainerStartResult:
    command = build_production_container_command(mcp_config, paths_config)
    logger.info(
        "Starting production container '%s' with flags: reset_database=%s index_metadata=%s index_code=%s index_help=%s reindex_interval_sec=%s",
        mcp_config.production.container_name,
        False,
        False,
        False,
        False,
        0,
    )
    logger.info("Production container command: %s", format_container_command_for_log(command))
    result = run_docker_command(
        command,
        runner=runner,
        error_code=ExitCode.PRODUCTION_SWITCH_FAILED,
        failure_message=f"Failed to start production container '{mcp_config.production.container_name}'.",
    )
    return ContainerStartResult(command=command, container_id=result.stdout.strip())


def start_build_container(
    mcp_config: MCPConfig,
    build_paths: BuildPaths,
    paths_config: PathsConfig,
    *,
    runner: DockerCommandRunner,
    reset_database: bool | None = None,
    seed_index_storage_from: Path | None = None,
    index_metadata: bool | None = None,
    index_code: bool | None = None,
    index_help: bool | None = None,
) -> BuildContainerStartResult:
    effective_reset_database = mcp_config.reset_database_on_build if reset_database is None else reset_database
    effective_index_metadata = mcp_config.index_metadata if index_metadata is None else index_metadata
    effective_index_code = mcp_config.index_code if index_code is None else index_code
    effective_index_help = mcp_config.index_help if index_help is None else index_help
    prepare_index_storage_build(paths_config.index_storage_root, seed_source=seed_index_storage_from)
    remove_container(
        mcp_config.build.container_name,
        runner=runner,
        error_code=ExitCode.BUILD_CONTAINER_FAILED,
    )
    command = build_build_container_command(
        mcp_config,
        build_paths,
        paths_config,
        reset_database=effective_reset_database,
        index_metadata=effective_index_metadata,
        index_code=effective_index_code,
        index_help=effective_index_help,
    )
    logger.info(
        "Starting build container '%s' with flags: reset_database=%s index_metadata=%s index_code=%s index_help=%s seed_index_storage_from=%s",
        mcp_config.build.container_name,
        effective_reset_database,
        effective_index_metadata,
        effective_index_code,
        effective_index_help,
        str(seed_index_storage_from) if seed_index_storage_from is not None else "<none>",
    )
    logger.info("Build container command: %s", format_container_command_for_log(command))
    result = run_docker_command(
        command,
        runner=runner,
        error_code=ExitCode.BUILD_CONTAINER_FAILED,
        failure_message=f"Failed to start build container '{mcp_config.build.container_name}'.",
    )
    return BuildContainerStartResult(command=command, container_id=result.stdout.strip())


def _bool_to_env(value: bool) -> str:
    return "true" if value else "false"


def _redact_env_assignment(assignment: str) -> str:
    if "=" not in assignment:
        return assignment
    key, _, value = assignment.partition("=")
    if _should_redact_env_key(key):
        return f"{key}=<redacted>"
    return assignment


def _should_redact_env_key(key: str) -> bool:
    normalized = key.upper()
    sensitive_markers = ("SECRET", "TOKEN", "PASSWORD", "API_KEY", "WEBHOOK", "LICENSE")
    return any(marker in normalized for marker in sensitive_markers)
