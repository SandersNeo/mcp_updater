from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigValidationError


@dataclass(slots=True)
class SettingsConfig:
    global_file: Path
    values: dict[str, Any]


def load_global_settings(path: Path) -> SettingsConfig:
    if not path.exists():
        return SettingsConfig(global_file=path, values={})

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigValidationError(f"Invalid JSON in settings file '{path}': {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigValidationError(f"Settings file must contain a JSON object: {path}")

    return SettingsConfig(global_file=path, values=raw)


def get_mapping(settings: SettingsConfig, path: tuple[str, ...]) -> dict[str, Any]:
    current: Any = settings.values
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return {}
        current = current[key]
    if not isinstance(current, dict):
        dotted = ".".join(path)
        raise ConfigValidationError(f"Field '{dotted}' in settings file must be an object.")
    return current
