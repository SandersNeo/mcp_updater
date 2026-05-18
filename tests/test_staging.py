from __future__ import annotations

import json
from pathlib import Path

from mcp_project_updater.config import load_project_config
from mcp_project_updater.source_detector import detect_sources
from mcp_project_updater.staging import (
    generate_parser_config,
    prepare_build_code_directory,
    prepare_build_staging,
    write_parser_config,
)
from tests.config_helpers import strip_global_project_blocks, write_runtime_files


def _write_config(tmp_path: Path) -> Path:
    repo_path = tmp_path / "repo"
    (repo_path / "src" / "cf").mkdir(parents=True)
    (repo_path / "src" / "cfe").mkdir(parents=True)
    (repo_path / "src" / "cf" / "main.txt").write_text("cf", encoding="utf-8")
    (repo_path / "src" / "cfe" / "ext.txt").write_text("cfe", encoding="utf-8")
    parser_path = tmp_path / "generate_config_report.py"
    parser_path.write_text("print('ok')\n", encoding="utf-8")
    tool_path = tmp_path / "mcp_smoke_test.py"
    tool_path.write_text("print('ok')\n", encoding="utf-8")
    write_runtime_files(tmp_path, parser_path=parser_path, tool_path=tool_path)

    payload = {
        "project": "orders",
        "repo": {"branch": "master", "remote": "origin", "pullMode": "ff-only"},
        "sources": {
            "mainConfigPath": "src/cf",
            "mainConfigRequired": False,
            "extensionPath": "src/cfe",
            "extensionRequired": False,
        },
        "parser": {
            "toolPath": str(parser_path),
            "encoding": "utf-8",
            "warningsAsErrors": False,
            "buildXmlOverrides": True,
            "allowedExitCodes": [0, 1],
        },
        "mcp": {
            "image": "comol/1c_code_metadata_mcp:light",
            "containerPort": 8000,
            "production": {"containerName": "prod", "hostPort": 8100, "url": "http://localhost:8100/mcp"},
            "build": {"containerName": "build", "hostPort": 18100, "url": "http://localhost:18100/mcp"},
            "indexCode": True,
            "indexMetadata": True,
            "indexHelp": False,
            "resetDatabaseOnBuild": True,
            "resetCache": False,
            "useSse": False,
            "useGpu": False,
            "env": {},
            "secretEnv": {},
        },
        "paths": {
            "root": str(tmp_path),
        },
        "smokeTest": {
            "enabled": True,
            "profile": "dev",
            "reportValidation": {
                "enabled": True,
                "requiredReportPatterns": ["Имя: \""],
                "forbiddenReportPatterns": [],
            },
            "infrastructure": {
                "enabled": True,
                "timeoutSeconds": 60,
                "checkIntervalSeconds": 5,
                "httpReadyUrl": "http://localhost:18100/mcp",
                "acceptableHttpStatusCodes": [200],
                "requireChromaNotEmpty": True,
                "logTailLines": 100,
                "logErrorPatterns": ["Traceback"],
                "logReadyPatterns": ["Started"],
            },
            "toolSmokeTest": {
                "enabled": True,
                "toolPath": str(tmp_path / "mcp_smoke_test.py"),
                "url": "http://localhost:18100/mcp",
                "timeoutSeconds": 60,
                "metadataToolName": "metadatasearch",
                "metadataQueryArgument": "query",
                "metadataQueries": ["Конфигурации"],
                "codeToolName": "codesearch",
                "codeQueryArgument": "query",
                "codeQueries": ["Процедура"],
            },
        },
        "notifications": {
            "enabled": True,
            "onSuccess": False,
            "onFailure": True,
            "onRollback": True,
            "webhookUrlSecret": "MCP_UPDATE_WEBHOOK_URL",
        },
        "retention": {"keepPreviousIndexes": 1, "keepLogsDays": 30, "keepStagingBuilds": 2},
        "rollback": {"preserveFailedIndex": True},
    }
    strip_global_project_blocks(payload)

    config_path = tmp_path / "project.json"
    config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return config_path


def test_prepare_build_staging_creates_expected_structure(tmp_path: Path) -> None:
    build_paths = prepare_build_staging(tmp_path / "staging", "orders")

    assert build_paths.metadata.exists()
    assert build_paths.code.exists()
    assert build_paths.diagnostics.exists()
    assert build_paths.logs.exists()
    assert build_paths.settings.exists()
    assert build_paths.generator_settings_path.name == "orders.xml-overrides.json"


def test_generate_and_write_parser_config(tmp_path: Path) -> None:
    config = load_project_config(_write_config(tmp_path))
    build_paths = prepare_build_staging(config.paths.staging_root, config.project)
    source_result = detect_sources(
        config.repo.path,
        config.sources.main_config_path,
        config.sources.main_config_required,
        config.sources.extension_path,
        config.sources.extension_required,
    )

    parser_config = generate_parser_config(config, build_paths, source_result)
    parser_config_path = write_parser_config(build_paths, parser_config)
    written = json.loads(parser_config_path.read_text(encoding="utf-8"))

    assert written["outputPath"] == str(build_paths.metadata)
    assert written["diagnosticsPath"] == str(build_paths.diagnostics)
    assert written["logsPath"] == str(build_paths.logs)
    assert written["generatorSettingsPath"] == str(build_paths.generator_settings_path)


def test_generate_parser_config_uses_null_for_missing_optional_source(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["sources"]["mainConfigPath"] = None
    payload["sources"]["mainConfigRequired"] = False
    config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    config = load_project_config(config_path)
    build_paths = prepare_build_staging(config.paths.staging_root, config.project)
    source_result = detect_sources(
        config.repo.path,
        config.sources.main_config_path,
        config.sources.main_config_required,
        config.sources.extension_path,
        config.sources.extension_required,
    )

    parser_config = generate_parser_config(config, build_paths, source_result)

    assert parser_config["mainConfigPath"] is None
    assert parser_config["extensionPath"] == "src/cfe"


def test_prepare_build_code_directory_copies_existing_sources(tmp_path: Path) -> None:
    config = load_project_config(_write_config(tmp_path))
    build_paths = prepare_build_staging(config.paths.staging_root, config.project)
    source_result = detect_sources(
        config.repo.path,
        config.sources.main_config_path,
        config.sources.main_config_required,
        config.sources.extension_path,
        config.sources.extension_required,
    )

    prepare_build_code_directory(build_paths, source_result)

    assert (build_paths.code / "cf" / "main.txt").read_text(encoding="utf-8") == "cf"
    assert (build_paths.code / "cfe" / "ext.txt").read_text(encoding="utf-8") == "cfe"
