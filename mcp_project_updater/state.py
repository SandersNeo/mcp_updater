from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class StateSnapshot:
    last_indexed_commit: str | None
    current_commit: str | None
    previous_commit: str | None


class StateStore:
    def __init__(self, state_root: Path) -> None:
        self.state_root = state_root

    @property
    def last_indexed_commit_path(self) -> Path:
        return self.state_root / "last_indexed_commit"

    @property
    def current_commit_path(self) -> Path:
        return self.state_root / "current_commit"

    @property
    def previous_commit_path(self) -> Path:
        return self.state_root / "previous_commit"

    @property
    def lock_path(self) -> Path:
        return self.state_root / "lock"

    def ensure_root(self) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True)

    def read_snapshot(self) -> StateSnapshot:
        return StateSnapshot(
            last_indexed_commit=self.read_last_indexed_commit(),
            current_commit=self.read_current_commit(),
            previous_commit=self.read_previous_commit(),
        )

    def read_last_indexed_commit(self) -> str | None:
        return self._read_text_file(self.last_indexed_commit_path)

    def write_last_indexed_commit(self, commit: str) -> None:
        self._write_text_file(self.last_indexed_commit_path, commit)

    def read_current_commit(self) -> str | None:
        return self._read_text_file(self.current_commit_path)

    def write_current_commit(self, commit: str) -> None:
        self._write_text_file(self.current_commit_path, commit)

    def read_previous_commit(self) -> str | None:
        return self._read_text_file(self.previous_commit_path)

    def write_previous_commit(self, commit: str) -> None:
        self._write_text_file(self.previous_commit_path, commit)

    def clear_previous_commit(self) -> None:
        if self.previous_commit_path.exists():
            self.previous_commit_path.unlink()

    def _read_text_file(self, path: Path) -> str | None:
        if not path.exists():
            return None
        value = path.read_text(encoding="utf-8").strip()
        return value or None

    def _write_text_file(self, path: Path, value: str) -> None:
        self.ensure_root()
        path.write_text(f"{value}\n", encoding="utf-8")
