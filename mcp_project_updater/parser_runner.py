from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .config import ParserConfig
from .constants import ExitCode
from .errors import UpdaterError


class ParserExecutionError(UpdaterError):
    pass


@dataclass(slots=True)
class ParserRunResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


ProcessRunner = Callable[[Sequence[str], Path], ParserRunResult]


def default_process_runner(command: Sequence[str], cwd: Path) -> ParserRunResult:
    completed = subprocess.run(
        list(command),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return ParserRunResult(
        command=list(command),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def build_parser_command(parser_tool_path: Path, parser_config_path: Path, *, verbose: bool) -> list[str]:
    command = ["python", str(parser_tool_path), "--config", str(parser_config_path)]
    if verbose:
        command.append("--verbose")
    return command


def run_parser(
    parser_config: ParserConfig,
    parser_config_path: Path,
    *,
    verbose: bool,
    working_directory: Path,
    runner: ProcessRunner = default_process_runner,
) -> ParserRunResult:
    command = build_parser_command(parser_config.tool_path, parser_config_path, verbose=verbose)
    result = runner(command, working_directory)
    if result.returncode not in parser_config.allowed_exit_codes:
        details = result.stderr.strip() or result.stdout.strip() or "Parser failed."
        raise ParserExecutionError(details, ExitCode.PARSER_FAILED)
    return result
