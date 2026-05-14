from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class StateSnapshot:
    last_indexed_commit: str | None
    current_commit: str | None
    previous_commit: str | None
    last_source_fingerprint: str | None
    last_report_hash: str | None


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
    def last_source_fingerprint_path(self) -> Path:
        return self.state_root / "last_source_fingerprint"

    @property
    def last_report_hash_path(self) -> Path:
        return self.state_root / "last_report_hash"

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
            last_source_fingerprint=self.read_last_source_fingerprint(),
            last_report_hash=self.read_last_report_hash(),
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

    def read_last_source_fingerprint(self) -> str | None:
        return self._read_text_file(self.last_source_fingerprint_path)

    def write_last_source_fingerprint(self, fingerprint: str) -> None:
        self._write_text_file(self.last_source_fingerprint_path, fingerprint)

    def read_last_report_hash(self) -> str | None:
        return self._read_text_file(self.last_report_hash_path)

    def write_last_report_hash(self, report_hash: str) -> None:
        self._write_text_file(self.last_report_hash_path, report_hash)

    def _read_text_file(self, path: Path) -> str | None:
        if not path.exists():
            return None
        value = path.read_text(encoding="utf-8").strip()
        return value or None

    def _write_text_file(self, path: Path, value: str) -> None:
        self.ensure_root()
        path.write_text(f"{value}\n", encoding="utf-8")
