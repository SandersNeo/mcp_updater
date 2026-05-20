from __future__ import annotations

import json
import os
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen


class RelayConfigError(Exception):
    pass


@dataclass(slots=True)
class RelayConfig:
    host: str
    port: int
    path: str
    token: str | None
    telegram_bot_token: str
    telegram_chat_id: str
    telegram_thread_id: int | None
    message_prefix: str


TelegramSender = Callable[[RelayConfig, str], None]


def load_config_from_env(env: dict[str, str] | None = None) -> RelayConfig:
    env = env or os.environ
    bot_token = _require_env(env, "TELEGRAM_BOT_TOKEN")
    chat_id = _require_env(env, "TELEGRAM_CHAT_ID")
    host = env.get("RELAY_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = _parse_port(env.get("RELAY_PORT", "8787"))
    path = _normalize_path(env.get("RELAY_PATH", "/webhook"))
    token = _optional_env(env, "RELAY_TOKEN")
    thread_id = _parse_optional_int(env.get("TELEGRAM_THREAD_ID"), "TELEGRAM_THREAD_ID")
    message_prefix = env.get("TELEGRAM_MESSAGE_PREFIX", "MCP updater").strip() or "MCP updater"
    return RelayConfig(
        host=host,
        port=port,
        path=path,
        token=token,
        telegram_bot_token=bot_token,
        telegram_chat_id=chat_id,
        telegram_thread_id=thread_id,
        message_prefix=message_prefix,
    )


def format_notification_message(payload: dict, *, prefix: str) -> str:
    lines = [
        prefix,
        f"project: {payload.get('project', '<unknown>')}",
        f"status: {payload.get('status', '<unknown>')}",
        f"stage: {payload.get('stage', '<unknown>')}",
    ]
    if payload.get("targetCommit"):
        lines.append(f"targetCommit: {payload['targetCommit']}")
    if payload.get("lastIndexedCommit"):
        lines.append(f"lastIndexedCommit: {payload['lastIndexedCommit']}")
    lines.append(f"productionUntouched: {payload.get('productionUntouched')}")
    lines.append(f"rollbackAttempted: {payload.get('rollbackAttempted')}")
    lines.append(f"rollbackSuccess: {payload.get('rollbackSuccess')}")
    if payload.get("logPath"):
        lines.append(f"logPath: {payload['logPath']}")
    return "\n".join(lines)


def process_webhook(
    method: str,
    raw_path: str,
    body: bytes,
    config: RelayConfig,
    *,
    sender: TelegramSender,
) -> tuple[int, dict[str, object]]:
    if method.upper() != "POST":
        return 405, {"ok": False, "error": "method_not_allowed"}

    parsed = urlsplit(raw_path)
    if _normalize_path(parsed.path) != config.path:
        return 404, {"ok": False, "error": "not_found"}

    if config.token:
        provided = parse_qs(parsed.query).get("token", [None])[0]
        if provided != config.token:
            return 403, {"ok": False, "error": "forbidden"}

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 400, {"ok": False, "error": "invalid_json"}

    if not isinstance(payload, dict):
        return 400, {"ok": False, "error": "invalid_payload"}

    text = format_notification_message(payload, prefix=config.message_prefix)
    sender(config, text)
    return 200, {"ok": True}


def send_telegram_message(config: RelayConfig, text: str) -> None:
    payload: dict[str, object] = {
        "chat_id": config.telegram_chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if config.telegram_thread_id is not None:
        payload["message_thread_id"] = config.telegram_thread_id

    request = Request(
        f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        body = response.read().decode("utf-8", errors="replace")
        if response.status >= 400:
            raise RelayConfigError(f"Telegram API returned HTTP {response.status}: {body}")
    try:
        response_payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RelayConfigError("Telegram API returned invalid JSON response.") from exc
    if not response_payload.get("ok", False):
        description = str(response_payload.get("description", "unknown Telegram API error"))
        raise RelayConfigError(f"Telegram API returned error: {description}")


def make_handler(config: RelayConfig, sender: TelegramSender) -> type[BaseHTTPRequestHandler]:
    class RelayHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self._handle()

        def do_GET(self) -> None:  # noqa: N802
            self._handle()

        def log_message(self, format: str, *args: object) -> None:
            return

        def _handle(self) -> None:
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length) if content_length > 0 else b""
            status, payload = process_webhook(
                self.command,
                self.path,
                body,
                config,
                sender=sender,
            )
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return RelayHandler


def main() -> int:
    config = load_config_from_env()
    server = ThreadingHTTPServer((config.host, config.port), make_handler(config, send_telegram_message))
    print(f"Telegram relay listening on http://{config.host}:{config.port}{config.path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _require_env(env: dict[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise RelayConfigError(f"Environment variable '{name}' is required.")
    return value


def _optional_env(env: dict[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_path(value: str | None) -> str:
    value = (value or "/webhook").strip() or "/webhook"
    if not value.startswith("/"):
        value = "/" + value
    if value != "/" and value.endswith("/"):
        value = value.rstrip("/")
    return value


def _parse_port(value: str | None) -> int:
    try:
        port = int((value or "8787").strip())
    except ValueError as exc:
        raise RelayConfigError("Environment variable 'RELAY_PORT' must be an integer.") from exc
    if port <= 0:
        raise RelayConfigError("Environment variable 'RELAY_PORT' must be greater than 0.")
    return port


def _parse_optional_int(value: str | None, name: str) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        return int(value.strip())
    except ValueError as exc:
        raise RelayConfigError(f"Environment variable '{name}' must be an integer when provided.") from exc
