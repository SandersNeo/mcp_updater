from __future__ import annotations

import argparse
from typing import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run MCP smoke tests.")
    parser.add_argument("--url", required=False, help="MCP server URL")
    parser.add_argument("--timeout", required=False, type=int, help="Timeout in seconds")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    build_parser().parse_args(argv)
    print("mcp_smoke_test skeleton is ready. Implementation will follow in a later phase.")
    return 0

