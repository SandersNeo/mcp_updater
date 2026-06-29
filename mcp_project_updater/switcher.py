from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .config import ProjectConfig
from .constants import ExitCode
from .docker_ops import DockerCommandRunner, remove_container, stop_container, write_container_logs
from .errors import UpdaterError
from .mcp_container import start_production_container
from .smoke_infrastructure import InfrastructureSmokeContext, InfrastructureSmokeResult, run_infrastructure_smoke_test
from .smoke_tool import ToolSmokeRunResult, default_process_runner as default_tool_smoke_runner, run_tool_smoke_test
from .state import StateStore


class ProductionSmokeTestFailed(UpdaterError):
    def __init__(self, message: str = "Production smoke-test failed.", *, rollback_attempted: bool = True) -> None:
        super().__init__(message, ExitCode.PRODUCTION_SMOKE_FAILED)
        self.rollback_attempted = rollback_attempted


class ProductionSwitchError(UpdaterError):
    def __init__(self, message: str) -> None:
        super().__init__(message, ExitCode.PRODUCTION_SWITCH_FAILED)


@dataclass(slots=True)
class ProductionSmokeTestResult:
    infrastructure: InfrastructureSmokeResult
    tool_smoke: ToolSmokeRunResult | None


@dataclass(slots=True)
class SwitchResult:
    target_commit: str
    production_log_path: Path


@dataclass(frozen=True, slots=True)
class _WslUncPath:
    distro: str
    linux_path: str


logger = logging.getLogger(__name__)


def run_production_smoke_test(
    config: ProjectConfig,
    *,
    docker_runner: DockerCommandRunner,
    tool_smoke_runner=default_tool_smoke_runner,
) -> ProductionSmokeTestResult:
    infrastructure_result = run_infrastructure_smoke_test(
        config.smoke_test.infrastructure,
        InfrastructureSmokeContext(
            container_name=config.mcp.production.container_name,
            host_port=config.mcp.production.host_port,
            url=config.mcp.production.url,
            index_storage_path=config.paths.index_storage_root / "current",
        ),
        runner=docker_runner,
    )

    tool_result = None
    if config.smoke_test.tool_smoke_test.enabled:
        tool_result = run_tool_smoke_test(
            config,
            config.smoke_test.tool_smoke_test,
            working_directory=config.repo.path,
            url=config.mcp.production.url,
            runner=tool_smoke_runner,
        )
    return ProductionSmokeTestResult(infrastructure=infrastructure_result, tool_smoke=tool_result)


def perform_switch(
    config: ProjectConfig,
    state_store: StateStore,
    target_commit: str,
    production_log_path: Path,
    *,
    docker_runner: DockerCommandRunner,
    production_smoke_runner: Callable[[ProjectConfig], ProductionSmokeTestResult] | None = None,
    rollback_runner: Callable[..., None] | None = None,
    storage_migration: bool = False,
) -> SwitchResult:
    staging_root = config.paths.staging_root
    index_storage_root = config.paths.index_storage_root
    build_staging = staging_root / "build"
    current_staging = staging_root / "current"
    previous_staging = staging_root / "previous"
    build_index_storage = index_storage_root / "build"
    current_index_storage = index_storage_root / "current"
    previous_index_storage = index_storage_root / "previous"

    if not build_staging.exists() or not build_index_storage.exists():
        raise ProductionSwitchError("Build artifacts are missing; cannot switch to current.")

    old_current_commit = state_store.read_current_commit()

    remove_container(config.mcp.production.container_name, runner=docker_runner, error_code=ExitCode.PRODUCTION_SWITCH_FAILED)
    _remove_build_container_best_effort(config, docker_runner)

    _remove_if_exists(previous_staging, allowed_root=staging_root)
    _remove_if_exists(previous_index_storage, allowed_root=index_storage_root)

    if current_staging.exists():
        shutil.move(str(current_staging), str(previous_staging))
    if current_index_storage.exists():
        shutil.move(str(current_index_storage), str(previous_index_storage))

    shutil.move(str(build_staging), str(current_staging))
    shutil.move(str(build_index_storage), str(current_index_storage))

    start_production_container(config.mcp, config.paths, runner=docker_runner)

    smoke_runner = production_smoke_runner or (lambda current_config: run_production_smoke_test(current_config, docker_runner=docker_runner))
    try:
        smoke_runner(config)
    except Exception as exc:
        write_container_logs(config.mcp.production.container_name, production_log_path, runner=docker_runner)
        if storage_migration:
            try:
                stop_container(
                    config.mcp.production.container_name,
                    runner=docker_runner,
                    error_code=ExitCode.PRODUCTION_SMOKE_FAILED,
                )
            except UpdaterError as stop_exc:
                logger.warning(
                    "Failed to stop production container '%s' after storage migration smoke failure: %s",
                    config.mcp.production.container_name,
                    stop_exc,
                )
            raise ProductionSmokeTestFailed(
                "Storage migration production smoke-test failed. "
                "Automatic rollback is disabled for storage migration; recover manually from the old deployment backup. "
                f"Original error: {exc}",
                rollback_attempted=False,
            ) from exc
        if rollback_runner is None:
            from .rollback import perform_automatic_rollback

            rollback_runner = perform_automatic_rollback
        rollback_runner(
            config,
            state_store,
            production_log_path,
            docker_runner=docker_runner,
            production_smoke_runner=smoke_runner,
        )
        raise ProductionSmokeTestFailed(str(exc), rollback_attempted=True) from exc

    write_container_logs(config.mcp.production.container_name, production_log_path, runner=docker_runner)

    if old_current_commit:
        state_store.write_previous_commit(old_current_commit)
    else:
        state_store.clear_previous_commit()
    state_store.write_current_commit(target_commit)
    state_store.write_last_indexed_commit(target_commit)
    return SwitchResult(target_commit=target_commit, production_log_path=production_log_path)


