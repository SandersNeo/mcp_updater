from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import ProjectConfig
from .constants import REPORT_FILE_NAME
from .source_detector import SourceDetectionResult


@dataclass(slots=True)
class BuildPaths:
    root: Path
    metadata: Path
    code: Path
    diagnostics: Path
    logs: Path
    settings: Path
    parser_config_path: Path
    report_path: Path
    generator_settings_path: Path


def prepare_build_staging(staging_root: Path, project_name: str) -> BuildPaths:
    build_root = staging_root / "build"
    if build_root.exists():
        shutil.rmtree(build_root)

    metadata = build_root / "metadata"
    code = build_root / "code"
    diagnostics = build_root / "diagnostics"
    logs = build_root / "logs"
    settings = build_root / "settings"

    for path in (metadata, code, diagnostics, logs, settings):
        path.mkdir(parents=True, exist_ok=True)

    return BuildPaths(
        root=build_root,
        metadata=metadata,
        code=code,
        diagnostics=diagnostics,
        logs=logs,
        settings=settings,
        parser_config_path=build_root / "parser-config.json",
        report_path=metadata / REPORT_FILE_NAME,
        generator_settings_path=settings / f"{project_name}.xml-overrides.json",
    )


def generate_parser_config(
    config: ProjectConfig,
    build_paths: BuildPaths,
    source_result: SourceDetectionResult,
) -> dict[str, object]:
    return {
        "project": config.project,
        "repoPath": str(config.repo.path),
        "mainConfigPath": config.sources.main_config_path if source_result.main_exists else "",
        "mainConfigRequired": config.sources.main_config_required,
        "extensionPath": config.sources.extension_path if source_result.extension_exists else "",
        "extensionRequired": config.sources.extension_required,
        "outputPath": str(build_paths.metadata),
        "reportFileName": REPORT_FILE_NAME,
        "diagnosticsPath": str(build_paths.diagnostics),
        "logsPath": str(build_paths.logs),
        "encoding": config.parser.encoding,
        "warningsAsErrors": config.parser.warnings_as_errors,
        "buildXmlOverrides": config.parser.build_xml_overrides,
        "generatorSettingsPath": str(build_paths.generator_settings_path),
    }


def write_parser_config(build_paths: BuildPaths, parser_config: dict[str, object]) -> Path:
    build_paths.parser_config_path.write_text(
        json.dumps(parser_config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return build_paths.parser_config_path


def copy_native_report(build_paths: BuildPaths, source_report_path: Path) -> Path:
    shutil.copyfile(source_report_path, build_paths.report_path)
    return build_paths.report_path


def prepare_build_code_directory(build_paths: BuildPaths, source_result: SourceDetectionResult) -> None:
    if source_result.main_exists and source_result.main_path is not None:
        shutil.copytree(source_result.main_path, build_paths.code / "cf", dirs_exist_ok=True)

    if source_result.extension_exists and source_result.extension_path is not None:
        shutil.copytree(source_result.extension_path, build_paths.code / "cfe", dirs_exist_ok=True)
