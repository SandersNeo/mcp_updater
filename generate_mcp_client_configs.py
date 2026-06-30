from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from mcp_project_updater.mcp_client_configs import DEFAULT_CLIENT_HOST, generate_mcp_client_configs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Codex and Cursor MCP client configs from updater projects.")
    parser.add_argument("--data-root", required=True, type=Path, help="Directory with project subfolders and project.json files.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("generated-mcp-client-configs"),
        help="Directory for generated codex-mcp-servers.toml and cursor-mcp.json.",
    )
    parser.add_argument(
        "--client-host",
        default=DEFAULT_CLIENT_HOST,
        help="Host name to use in generated client URLs. Defaults to 1c-mcp.",
    )
    parser.add_argument(
        "--no-host-override",
        action="store_true",
        help="Keep production URLs exactly as resolved from project configs.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client_host = None if args.no_host_override else args.client_host
    result = generate_mcp_client_configs(args.data_root, args.output_dir, client_host=client_host)

    print(f"Generated MCP client configs for {len(result.servers)} project(s).")
    print(f"Codex: {result.codex_output_path}")
    print(f"Cursor: {result.cursor_output_path}")
    for server in result.servers:
        print(f"- {server.server_name}: {server.url}")
    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"- {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