def _remove_if_exists(
    path: Path,
    *,
    allowed_root: Path,
    process_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    _assert_cleanup_target_inside_root(path, allowed_root=allowed_root)
    wsl_path = _parse_wsl_unc_path(path)
    if wsl_path is not None:
        _remove_wsl_unc_path(path, wsl_path, process_runner=process_runner)
        return

    try:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    except OSError as exc:
        raise ProductionSwitchError(f"Failed to remove switch artifact '{path}': {exc}") from exc


def _assert_cleanup_target_inside_root(path: Path, *, allowed_root: Path) -> None:
    path_text = _normalize_path_for_guard(path)
    root_text = _normalize_path_for_guard(allowed_root)
    if path_text == root_text:
        raise ProductionSwitchError(f"Refusing to remove cleanup root itself: {path}")
    if not path_text.startswith(f"{root_text}\\"):
        raise ProductionSwitchError(f"Refusing to remove path outside cleanup root: {path}")


def _normalize_path_for_guard(path: Path) -> str:
    return str(path).replace("/", "\\").rstrip("\\").casefold()


def _parse_wsl_unc_path(path: Path) -> _WslUncPath | None:
    path_text = str(path).replace("/", "\\")
    for prefix in ("\\\\wsl.localhost\\", "\\\\wsl$\\"):
        if path_text.casefold().startswith(prefix.casefold()):
            rest = path_text[len(prefix) :].strip("\\")
            parts = [part for part in rest.split("\\") if part]
            if len(parts) < 2:
                raise ProductionSwitchError(f"Invalid WSL UNC cleanup path: {path}")
            return _WslUncPath(distro=parts[0], linux_path="/" + "/".join(parts[1:]))
    return None


def _remove_wsl_unc_path(
    original_path: Path,
    wsl_path: _WslUncPath,
    *,
    process_runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    command: Sequence[str] = (
        "wsl.exe",
        "-d",
        wsl_path.distro,
        "--",
        "rm",
        "-rf",
        "--",
        wsl_path.linux_path,
    )
    try:
        result = process_runner(
            list(command),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise ProductionSwitchError(f"Failed to run WSL cleanup for '{original_path}': {exc}") from exc
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        message = f"Failed to remove WSL switch artifact '{original_path}' with exit code {result.returncode}."
        if details:
            message = f"{message} {details}"
        raise ProductionSwitchError(message)


def _remove_build_container_best_effort(config: ProjectConfig, docker_runner: DockerCommandRunner) -> None:
    try:
        remove_container(config.mcp.build.container_name, runner=docker_runner, error_code=ExitCode.PRODUCTION_SWITCH_FAILED)
    except UpdaterError as exc:
        logger.warning(
            "Failed to remove build container '%s' before production switch; continuing: %s",
            config.mcp.build.container_name,
            exc,
        )
