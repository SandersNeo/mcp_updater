from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .constants import ExitCode
from .errors import UpdaterError


class SourceDetectionError(UpdaterError):
    pass


@dataclass(slots=True)
class SourceDetectionResult:
    main_exists: bool
    extension_exists: bool
    main_path: Path | None
    extension_path: Path | None
    native_report_path: Path | None


def detect_sources(
    repo_path: Path,
    main_config_path: str | None,
    main_config_required: bool,
    extension_path: str | None,
    extension_required: bool,
    native_report_path: str | None = None,
) -> SourceDetectionResult:
    resolved_main_path = repo_path / main_config_path if main_config_path else None
    resolved_extension_path = repo_path / extension_path if extension_path else None
    resolved_native_report_path = repo_path / native_report_path if native_report_path else None

    main_exists = resolved_main_path.exists() if resolved_main_path is not None else False
    extension_exists = resolved_extension_path.exists() if resolved_extension_path is not None else False
    native_report_exists = resolved_native_report_path.exists() if resolved_native_report_path is not None else False

    if main_config_required and not main_exists:
        raise SourceDetectionError(
            f"Required main configuration source is missing: {resolved_main_path}",
            ExitCode.MAIN_CONFIG_REQUIRED_MISSING,
        )

    if extension_required and not extension_exists:
        raise SourceDetectionError(
            f"Required extension source is missing: {resolved_extension_path}",
            ExitCode.EXTENSION_REQUIRED_MISSING,
        )

    if not main_exists and not extension_exists:
        raise SourceDetectionError(
            f"Neither main nor extension source exists under repo '{repo_path}'.",
            ExitCode.MISSING_SOURCES,
        )

    if resolved_native_report_path is not None and not native_report_exists:
        raise SourceDetectionError(
            f"Configured native report file is missing: {resolved_native_report_path}",
            ExitCode.MISSING_SOURCES,
        )

    return SourceDetectionResult(
        main_exists=main_exists,
        extension_exists=extension_exists,
        main_path=resolved_main_path if main_exists else None,
        extension_path=resolved_extension_path if extension_exists else None,
        native_report_path=resolved_native_report_path if native_report_exists else None,
    )
