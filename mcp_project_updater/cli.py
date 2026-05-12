from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .config import ProjectConfig, load_project_config
from .constants import ExitCode
from .docker_ops import default_docker_runner, ensure_docker_available, write_container_logs
from .git_ops import determine_target_commit, validate_repo
from .lock import LockManager
from .mcp_container import start_build_container
from .parser_runner import run_parser
from .report_validator import validate_report
from .smoke_infrastructure import InfrastructureSmokeContext, run_infrastructure_smoke_test
from .smoke_tool import run_tool_smoke_test
from .source_detector import SourceDetectionResult, detect_sources
from .staging import generate_parser_config, prepare_build_code_directory, prepare_build_staging, write_parser_config
from .state import StateSnapshot, StateStore
from .errors import UpdaterError, WorkflowNotImplementedError
from .logging_setup import setup_logging


@dataclass(slots=True)
class CliOptions:
    config_path: Path
    force: bool
    no_git_pull: bool
    rollback: bool
    verbose: bool
    dry_run: bool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Update MCP project index from a Git repository.")
    parser.add_argument("--config", required=True, help="Path to project.json")
    parser.add_argument("--force", action="store_true", help="Reindex the current commit even if unchanged.")
    parser.add_argument("--no-git-pull", action="store_true", help="Use current HEAD without git fetch/pull.")
    parser.add_argument("--rollback", action="store_true", help="Run manual rollback current <-> previous.")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging.")
    parser.add_argument("--dry-run", action="store_true", help="Validate config and show planned actions.")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> CliOptions:
    namespace = build_parser().parse_args(argv)
    return CliOptions(
        config_path=Path(namespace.config),
        force=namespace.force,
        no_git_pull=namespace.no_git_pull,
        rollback=namespace.rollback,
        verbose=namespace.verbose,
        dry_run=namespace.dry_run,
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        options = parse_args(argv)
        config = load_project_config(options.config_path)
        log_path = setup_logging(config.paths.logs_root, options.verbose)
        logger = logging.getLogger(__name__)
        logger.info("Loaded config for project '%s'.", config.project)
        logger.info("Log file: %s", log_path)
        return run_update(config, options, log_path=log_path)
    except UpdaterError as exc:
        if logging.getLogger().handlers:
            logging.getLogger(__name__).error(str(exc))
        else:
            print(str(exc))
        return int(exc.exit_code)


def run_update(config: ProjectConfig, options: CliOptions, *, log_path: Path) -> int:
    logger = logging.getLogger(__name__)
    state_store = StateStore(config.paths.state_root)
    lock_manager = LockManager(
        state_store.lock_path,
        config.project,
        "rollback" if options.rollback else ("dry-run" if options.dry_run else "update"),
    )

    lock_manager.acquire()
    logger.info("Lock acquired: %s", state_store.lock_path)

    try:
        if options.rollback:
            raise WorkflowNotImplementedError("Manual rollback workflow is not implemented yet.")

        repo_validation = validate_repo(config.repo.path)
        if repo_validation.untracked_changes:
            logger.warning("Untracked Git changes detected but ignored for MVP: %s", repo_validation.untracked_changes)

        target_commit = determine_target_commit(
            config.repo.path,
            config.repo.branch,
            config.repo.remote,
            no_git_pull=options.no_git_pull,
        )
        state_snapshot = state_store.read_snapshot()
        source_result = detect_sources(
            config.repo.path,
            config.sources.main_config_path,
            config.sources.main_config_required,
            config.sources.extension_path,
            config.sources.extension_required,
        )

        logger.info("Target commit: %s", target_commit)
        logger.info("Last indexed commit: %s", state_snapshot.last_indexed_commit or "<none>")
        logger.info(
            "Detected sources: main=%s extension=%s",
            source_result.main_exists,
            source_result.extension_exists,
        )

        if target_commit == state_snapshot.last_indexed_commit and not options.force:
            logger.info("No changes detected. Update is skipped.")
            return ExitCode.SUCCESS

        if options.dry_run:
            _log_dry_run_summary(logger, config, options, state_snapshot, target_commit, source_result)
            return ExitCode.SUCCESS

        build_paths = prepare_build_staging(config.paths.staging_root, config.project)
        parser_config_payload = generate_parser_config(config, build_paths)
        parser_config_path = write_parser_config(build_paths, parser_config_payload)
        parser_result = run_parser(
            config.parser,
            parser_config_path,
            verbose=options.verbose,
            working_directory=config.repo.path,
        )
        logger.info("Parser exit code: %s", parser_result.returncode)

        report_result = validate_report(
            build_paths.report_path,
            config.smoke_test.report_validation,
            build_paths.diagnostics,
        )
        logger.info("Validated report: %s (%s bytes)", report_result.report_path, report_result.report_size)

        prepare_build_code_directory(build_paths, source_result)
        logger.info("Prepared build code directory: %s", build_paths.code)

        docker_version = ensure_docker_available()
        logger.info("Docker available: %s", docker_version)

        build_container_result = start_build_container(
            config.mcp,
            build_paths,
            config.paths,
            runner=default_docker_runner,
        )
        logger.info("Started build container: %s", config.mcp.build.container_name)
        logger.debug("Build container command: %s", build_container_result.command)

        smoke_result = run_infrastructure_smoke_test(
            config.smoke_test.infrastructure,
            InfrastructureSmokeContext(
                container_name=config.mcp.build.container_name,
                host_port=config.mcp.build.host_port,
                url=config.mcp.build.url,
                chroma_path=config.paths.chroma_root / "build",
            ),
            runner=default_docker_runner,
        )
        logger.info("Infrastructure smoke-test passed with HTTP status %s", smoke_result.http_status_code)

        if config.smoke_test.tool_smoke_test.enabled:
            tool_smoke_result = run_tool_smoke_test(
                config,
                config.smoke_test.tool_smoke_test,
                working_directory=config.repo.path,
                url=config.mcp.build.url,
            )
            logger.info("Tool smoke-test passed: %s", tool_smoke_result.stdout.strip() or "<no output>")
        else:
            logger.warning("MCP tool smoke-test skipped")

        build_log_path = _derive_related_log_path(log_path, "mcp-build")
        write_container_logs(
            config.mcp.build.container_name,
            build_log_path,
            runner=default_docker_runner,
        )
        logger.info("Saved build container logs: %s", build_log_path)

        logger.warning("Phase 4 workflow completed. Tool smoke-test and switch stages are not implemented yet.")
        return ExitCode.SUCCESS_WITH_WARNINGS
    finally:
        lock_manager.release()
        logger.info("Lock released: %s", state_store.lock_path)


def _log_dry_run_summary(
    logger: logging.Logger,
    config: ProjectConfig,
    options: CliOptions,
    state_snapshot: StateSnapshot,
    target_commit: str,
    source_result: SourceDetectionResult,
) -> None:
    logger.info("Dry-run mode enabled.")
    logger.info(
        "Options: force=%s no_git_pull=%s rollback=%s verbose=%s",
        options.force,
        options.no_git_pull,
        options.rollback,
        options.verbose,
    )
    logger.info("Repository path: %s", config.repo.path)
    logger.info("Branch: %s", config.repo.branch)
    logger.info("Target commit: %s", target_commit)
    logger.info("Last indexed commit: %s", state_snapshot.last_indexed_commit or "<none>")
    logger.info("Current commit: %s", state_snapshot.current_commit or "<none>")
    logger.info("Previous commit: %s", state_snapshot.previous_commit or "<none>")
    logger.info("Main source exists: %s", source_result.main_exists)
    logger.info("Extension source exists: %s", source_result.extension_exists)
    logger.info("Build URL: %s", config.mcp.build.url)
    logger.info("Production URL: %s", config.mcp.production.url)
    logger.info("Smoke profile: %s", config.smoke_test.profile)
    logger.info("Tool smoke-test enabled: %s", config.smoke_test.tool_smoke_test.enabled)


def _derive_related_log_path(update_log_path: Path, suffix: str) -> Path:
    file_name = update_log_path.name
    if file_name.endswith("-update.log"):
        return update_log_path.with_name(file_name.replace("-update.log", f"-{suffix}.log"))
    return update_log_path.with_name(f"{update_log_path.stem}-{suffix}.log")
