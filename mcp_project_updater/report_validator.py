from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ReportValidationConfig
from .constants import ExitCode, REPORT_DIAGNOSTICS_FILE_NAME, REPORT_ROOT_REGEX, REPORT_STATS_FILE_NAME
from .errors import UpdaterError


class ReportValidationError(UpdaterError):
    pass


@dataclass(slots=True)
class ReportValidationResult:
    report_path: Path
    report_size: int
    diagnostics_error_count: int


def validate_report(
    report_path: Path,
    validation_config: ReportValidationConfig,
    diagnostics_path: Path | None = None,
) -> ReportValidationResult:
    if not report_path.exists():
        raise ReportValidationError(f"Report file does not exist: {report_path}", ExitCode.REPORT_VALIDATION_FAILED)

    report_text = report_path.read_text(encoding="utf-8")
    report_size = len(report_text.encode("utf-8"))
    if report_size <= 0 or not report_text.strip():
        raise ReportValidationError("Report.txt is empty.", ExitCode.REPORT_VALIDATION_FAILED)

    if not re.search(REPORT_ROOT_REGEX, report_text, flags=re.MULTILINE):
        raise ReportValidationError("Report.txt does not contain a valid root section.", ExitCode.REPORT_VALIDATION_FAILED)

    for pattern in validation_config.required_report_patterns:
        if not re.search(pattern, report_text, flags=re.MULTILINE):
            raise ReportValidationError(
                f"Report.txt is missing required pattern: {pattern}",
                ExitCode.REPORT_VALIDATION_FAILED,
            )

    for pattern in validation_config.forbidden_report_patterns:
        if re.search(pattern, report_text, flags=re.MULTILINE):
            raise ReportValidationError(
                f"Report.txt contains forbidden pattern: {pattern}",
                ExitCode.REPORT_VALIDATION_FAILED,
            )

    diagnostics_error_count = _count_diagnostics_errors(diagnostics_path) if diagnostics_path else 0
    if diagnostics_error_count > 0:
        raise ReportValidationError(
            f"Diagnostics contain parser errors: {diagnostics_error_count}",
            ExitCode.REPORT_VALIDATION_FAILED,
        )

    return ReportValidationResult(
        report_path=report_path,
        report_size=report_size,
        diagnostics_error_count=diagnostics_error_count,
    )


def _count_diagnostics_errors(diagnostics_path: Path) -> int:
    if not diagnostics_path.exists():
        return 0

    total_errors = 0
    for file_name in (REPORT_DIAGNOSTICS_FILE_NAME, REPORT_STATS_FILE_NAME):
        candidate = diagnostics_path / file_name
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        total_errors += _extract_error_count(payload)
    return total_errors


def _extract_error_count(payload: Any) -> int:
    if isinstance(payload, dict):
        if "errors" in payload:
            return _normalize_error_value(payload["errors"])

        count = 0
        for key, value in payload.items():
            if key.lower() in {"severity", "level"} and str(value).lower() == "error":
                count += 1
            else:
                count += _extract_error_count(value)
        return count

    if isinstance(payload, list):
        return sum(_extract_error_count(item) for item in payload)

    return 0


def _normalize_error_value(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return _extract_error_count(value)
    return 0
