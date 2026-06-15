from __future__ import annotations

import json
from pathlib import Path


def write_runtime_files(project_root: Path, *, parser_path: Path, tool_path: Path) -> None:
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root.parent / "secrets.global.json").write_text(
        json.dumps({"ONERPA_LICENSE_KEY": "license-value"}),
        encoding="utf-8",
    )
    (project_root / "secrets.local.json").write_text(
        json.dumps({"GITLAB_TOKEN": "gitlab-value", "MCP_UPDATE_WEBHOOK_URL": "https://example.com/webhook"}),
        encoding="utf-8",
    )
    (project_root.parent / "settings.global.json").write_text(
        json.dumps(_settings_payload(parser_path, tool_path), ensure_ascii=False),
        encoding="utf-8",
    )


def strip_global_project_blocks(payload: dict) -> None:
    payload.pop("parser", None)
    payload.pop("smokeTest", None)


def _settings_payload(parser_path: Path, tool_path: Path) -> dict:
    return {
        "parser": {
            "toolPath": str(parser_path),
            "encoding": "utf-8",
            "warningsAsErrors": False,
            "buildXmlOverrides": True,
            "allowedExitCodes": [0, 1],
        },
        "mcp": {
            "env": {},
            "secretEnv": {
                "LICENSE_KEY": "ONERPA_LICENSE_KEY",
            },
        },
        "smokeTest": {
            "enabled": True,
            "profile": "dev",
            "reportValidation": {
                "enabled": True,
                "requiredReportPatterns": ['Имя: "'],
                "forbiddenReportPatterns": [],
            },
            "infrastructure": {
                "enabled": True,
                "timeoutSeconds": 60,
                "checkIntervalSeconds": 5,
                "acceptableHttpStatusCodes": [200, 400, 404, 405, 406],
                "requireIndexStorageNotEmpty": True,
                "logTailLines": 100,
                "logErrorPatterns": ["Traceback", "Unhandled exception", "CRITICAL"],
                "logReadyPatterns": ["Started"],
            },
            "toolSmokeTest": {
                "enabled": True,
                "toolPath": str(tool_path),
                "timeoutSeconds": 300,
                "attemptTimeoutSeconds": 60,
                "retryIntervalSeconds": 10,
                "diagnostic": False,
                "metadataToolName": "metadatasearch",
                "metadataQueryArgument": "query",
                "metadataQueries": ["Конфигурации"],
                "codeToolName": "codesearch",
                "codeQueryArgument": "query",
                "codeQueries": ["Процедура"],
            },
        },
    }
