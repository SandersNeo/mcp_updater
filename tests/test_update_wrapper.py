from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _prepare_fake_python(tmp_path: Path) -> tuple[dict[str, str], Path]:
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
    return env, args_file


def _write_promote_log(path: Path, *, commit: str, fingerprint: str, report_hash: str) -> None:
    path.write_text(
        "\n".join(
            [
                f"Target commit: {commit}",
                f"Source fingerprint: {fingerprint}",
                f"Report hash: {report_hash}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _run_wrapper(
    tmp_path: Path,
    *,
    verbose: bool,
    repair_metadata_index: bool = False,
) -> subprocess.CompletedProcess[str]:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is not available")

    script_source = Path(__file__).resolve().parents[1] / "update-mcp-project.ps1"
    script_path = tmp_path / "update-mcp-project.ps1"
    script_path.write_text(script_source.read_text(encoding="utf-8"), encoding="utf-8")

    env, args_file = _prepare_fake_python(tmp_path)

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
    if repair_metadata_index:
        command.append("-RepairMetadataIndex")

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


def test_update_wrapper_accepts_repair_metadata_index(tmp_path: Path) -> None:
    result = _run_wrapper(tmp_path, verbose=False, repair_metadata_index=True)

    assert result.returncode == 0
    assert "--repair-metadata-index" in result.args_file.read_text(encoding="utf-8")  # type: ignore[attr-defined]


def test_promote_wrapper_defaults_project_root_to_config_directory(tmp_path: Path) -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is not available")

    script_source = Path(__file__).resolve().parents[1] / "promote-existing-build.ps1"
    script_path = tmp_path / "promote-existing-build.ps1"
    script_path.write_text(script_source.read_text(encoding="utf-8"), encoding="utf-8")
    config_path = tmp_path / "project.json"
    config_path.write_text('{"project":"orders"}', encoding="utf-8")
    logs_root = tmp_path / "logs"
    logs_root.mkdir()
    _write_promote_log(
        logs_root / "20260520-120000-update.log",
        commit="old-commit",
        fingerprint="old-fp",
        report_hash="old-hash",
    )
    latest_log = logs_root / "20260520-130000-update.log"
    _write_promote_log(latest_log, commit="new-commit", fingerprint="new-fp", report_hash="new-hash")
    env, args_file = _prepare_fake_python(tmp_path)

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-Config",
            str(config_path),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    args_text = args_file.read_text(encoding="utf-8")
    assert result.returncode == 0
    assert f"Using update log: {latest_log}" in result.stdout
    assert "--promote-commit new-commit" in args_text
    assert "--promote-source-fingerprint new-fp" in args_text
    assert "--promote-report-hash new-hash" in args_text


def test_promote_wrapper_explicit_update_log_does_not_require_paths_root(tmp_path: Path) -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is not available")

    script_source = Path(__file__).resolve().parents[1] / "promote-existing-build.ps1"
    script_path = tmp_path / "promote-existing-build.ps1"
    script_path.write_text(script_source.read_text(encoding="utf-8"), encoding="utf-8")
    config_path = tmp_path / "project.json"
    config_path.write_text('{"project":"orders"}', encoding="utf-8")
    explicit_log = tmp_path / "manual-update.log"
    _write_promote_log(explicit_log, commit="manual-commit", fingerprint="manual-fp", report_hash="manual-hash")
    env, args_file = _prepare_fake_python(tmp_path)

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-Config",
            str(config_path),
            "-UpdateLog",
            str(explicit_log),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    args_text = args_file.read_text(encoding="utf-8")
    assert result.returncode == 0
    assert f"Using update log: {explicit_log}" in result.stdout
    assert "--promote-commit manual-commit" in args_text
    assert "--promote-source-fingerprint manual-fp" in args_text
    assert "--promote-report-hash manual-hash" in args_text
