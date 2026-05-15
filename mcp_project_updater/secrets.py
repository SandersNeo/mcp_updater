from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigValidationError


@dataclass(slots=True)
class SecretsConfig:
    global_file: Path
    project_file: Path


def load_secrets(config: SecretsConfig) -> dict[str, str]:
    secrets: dict[str, str] = {}
    secrets.update(_load_secret_file(config.global_file, required=False))
    secrets.update(_load_secret_file(config.project_file, required=False))
    return secrets


def _load_secret_file(path: Path, *, required: bool) -> dict[str, str]:
    if not path.exists():
        if required:
            raise ConfigValidationError(f"Secrets file does not exist: {path}")
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigValidationError(f"Invalid JSON in secrets file '{path}': {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigValidationError(f"Secrets file must contain a JSON object: {path}")

    return {str(key): _coerce_secret_value(value, path, str(key)) for key, value in raw.items()}


def _coerce_secret_value(value: Any, path: Path, key: str) -> str:
    if not isinstance(value, str) or value == "":
        raise ConfigValidationError(f"Secret '{key}' in '{path}' must be a non-empty string.")
    return value
