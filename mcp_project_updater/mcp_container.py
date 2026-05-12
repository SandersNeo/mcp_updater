from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import MCPConfig, PathsConfig
from .constants import ExitCode
from .docker_ops import DockerCommandResult, DockerCommandRunner, remove_container, run_docker_command
from .errors import UpdaterError
from .staging import BuildPaths


class MissingSecretEnvError(UpdaterError):
    def __init__(self, env_name: str) -> None:
        super().__init__(f"Required secret environment variable is missing: {env_name}", ExitCode.MISSING_REQUIRED_SECRET)


@dataclass(slots=True)
class BuildContainerStartResult:
    command: list[str]
    container_id: str


def prepare_chroma_build(chroma_root: Path) -> Path:
    build_path = chroma_root / "build"
    if build_path.exists():
        shutil.rmtree(build_path)
    build_path.mkdir(parents=True, exist_ok=True)
    return build_path


def resolve_secret_environment(secret_env_mapping: dict[str, str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for container_var, source_env_name in secret_env_mapping.items():
        value = os.getenv(source_env_name)
        if value is None or value == "":
            raise MissingSecretEnvError(source_env_name)
        resolved[container_var] = value
    return resolved


def build_container_environment(mcp_config: MCPConfig, extra_env: dict[str, str]) -> dict[str, str]:
    environment = {str(key): str(value) for key, value in mcp_config.env.items()}
    environment.update(extra_env)
    return environment


def build_build_container_command(
    mcp_config: MCPConfig,
    build_paths: BuildPaths,
    paths_config: PathsConfig,
) -> list[str]:
    chroma_build_path = paths_config.chroma_root / "build"
    resolved_secret_env = resolve_secret_environment(mcp_config.secret_env)
    container_env = build_container_environment(
        mcp_config,
        {
            **resolved_secret_env,
            "RESET_DATABASE": _bool_to_env(True),
            "RESET_CACHE": _bool_to_env(mcp_config.reset_cache),
            "USESSE": _bool_to_env(mcp_config.use_sse),
        },
    )

    command: list[str] = [
        "docker",
        "run",
        "-d",
        "--name",
        mcp_config.build.container_name,
    ]

    for key, value in container_env.items():
        command.extend(["-e", f"{key}={value}"])

    if mcp_config.use_gpu:
        command.extend(["--gpus", "all"])

    command.extend(
        [
            "-p",
            f"{mcp_config.build.host_port}:{mcp_config.container_port}",
            "-v",
            f"{build_paths.metadata}:/app/metadata",
            "-v",
            f"{build_paths.code}:/app/code",
            "-v",
            f"{chroma_build_path}:/app/chroma_db",
            mcp_config.image,
        ]
    )
    return command


def start_build_container(
    mcp_config: MCPConfig,
    build_paths: BuildPaths,
    paths_config: PathsConfig,
    *,
    runner: DockerCommandRunner,
) -> BuildContainerStartResult:
    prepare_chroma_build(paths_config.chroma_root)
    remove_container(
        mcp_config.build.container_name,
        runner=runner,
        error_code=ExitCode.BUILD_CONTAINER_FAILED,
    )
    command = build_build_container_command(mcp_config, build_paths, paths_config)
    result = run_docker_command(
        command,
        runner=runner,
        error_code=ExitCode.BUILD_CONTAINER_FAILED,
        failure_message=f"Failed to start build container '{mcp_config.build.container_name}'.",
    )
    return BuildContainerStartResult(command=command, container_id=result.stdout.strip())


def _bool_to_env(value: bool) -> str:
    return "true" if value else "false"
