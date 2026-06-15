from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import ProjectConfig
from .constants import ExitCode
from .docker_ops import DockerCommandRunner, remove_container, write_container_logs
from .errors import UpdaterError
from .mcp_container import start_production_container
from .state import StateStore


class RollbackError(UpdaterError):
    def __init__(self, message: str, exit_code: int = ExitCode.ROLLBACK_FAILED) -> None:
        super().__init__(message, exit_code)


def perform_automatic_rollback(
    config: ProjectConfig,
    state_store: StateStore,
    production_log_path: Path,
    *,
    docker_runner: DockerCommandRunner,
    production_smoke_runner: Callable[[ProjectConfig], object],
    timestamp_provider: Callable[[], str] | None = None,
) -> None:
    timestamp_provider = timestamp_provider or (lambda: datetime.now().strftime("%Y%m%d-%H%M%S"))
    staging_root = config.paths.staging_root
    index_storage_root = config.paths.index_storage_root

    current_staging = staging_root / "current"
    previous_staging = staging_root / "previous"
    current_index_storage = index_storage_root / "current"
    previous_index_storage = index_storage_root / "previous"

    if not previous_staging.exists() or not previous_index_storage.exists():
        raise RollbackError("Automatic rollback is impossible: previous artifacts are missing.")

    remove_container(config.mcp.production.container_name, runner=docker_runner, error_code=ExitCode.ROLLBACK_FAILED)

    if config.rollback.preserve_failed_index:
        failed_suffix = timestamp_provider()
        _move_if_exists(current_staging, staging_root / f"failed-{failed_suffix}")
        _move_if_exists(current_index_storage, index_storage_root / f"failed-{failed_suffix}")
    else:
        _remove_if_exists(current_staging)
        _remove_if_exists(current_index_storage)

    shutil.move(str(previous_staging), str(current_staging))
    shutil.move(str(previous_index_storage), str(current_index_storage))

    start_production_container(config.mcp, config.paths, runner=docker_runner)
    try:
        production_smoke_runner(config)
    except Exception as exc:
        write_container_logs(config.mcp.production.container_name, production_log_path, runner=docker_runner)
        raise RollbackError(f"Automatic rollback failed during production smoke-test: {exc}") from exc

    write_container_logs(config.mcp.production.container_name, production_log_path, runner=docker_runner)


def perform_manual_rollback(
    config: ProjectConfig,
    state_store: StateStore,
    production_log_path: Path,
    *,
    docker_runner: DockerCommandRunner,
    production_smoke_runner: Callable[[ProjectConfig], object],
) -> None:
    staging_root = config.paths.staging_root
    index_storage_root = config.paths.index_storage_root

    current_staging = staging_root / "current"
    previous_staging = staging_root / "previous"
    current_index_storage = index_storage_root / "current"
    previous_index_storage = index_storage_root / "previous"

    if (
        not current_staging.exists()
        or not previous_staging.exists()
        or not current_index_storage.exists()
        or not previous_index_storage.exists()
    ):
        raise RollbackError("Manual rollback cannot proceed: current/previous artifacts are missing.", ExitCode.INVALID_STATE)

    current_commit = state_store.read_current_commit()
    previous_commit = state_store.read_previous_commit()
    if not current_commit or not previous_commit:
        raise RollbackError("Manual rollback cannot determine current/previous commits from state.", ExitCode.INVALID_STATE)

    remove_container(config.mcp.production.container_name, runner=docker_runner, error_code=ExitCode.ROLLBACK_FAILED)

    temp_staging = staging_root / "_rollback_temp_current"
    temp_index_storage = index_storage_root / "_rollback_temp_current"
    _remove_if_exists(temp_staging)
    _remove_if_exists(temp_index_storage)

    shutil.move(str(current_staging), str(temp_staging))
    shutil.move(str(previous_staging), str(current_staging))
    shutil.move(str(temp_staging), str(previous_staging))

    shutil.move(str(current_index_storage), str(temp_index_storage))
    shutil.move(str(previous_index_storage), str(current_index_storage))
    shutil.move(str(temp_index_storage), str(previous_index_storage))

    start_production_container(config.mcp, config.paths, runner=docker_runner)
    try:
        production_smoke_runner(config)
    except Exception as exc:
        write_container_logs(config.mcp.production.container_name, production_log_path, runner=docker_runner)
        raise RollbackError(f"Manual rollback failed during production smoke-test: {exc}") from exc

    write_container_logs(config.mcp.production.container_name, production_log_path, runner=docker_runner)

    state_store.write_current_commit(previous_commit)
    state_store.write_previous_commit(current_commit)


def _move_if_exists(source: Path, destination: Path) -> None:
    if source.exists():
        _remove_if_exists(destination)
        shutil.move(str(source), str(destination))


def _remove_if_exists(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()
