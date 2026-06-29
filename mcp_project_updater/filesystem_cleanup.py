from __future__ import annotations

import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


class FilesystemCleanupError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class WslUncPath:
    distro: str
    linux_path: str


def remove_path_if_exists(
    path: Path,
    *,
    allowed_root: Path,
    description: str,
    process_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> None:
    _assert_cleanup_target_inside_root(path, allowed_root=allowed_root)
    wsl_path = parse_wsl_unc_path(path)
    if wsl_path is not None:
        _remove_wsl_unc_path(path, wsl_path, description=description, process_runner=process_runner)
        return

    try:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    except OSError as exc:
        raise FilesystemCleanupError(f"Failed to remove {description} '{path}': {exc}") from exc


def parse_wsl_unc_path(path: Path) -> WslUncPath | None:
    path_text = str(path).replace("/", "\\")
    for prefix in ("\\\\wsl.localhost\\", "\\\\wsl$\\"):
        if path_text.casefold().startswith(prefix.casefold()):
            rest = path_text[len(prefix) :].strip("\\")
            parts = [part for part in rest.split("\\") if part]
            if len(parts) < 2:
                raise FilesystemCleanupError(f"Invalid WSL UNC cleanup path: {path}")
            return WslUncPath(distro=parts[0], linux_path="/" + "/".join(parts[1:]))
    return None


def _assert_cleanup_target_inside_root(path: Path, *, allowed_root: Path) -> None:
    path_text = _normalize_path_for_guard(path)
    root_text = _normalize_path_for_guard(allowed_root)
    if path_text == root_text:
        raise FilesystemCleanupError(f"Refusing to remove cleanup root itself: {path}")
    if not path_text.startswith(f"{root_text}\\"):
        raise FilesystemCleanupError(f"Refusing to remove path outside cleanup root: {path}")


def _normalize_path_for_guard(path: Path) -> str:
    return str(path).replace("/", "\\").rstrip("\\").casefold()


def _remove_wsl_unc_path(
    original_path: Path,
    wsl_path: WslUncPath,
    *,
    description: str,
    process_runner: Callable[..., subprocess.CompletedProcess[str]] | None,
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
    effective_runner = process_runner or subprocess.run
    try:
        result = effective_runner(
            list(command),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise FilesystemCleanupError(f"Failed to run WSL cleanup for {description} '{original_path}': {exc}") from exc
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        message = f"Failed to remove WSL {description} '{original_path}' with exit code {result.returncode}."
        if details:
            message = f"{message} {details}"
        raise FilesystemCleanupError(message)
