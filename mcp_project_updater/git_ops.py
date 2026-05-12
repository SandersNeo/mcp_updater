from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .constants import ExitCode
from .errors import UpdaterError


class GitOperationError(UpdaterError):
    pass


@dataclass(slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str], Path], CommandResult]


def default_command_runner(command: Sequence[str], cwd: Path) -> CommandResult:
    completed = subprocess.run(
        list(command),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


@dataclass(slots=True)
class RepoValidationResult:
    inside_work_tree: bool
    tracked_changes: list[str]
    untracked_changes: list[str]


def validate_repo(repo_path: Path, runner: CommandRunner = default_command_runner) -> RepoValidationResult:
    inside = _run_git(repo_path, ["git", "rev-parse", "--is-inside-work-tree"], runner, ExitCode.GIT_REPOSITORY_NOT_FOUND)
    if inside.stdout.strip().lower() != "true":
        raise GitOperationError(f"Path is not a Git work tree: {repo_path}", ExitCode.GIT_REPOSITORY_NOT_FOUND)

    status = _run_git(repo_path, ["git", "status", "--porcelain"], runner, ExitCode.GIT_PULL_FAILED)
    tracked_changes: list[str] = []
    untracked_changes: list[str] = []

    for line in [item for item in status.stdout.splitlines() if item.strip()]:
        if line.startswith("??"):
            untracked_changes.append(line)
        else:
            tracked_changes.append(line)

    if tracked_changes:
        raise GitOperationError(
            f"Tracked Git changes detected in repository: {repo_path}",
            ExitCode.GIT_TRACKED_CHANGES,
        )

    return RepoValidationResult(
        inside_work_tree=True,
        tracked_changes=tracked_changes,
        untracked_changes=untracked_changes,
    )


def determine_target_commit(
    repo_path: Path,
    branch: str,
    remote: str,
    *,
    no_git_pull: bool,
    runner: CommandRunner = default_command_runner,
) -> str:
    if no_git_pull:
        result = _run_git(repo_path, ["git", "rev-parse", "HEAD"], runner, ExitCode.GIT_PULL_FAILED)
        return result.stdout.strip()

    _run_git(repo_path, ["git", "fetch", remote, branch], runner, ExitCode.GIT_PULL_FAILED)
    _run_git(repo_path, ["git", "checkout", branch], runner, ExitCode.GIT_PULL_FAILED)
    _run_git(repo_path, ["git", "pull", "--ff-only", remote, branch], runner, ExitCode.GIT_PULL_FAILED)
    result = _run_git(repo_path, ["git", "rev-parse", f"{remote}/{branch}"], runner, ExitCode.GIT_PULL_FAILED)
    return result.stdout.strip()


def _run_git(repo_path: Path, command: Sequence[str], runner: CommandRunner, error_code: int) -> CommandResult:
    result = runner(command, repo_path)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        details = stderr or stdout or "Git command failed."
        raise GitOperationError(details, error_code)
    return result
