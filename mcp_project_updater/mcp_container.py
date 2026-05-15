from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import MCPConfig, MCPInstanceConfig, PathsConfig
from .constants import ExitCode
from .docker_ops import DockerCommandResult, DockerCommandRunner, remove_container, run_docker_command
from .errors import UpdaterError
from .staging import BuildPaths


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


def prepare_chroma_build(chroma_root: Path, *, seed_source: Path | None = None) -> Path:
    build_path = chroma_root / "build"
    if build_path.exists():
        shutil.rmtree(build_path)
    if seed_source is not None and seed_source.exists():
        shutil.copytree(seed_source, build_path)
    else:
        build_path.mkdir(parents=True, exist_ok=True)
    return build_path


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


def build_runtime_container_command(
    mcp_config: MCPConfig,
    instance_config: MCPInstanceConfig,
    *,
    metadata_path: Path,
    code_path: Path,
    chroma_path: Path,
    reset_database: bool,
    index_metadata: bool,
    index_code: bool,
    index_help: bool,
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

    command: list[str] = [
        "docker",
        "run",
        "-d",
        "--name",
        instance_config.container_name,
    ]

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
            f"{chroma_path}:/app/chroma_db",
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
        chroma_path=paths_config.chroma_root / "build",
        reset_database=reset_database,
        index_metadata=index_metadata,
        index_code=index_code,
        index_help=index_help,
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
        chroma_path=paths_config.chroma_root / "current",
        reset_database=False,
        index_metadata=mcp_config.index_metadata,
        index_code=mcp_config.index_code,
        index_help=mcp_config.index_help,
    )


def start_production_container(
    mcp_config: MCPConfig,
    paths_config: PathsConfig,
    *,
    runner: DockerCommandRunner,
) -> ContainerStartResult:
    command = build_production_container_command(mcp_config, paths_config)
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
    seed_chroma_from: Path | None = None,
    index_metadata: bool | None = None,
    index_code: bool | None = None,
    index_help: bool | None = None,
) -> BuildContainerStartResult:
    prepare_chroma_build(paths_config.chroma_root, seed_source=seed_chroma_from)
    remove_container(
        mcp_config.build.container_name,
        runner=runner,
        error_code=ExitCode.BUILD_CONTAINER_FAILED,
    )
    command = build_build_container_command(
        mcp_config,
        build_paths,
        paths_config,
        reset_database=mcp_config.reset_database_on_build if reset_database is None else reset_database,
        index_metadata=mcp_config.index_metadata if index_metadata is None else index_metadata,
        index_code=mcp_config.index_code if index_code is None else index_code,
        index_help=mcp_config.index_help if index_help is None else index_help,
    )
    result = run_docker_command(
        command,
        runner=runner,
        error_code=ExitCode.BUILD_CONTAINER_FAILED,
        failure_message=f"Failed to start build container '{mcp_config.build.container_name}'.",
    )
    return BuildContainerStartResult(command=command, container_id=result.stdout.strip())


def _bool_to_env(value: bool) -> str:
    return "true" if value else "false"
