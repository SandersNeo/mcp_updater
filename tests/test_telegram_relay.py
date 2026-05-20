from __future__ import annotations

import json

import pytest

from mcp_telegram_relay.cli import (
    RelayConfig,
    RelayConfigError,
    format_notification_message,
    load_config_from_env,
    process_webhook,
    send_telegram_message,
)


def _config(**overrides: object) -> RelayConfig:
    values: dict[str, object] = {
        "host": "127.0.0.1",
        "port": 8787,
        "path": "/webhook",
        "token": "secret-token",
        "telegram_bot_token": "bot-token",
        "telegram_chat_id": "12345",
        "telegram_thread_id": None,
        "message_prefix": "MCP updater",
    }
    values.update(overrides)
    return RelayConfig(
        host=str(values["host"]),
        port=int(values["port"]),
        path=str(values["path"]),
        token=values["token"] if values["token"] is None else str(values["token"]),
        telegram_bot_token=str(values["telegram_bot_token"]),
        telegram_chat_id=str(values["telegram_chat_id"]),
        telegram_thread_id=values["telegram_thread_id"] if values["telegram_thread_id"] is None else int(values["telegram_thread_id"]),
        message_prefix=str(values["message_prefix"]),
    )


def test_load_config_from_env_defaults() -> None:
    config = load_config_from_env(
        {
            "TELEGRAM_BOT_TOKEN": "bot-token",
            "TELEGRAM_CHAT_ID": "12345",
        }
    )

    assert config.host == "127.0.0.1"
    assert config.port == 8787
    assert config.path == "/webhook"
    assert config.token is None
    assert config.telegram_bot_token == "bot-token"
    assert config.telegram_chat_id == "12345"
    assert config.telegram_thread_id is None
    assert config.message_prefix == "MCP updater"


def test_load_config_from_env_optional_values() -> None:
    config = load_config_from_env(
        {
            "RELAY_HOST": "0.0.0.0",
            "RELAY_PORT": "9000",
            "RELAY_PATH": "telegram-hook/",
            "RELAY_TOKEN": "relay-token",
            "TELEGRAM_BOT_TOKEN": "bot-token",
            "TELEGRAM_CHAT_ID": "12345",
            "TELEGRAM_THREAD_ID": "77",
            "TELEGRAM_MESSAGE_PREFIX": "Updater",
        }
    )

    assert config.host == "0.0.0.0"
    assert config.port == 9000
    assert config.path == "/telegram-hook"
    assert config.token == "relay-token"
    assert config.telegram_thread_id == 77
    assert config.message_prefix == "Updater"


def test_load_config_from_env_requires_bot_token() -> None:
    with pytest.raises(RelayConfigError, match="TELEGRAM_BOT_TOKEN"):
        load_config_from_env({"TELEGRAM_CHAT_ID": "12345"})


def test_format_notification_message_includes_payload_fields() -> None:
    message = format_notification_message(
        {
            "project": "orders",
            "status": "failed",
            "stage": "build_smoke",
            "targetCommit": "abc123",
            "lastIndexedCommit": "def456",
            "productionUntouched": True,
            "rollbackAttempted": True,
            "rollbackSuccess": False,
            "logPath": r"C:\logs\run.log",
        },
        prefix="Relay",
    )

    assert message == "\n".join(
        [
            "Relay",
            "project: orders",
            "status: failed",
            "stage: build_smoke",
            "targetCommit: abc123",
            "lastIndexedCommit: def456",
            "productionUntouched: True",
            "rollbackAttempted: True",
            "rollbackSuccess: False",
            r"logPath: C:\logs\run.log",
        ]
    )


def test_process_webhook_success_accepts_trailing_slash() -> None:
    calls: list[str] = []

    def sender(config: RelayConfig, text: str) -> None:
        calls.append(text)

    status_code, payload = process_webhook(
        method="POST",
        raw_path="/webhook/?token=secret-token",
        body=json.dumps(
            {
                "project": "orders",
                "status": "success",
                "stage": "success",
            }
        ).encode("utf-8"),
        config=_config(),
        sender=sender,
    )

    assert status_code == 200
    assert payload == {"ok": True}
    assert len(calls) == 1
    assert "project: orders" in calls[0]


def test_process_webhook_rejects_wrong_method() -> None:
    status_code, payload = process_webhook(
        method="GET",
        raw_path="/webhook?token=secret-token",
        body=b"",
        config=_config(),
        sender=lambda _config, _text: None,
    )

    assert status_code == 405
    assert payload["ok"] is False


def test_process_webhook_rejects_wrong_path() -> None:
    status_code, payload = process_webhook(
        method="POST",
        raw_path="/wrong?token=secret-token",
        body=b"{}",
        config=_config(),
        sender=lambda _config, _text: None,
    )

    assert status_code == 404
    assert payload["ok"] is False


def test_process_webhook_rejects_missing_token() -> None:
    status_code, payload = process_webhook(
        method="POST",
        raw_path="/webhook",
        body=b"{}",
        config=_config(),
        sender=lambda _config, _text: None,
    )

    assert status_code == 403
    assert payload["ok"] is False


def test_process_webhook_rejects_invalid_json() -> None:
    status_code, payload = process_webhook(
        method="POST",
        raw_path="/webhook?token=secret-token",
        body=b"{not-json}",
        config=_config(),
        sender=lambda _config, _text: None,
    )

    assert status_code == 400
    assert payload["ok"] is False


def test_process_webhook_rejects_non_object_json() -> None:
    status_code, payload = process_webhook(
        method="POST",
        raw_path="/webhook?token=secret-token",
        body=b'["not-an-object"]',
        config=_config(),
        sender=lambda _config, _text: None,
    )

    assert status_code == 400
    assert payload["ok"] is False


def test_send_telegram_message_raises_on_bad_api_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Response:
        status = 200

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return b'{"ok": false, "description": "chat not found"}'

    def fake_urlopen(request, timeout):
        return _Response()

    monkeypatch.setattr("mcp_telegram_relay.cli.urlopen", fake_urlopen)

    with pytest.raises(RelayConfigError, match="chat not found"):
        send_telegram_message(_config(token=None), "hello")
