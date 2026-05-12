from __future__ import annotations

from pathlib import Path

import pytest

from mcp_project_updater.config import ParserConfig
from mcp_project_updater.constants import ExitCode
from mcp_project_updater.parser_runner import ParserExecutionError, ParserRunResult, build_parser_command, run_parser


def test_build_parser_command_adds_verbose_flag() -> None:
    command = build_parser_command(Path("tool.py"), Path("parser-config.json"), verbose=True)

    assert command == ["python", "tool.py", "--config", "parser-config.json", "--verbose"]


def test_run_parser_accepts_allowed_exit_code(tmp_path: Path) -> None:
    parser_config = ParserConfig(
        tool_path=tmp_path / "tool.py",
        encoding="utf-8",
        warnings_as_errors=False,
        build_xml_overrides=True,
        allowed_exit_codes=[0, 1],
    )

    result = run_parser(
        parser_config,
        tmp_path / "parser-config.json",
        verbose=False,
        working_directory=tmp_path,
        runner=lambda command, cwd: ParserRunResult(list(command), 1, "warn", ""),
    )

    assert result.returncode == 1


def test_run_parser_raises_for_disallowed_exit_code(tmp_path: Path) -> None:
    parser_config = ParserConfig(
        tool_path=tmp_path / "tool.py",
        encoding="utf-8",
        warnings_as_errors=False,
        build_xml_overrides=True,
        allowed_exit_codes=[0, 1],
    )

    with pytest.raises(ParserExecutionError) as exc:
        run_parser(
            parser_config,
            tmp_path / "parser-config.json",
            verbose=False,
            working_directory=tmp_path,
            runner=lambda command, cwd: ParserRunResult(list(command), 2, "", "boom"),
        )

    assert exc.value.exit_code == ExitCode.PARSER_FAILED
