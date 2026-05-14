from __future__ import annotations

import http.client
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .config import InfrastructureSmokeConfig
from .constants import ExitCode
from .docker_ops import DockerCommandRunner, inspect_container, read_container_logs
from .errors import UpdaterError


class InfrastructureSmokeError(UpdaterError):
    def __init__(self, message: str) -> None:
        super().__init__(message, ExitCode.BUILD_SMOKE_FAILED)


@dataclass(slots=True)
class InfrastructureSmokeContext:
    container_name: str
    host_port: int
    url: str
    chroma_path: Path


@dataclass(slots=True)
class InfrastructureSmokeResult:
    http_status_code: int
    logs_checked: bool
    chroma_non_empty: bool


HttpStatusGetter = Callable[[str], int]
PortChecker = Callable[[str, int], bool]


def run_infrastructure_smoke_test(
    smoke_config: InfrastructureSmokeConfig,
    context: InfrastructureSmokeContext,
    *,
    runner: DockerCommandRunner,
    http_status_getter: HttpStatusGetter | None = None,
    port_checker: PortChecker | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> InfrastructureSmokeResult:
    http_status_getter = http_status_getter or _default_http_status_getter
    port_checker = port_checker or _default_port_checker

    deadline = monotonic() + smoke_config.timeout_seconds
    last_failure = "Infrastructure smoke-test timed out."

    while monotonic() <= deadline:
        inspection = inspect_container(context.container_name, runner=runner)
        if inspection is None:
            last_failure = f"Container '{context.container_name}' does not exist yet."
            sleep(smoke_config.check_interval_seconds)
            continue

        state = inspection.get("State", {})
        if state.get("Status") != "running":
            last_failure = f"Container '{context.container_name}' is not running: {state.get('Status')}"
            sleep(smoke_config.check_interval_seconds)
            continue

        if bool(state.get("Restarting")):
            last_failure = f"Container '{context.container_name}' is restarting."
            sleep(smoke_config.check_interval_seconds)
            continue

        host = urlparse(context.url).hostname or "localhost"
        if not port_checker(host, context.host_port):
            last_failure = f"Host port {context.host_port} is not reachable."
            sleep(smoke_config.check_interval_seconds)
            continue

        try:
            http_status = http_status_getter(context.url)
        except (URLError, OSError, http.client.HTTPException) as exc:
            last_failure = f"HTTP readiness check failed: {exc}"
            sleep(smoke_config.check_interval_seconds)
            continue

        if http_status not in smoke_config.acceptable_http_status_codes:
            last_failure = f"Unexpected HTTP status code: {http_status}"
            sleep(smoke_config.check_interval_seconds)
            continue

        if not context.chroma_path.exists():
            last_failure = f"Chroma path does not exist: {context.chroma_path}"
            sleep(smoke_config.check_interval_seconds)
            continue

        chroma_non_empty = _is_directory_non_empty(context.chroma_path)
        if smoke_config.require_chroma_not_empty and not chroma_non_empty:
            last_failure = f"Chroma path is empty: {context.chroma_path}"
            sleep(smoke_config.check_interval_seconds)
            continue

        logs_text = read_container_logs(
            context.container_name,
            tail_lines=smoke_config.log_tail_lines,
            runner=runner,
        )
        for pattern in smoke_config.log_error_patterns:
            if pattern and pattern.lower() in logs_text.lower():
                raise InfrastructureSmokeError(f"Docker logs contain error pattern: {pattern}")

        if smoke_config.log_ready_patterns:
            if not any(pattern and pattern.lower() in logs_text.lower() for pattern in smoke_config.log_ready_patterns):
                last_failure = "Docker logs do not contain any ready pattern yet."
                sleep(smoke_config.check_interval_seconds)
                continue

        return InfrastructureSmokeResult(
            http_status_code=http_status,
            logs_checked=True,
            chroma_non_empty=chroma_non_empty,
        )

    raise InfrastructureSmokeError(last_failure)


def _default_http_status_getter(url: str) -> int:
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=5) as response:
            return response.status
    except HTTPError as exc:
        return exc.code
    except (URLError, OSError, http.client.HTTPException):
        raise


def _default_port_checker(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def _is_directory_non_empty(path: Path) -> bool:
    return any(path.rglob("*"))
