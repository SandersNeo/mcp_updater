from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _run_wrapper(tmp_path: Path, *, verbose: bool) -> subprocess.CompletedProcess[str]:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is not available")

    script_source = Path(__file__).resolve().parents[1] / "update-mcp-project.ps1"
    script_path = tmp_path / "update-mcp-project.ps1"
    script_path.write_text(script_source.read_text(encoding="utf-8"), encoding="utf-8")

    python_bin = tmp_path / "bin"
    python_bin.mkdir()
    args_file = tmp_path / "python-args.txt"
    (python_bin / "python.cmd").write_text(
        "@echo off\r\n"
        "echo %* > \"%PYTHON_ARGS_FILE%\"\r\n"
        "exit /b 0\r\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PATH"] = f"{python_bin}{os.pathsep}{env['PATH']}"
    env["PYTHON_ARGS_FILE"] = str(args_file)

    command = [
        powershell,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-Config",
        r"C:\mcp-updater-data\orders\project.json",
    ]
    if verbose:
        command.append("-Verbose")

    result = subprocess.run(
        command,
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    result.args_file = args_file  # type: ignore[attr-defined]
    return result


def test_update_wrapper_accepts_verbose_common_parameter(tmp_path: Path) -> None:
    result = _run_wrapper(tmp_path, verbose=True)

    assert result.returncode == 0
    assert "defined multiple times" not in result.stderr
    assert "--verbose" in result.args_file.read_text(encoding="utf-8")  # type: ignore[attr-defined]


def test_update_wrapper_omits_verbose_when_not_requested(tmp_path: Path) -> None:
    result = _run_wrapper(tmp_path, verbose=False)

    assert result.returncode == 0
    assert "--verbose" not in result.args_file.read_text(encoding="utf-8")  # type: ignore[attr-defined]
