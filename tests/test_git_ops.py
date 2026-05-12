from __future__ import annotations

import pytest

from mcp_project_updater.constants import ExitCode
from mcp_project_updater.git_ops import CommandResult, GitOperationError, determine_target_commit, validate_repo


def test_validate_repo_without_changes() -> None:
    calls = []

    def runner(command, cwd):
        calls.append(command)
        if command[2] == "--is-inside-work-tree":
            return CommandResult(0, "true\n", "")
        return CommandResult(0, "", "")

    result = validate_repo(cwd := __import__("pathlib").Path("."), runner)

    assert result.inside_work_tree is True
    assert result.tracked_changes == []
    assert result.untracked_changes == []
    assert len(calls) == 2


def test_validate_repo_with_tracked_changes_raises() -> None:
    def runner(command, cwd):
        if command[2] == "--is-inside-work-tree":
            return CommandResult(0, "true\n", "")
        return CommandResult(0, " M tracked.txt\n", "")

    with pytest.raises(GitOperationError) as exc:
        validate_repo(__import__("pathlib").Path("."), runner)

    assert exc.value.exit_code == ExitCode.GIT_TRACKED_CHANGES


def test_validate_repo_collects_untracked_changes() -> None:
    def runner(command, cwd):
        if command[2] == "--is-inside-work-tree":
            return CommandResult(0, "true\n", "")
        return CommandResult(0, "?? new.txt\n", "")

    result = validate_repo(__import__("pathlib").Path("."), runner)

    assert result.untracked_changes == ["?? new.txt"]


def test_determine_target_commit_with_no_git_pull() -> None:
    calls = []

    def runner(command, cwd):
        calls.append(command)
        return CommandResult(0, "abc123\n", "")

    commit = determine_target_commit(
        __import__("pathlib").Path("."),
        "master",
        "origin",
        no_git_pull=True,
        runner=runner,
    )

    assert commit == "abc123"
    assert calls == [["git", "rev-parse", "HEAD"]]


def test_determine_target_commit_with_git_pull_flow() -> None:
    calls = []

    def runner(command, cwd):
        calls.append(command)
        if command[:2] == ["git", "rev-parse"]:
            return CommandResult(0, "def456\n", "")
        return CommandResult(0, "", "")

    commit = determine_target_commit(
        __import__("pathlib").Path("."),
        "master",
        "origin",
        no_git_pull=False,
        runner=runner,
    )

    assert commit == "def456"
    assert calls == [
        ["git", "fetch", "origin", "master"],
        ["git", "checkout", "master"],
        ["git", "pull", "--ff-only", "origin", "master"],
        ["git", "rev-parse", "origin/master"],
    ]
