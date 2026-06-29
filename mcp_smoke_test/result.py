from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SmokeToolConfig:
    url: str
    timeout_seconds: int
    overall_timeout_seconds: int
    index_code: bool
    diagnostic: bool
    metadata_tool_name: str
    metadata_query_argument: str
    metadata_queries: list[str]
    code_tool_name: str
    code_query_argument: str
    code_queries: list[str]
    require_metadata_vector_index: bool = True
    require_code_vector_index: bool = True


@dataclass(slots=True)
class SmokeTestRunResult:
    listed_tools: list[str]
    metadata_ok: bool
    code_ok: bool
    stats_ok: bool = True
