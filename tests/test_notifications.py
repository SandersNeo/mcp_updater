from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from mcp_project_updater.notifications import NotificationError, NotificationPayload, cleanup_old_logs, send_notification
from mcp_project_updater.config import NotificationsConfig


def _notifications_config() -> NotificationsConfig:
    return NotificationsConfig(
        enabled=True,
        on_success=False,
        on_failure=True,
        on_rollback=True,
        webhook_url_secret="MCP_UPDATE_WEBHOOK_URL",
        secrets={"MCP_UPDATE_WEBHOOK_URL": "https://example.invalid"},
    )


def test_send_notification_disabled() -> None:
    config = NotificationsConfig(
        enabled=False,
        on_success=False,
        on_failure=True,
        on_rollback=True,
        webhook_url_secret="MCP_UPDATE_WEBHOOK_URL",
        secrets={},
    )
    send_notification(
        config,
        NotificationPayload("orders", "failed", "parser", "abc", "def", True, False, None, "log"),
        env={},
        sender=lambda url, payload: (_ for _ in ()).throw(RuntimeError("should not happen")),
    )


def test_send_notification_success() -> None:
    sent = {}
    send_notification(
        _notifications_config(),
        NotificationPayload("orders", "failed", "parser", "abc", "def", True, False, None, "log"),
        env={"MCP_UPDATE_WEBHOOK_URL": "https://example.invalid"},
        sender=lambda url, payload: sent.update({"url": url, "payload": payload}),
    )

    assert sent["payload"]["project"] == "orders"


def test_send_notification_missing_secret_raises() -> None:
    config = _notifications_config()
    config.secrets = {}
    with pytest.raises(NotificationError):
        send_notification(
            config,
            NotificationPayload("orders", "failed", "parser", "abc", "def", True, False, None, "log"),
        )


def test_cleanup_old_logs(tmp_path: Path) -> None:
    old_log = tmp_path / "old.log"
    new_log = tmp_path / "new.log"
    old_log.write_text("old", encoding="utf-8")
    new_log.write_text("new", encoding="utf-8")

    old_time = (datetime.now() - timedelta(days=31)).timestamp()
    new_time = datetime.now().timestamp()
    old_log.touch()
    new_log.touch()
    import os
    os.utime(old_log, (old_time, old_time))
    os.utime(new_log, (new_time, new_time))

    removed = cleanup_old_logs(tmp_path, 30, now_provider=datetime.now)

    assert old_log in removed
    assert not old_log.exists()
    assert new_log.exists()
