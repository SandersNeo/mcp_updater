from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

from .config import NotificationsConfig
from .constants import ExitCode
from .errors import UpdaterError


class NotificationError(UpdaterError):
    def __init__(self, message: str) -> None:
        super().__init__(message, ExitCode.NOTIFICATION_FAILED)


@dataclass(slots=True)
class NotificationPayload:
    project: str
    status: str
    stage: str
    targetCommit: str | None
    lastIndexedCommit: str | None
    productionUntouched: bool
    rollbackAttempted: bool
    rollbackSuccess: bool | None
    logPath: str


def send_notification(
    config: NotificationsConfig,
    payload: NotificationPayload,
    *,
    env: dict[str, str] | None = None,
    sender: Callable[[str, dict], None] | None = None,
) -> None:
    if not config.enabled:
        return

    env = env or os.environ
    webhook_url = env.get(config.webhook_url_env)
    if not webhook_url:
        raise NotificationError(f"Notification environment variable is missing: {config.webhook_url_env}")

    sender = sender or _default_sender
    try:
        sender(webhook_url, asdict(payload))
    except Exception as exc:
        raise NotificationError(f"Failed to send notification: {exc}") from exc


def cleanup_old_logs(
    logs_root: Path,
    keep_logs_days: int,
    *,
    now_provider: Callable[[], datetime] | None = None,
) -> list[Path]:
    now_provider = now_provider or datetime.now
    if not logs_root.exists():
        return []

    cutoff = now_provider() - timedelta(days=keep_logs_days)
    removed: list[Path] = []
    for path in logs_root.iterdir():
        if not path.is_file():
            continue
        modified_at = datetime.fromtimestamp(path.stat().st_mtime)
        if modified_at < cutoff:
            path.unlink()
            removed.append(path)
    return removed


def _default_sender(webhook_url: str, payload: dict) -> None:
    request = Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            if response.status >= 400:
                raise NotificationError(f"Webhook returned HTTP {response.status}")
    except URLError as exc:
        raise NotificationError("Webhook request failed.") from exc
