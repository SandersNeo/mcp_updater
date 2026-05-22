from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_project_updater.config import ReportValidationConfig
from mcp_project_updater.constants import ExitCode
from mcp_project_updater.report_validator import ReportValidationError, validate_report


def _config() -> ReportValidationConfig:
    return ReportValidationConfig(
        enabled=True,
        required_report_patterns=["Имя: \"", "Синоним: \""],
        forbidden_report_patterns=["src/cf"],
    )


def test_validate_report_with_root_leading_tab(tmp_path: Path) -> None:
    report_path = tmp_path / "Report.txt"
    report_path.write_text('\t- Конфигурации.Orders\nИмя: "Orders"\nСиноним: "Orders"\n', encoding="utf-8")

    result = validate_report(report_path, _config(), tmp_path / "diagnostics")

    assert result.report_size > 0


def test_validate_report_accepts_utf16_with_bom(tmp_path: Path) -> None:
    report_path = tmp_path / "Report.txt"
    report_path.write_text('\t- Конфигурации.Orders\nИмя: "Orders"\nСиноним: "Orders"\n', encoding="utf-16")

    result = validate_report(report_path, _config(), tmp_path / "diagnostics")

    assert result.report_size == len(report_path.read_bytes())


def test_validate_report_forbidden_pattern(tmp_path: Path) -> None:
    report_path = tmp_path / "Report.txt"
    report_path.write_text('\t- Конфигурации.Orders\nИмя: "Orders"\nСиноним: "Orders"\nsrc/cf\n', encoding="utf-8")

    with pytest.raises(ReportValidationError) as exc:
        validate_report(report_path, _config(), tmp_path / "diagnostics")

    assert exc.value.exit_code == ExitCode.REPORT_VALIDATION_FAILED


def test_validate_report_missing_root(tmp_path: Path) -> None:
    report_path = tmp_path / "Report.txt"
    report_path.write_text('Имя: "Orders"\nСиноним: "Orders"\n', encoding="utf-8")

    with pytest.raises(ReportValidationError):
        validate_report(report_path, _config(), tmp_path / "diagnostics")


def test_validate_report_empty_file(tmp_path: Path) -> None:
    report_path = tmp_path / "Report.txt"
    report_path.write_text("", encoding="utf-8")

    with pytest.raises(ReportValidationError):
        validate_report(report_path, _config(), tmp_path / "diagnostics")


def test_validate_report_fails_when_diagnostics_have_errors(tmp_path: Path) -> None:
    report_path = tmp_path / "Report.txt"
    diagnostics_path = tmp_path / "diagnostics"
    diagnostics_path.mkdir()
    report_path.write_text('\t- Конфигурации.Orders\nИмя: "Orders"\nСиноним: "Orders"\n', encoding="utf-8")
    (diagnostics_path / "report-diagnostics.json").write_text(json.dumps({"errors": 1}), encoding="utf-8")

    with pytest.raises(ReportValidationError):
        validate_report(report_path, _config(), diagnostics_path)
