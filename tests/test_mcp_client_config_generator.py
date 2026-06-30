from __future__ import annotations

import json
from pathlib import Path

from mcp_project_updater.mcp_client_configs import (
    client_url,
    collect_mcp_client_servers,
    generate_mcp_client_configs,
    render_codex_toml,
    render_cursor_json,
)


def _write_data_root(tmp_path: Path) -> Path:
    data_root = tmp_path / "mcp-updater-data"
    data_root.mkdir()
    parser_path = tmp_path / "generate_config_report.py"
    parser_path.write_text("print('ok')\n", encoding="utf-8")
    smoke_path = tmp_path / "mcp_smoke_test.py"
    smoke_path.write_text("print('ok')\n", encoding="utf-8")
    (data_root / "settings.global.json").write_text(
        json.dumps(
            {
                "parser": {
                    "toolPath": str(parser_path),
                    "encoding": "utf-8",
                    "warningsAsErrors": False,
                    "buildXmlOverrides": True,
                    "allowedExitCodes": [0, 1],
                },
                "projectDefaults": {
                    "indexStorageRootTemplate": r"\\wsl.localhost\Ubuntu\mcp-indexes\{project}",
                    "productionContainerNameTemplate": "mcp-{project}",
                    "buildContainerNameTemplate": "mcp-{project}-build",
                    "urlScheme": "http",
                    "urlHost": "localhost",
                    "urlPath": "/mcp",
                    "buildHostPortOffset": 10000,
                    "containerPort": 8000,
                },
                "mcp": {
                    "secretEnv": {
                        "LICENSE_KEY": "ONERPA_LICENSE_KEY",
                    }
                },
                "smokeTest": {
                    "enabled": True,
                    "profile": "production",
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
                        "logErrorPatterns": ["Traceback"],
                        "logReadyPatterns": [],
                    },
                    "toolSmokeTest": {
                        "enabled": True,
                        "toolPath": str(smoke_path),
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
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (data_root / "secrets.global.json").write_text(json.dumps({"ONERPA_LICENSE_KEY": "license"}), encoding="utf-8")
    (data_root / "not-a-project").mkdir()
    return data_root


def _write_project(data_root: Path, name: str, host_port: int) -> Path:
    project_root = data_root / name
    project_root.mkdir()
    index_storage_root = data_root / "indexes" / name
    index_storage_root.parent.mkdir(parents=True, exist_ok=True)
    (project_root / "secrets.local.json").write_text(json.dumps({}), encoding="utf-8")
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project": name,
                "repo": {
                    "branch": "master",
                    "remote": "origin",
                    "pullMode": "ff-only",
                    "cloneUrl": f"https://gitlab.example.com/{name}.git",
                },
                "sources": {
                    "mainConfigPath": "src/cf",
                    "mainConfigRequired": False,
                    "extensionPath": "src/cfe",
                    "extensionRequired": False,
                    "nativeReportPath": None,
                },
                "mcp": {
                    "image": "comol/1c_code_metadata_mcp:latest",
                    "hostPort": host_port,
                    "indexStorageRoot": str(index_storage_root),
                },
                "notifications": {
                    "enabled": False,
                    "onSuccess": True,
                    "onFailure": True,
                    "onRollback": True,
                    "webhookUrlSecret": "MCP_UPDATE_WEBHOOK_URL",
                },
                "retention": {
                    "keepPreviousIndexes": 1,
                    "keepLogsDays": 30,
                    "keepStagingBuilds": 2,
                },
                "rollback": {
                    "preserveFailedIndex": True,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return project_root


def test_collect_mcp_client_servers_scans_data_root_and_ignores_non_projects(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("mcp_project_updater.config.platform.system", lambda: "Linux")
    data_root = _write_data_root(tmp_path)
    _write_project(data_root, "orders", 8100)
    _write_project(data_root, "zup", 8150)

    servers, warnings = collect_mcp_client_servers(data_root, client_host="1c-mcp")

    assert warnings == []
    assert [server.project for server in servers] == ["orders", "zup"]
    assert [server.server_name for server in servers] == [
        "1c-code-metadata-mcp-orders",
        "1c-code-metadata-mcp-zup",
    ]
    assert [server.url for server in servers] == [
        "http://1c-mcp:8100/mcp",
        "http://1c-mcp:8150/mcp",
    ]


def test_collect_mcp_client_servers_warns_and_continues_on_invalid_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("mcp_project_updater.config.platform.system", lambda: "Linux")
    data_root = _write_data_root(tmp_path)
    _write_project(data_root, "orders", 8100)
    broken_root = data_root / "broken"
    broken_root.mkdir()
    (broken_root / "project.json").write_text('{"project":"broken"}', encoding="utf-8")

    servers, warnings = collect_mcp_client_servers(data_root, client_host="1c-mcp")

    assert [server.project for server in servers] == ["orders"]
    assert len(warnings) == 1
    assert "broken" in warnings[0]


def test_client_url_preserves_url_parts_when_overriding_host() -> None:
    assert (
        client_url("http://localhost:8100/mcp?x=1#frag", client_host="1c-mcp")
        == "http://1c-mcp:8100/mcp?x=1#frag"
    )


def test_render_codex_toml_output() -> None:
    server = _server("orders", "http://1c-mcp:8100/mcp")

    toml = render_codex_toml([server])

    assert "[mcp_servers.1c-code-metadata-mcp-orders]" in toml
    assert "enabled = true" in toml
    assert 'url = "http://1c-mcp:8100/mcp"' in toml


def test_render_cursor_json_output() -> None:
    server = _server("orders", "http://1c-mcp:8100/mcp")

    payload = json.loads(render_cursor_json([server]))

    assert payload["mcpServers"]["1c-code-metadata-mcp-orders"] == {
        "url": "http://1c-mcp:8100/mcp",
        "connection_id": "1c_code_metadata_mcp_orders",
    }


def test_generate_mcp_client_configs_writes_both_outputs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("mcp_project_updater.config.platform.system", lambda: "Linux")
    data_root = _write_data_root(tmp_path)
    _write_project(data_root, "orders", 8100)
    output_dir = tmp_path / "out"

    result = generate_mcp_client_configs(data_root, output_dir, client_host="1c-mcp")

    assert result.codex_output_path == output_dir / "codex-mcp-servers.toml"
    assert result.cursor_output_path == output_dir / "cursor-mcp.json"
    assert result.codex_output_path.exists()
    assert result.cursor_output_path.exists()
    assert "1c-code-metadata-mcp-orders" in result.codex_output_path.read_text(encoding="utf-8")
    assert "1c-code-metadata-mcp-orders" in result.cursor_output_path.read_text(encoding="utf-8")


def _server(project: str, url: str):
    from mcp_project_updater.mcp_client_configs import MCPClientServer

    return MCPClientServer(
        project=project,
        server_name=f"1c-code-metadata-mcp-{project}",
        url=url,
        config_path=Path(f"{project}/project.json"),
    )
