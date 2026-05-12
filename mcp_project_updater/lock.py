from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .constants import ExitCode
from .errors import UpdaterError


class LockError(UpdaterError):
    def __init__(self, message: str) -> None:
        super().__init__(message=message, exit_code=ExitCode.LOCK_ALREADY_EXISTS)


@dataclass(slots=True)
class LockInfo:
    pid: int
    startedAt: str
    project: str
    mode: str


class LockManager:
    def __init__(
        self,
        lock_path: Path,
        project: str,
        mode: str,
        *,
        pid: int | None = None,
        now_provider: Callable[[], datetime] | None = None,
        pid_checker: Callable[[int], bool] | None = None,
    ) -> None:
        self.lock_path = lock_path
        self.project = project
        self.mode = mode
        self.pid = pid if pid is not None else os.getpid()
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self.pid_checker = pid_checker or _default_pid_checker
        self.acquired = False

    def acquire(self) -> LockInfo:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        if self.lock_path.exists():
            existing = self.read_lock_info()
            if existing is None:
                raise LockError(f"Cannot parse lock file: {self.lock_path}")
            if self.pid_checker(existing.pid):
                raise LockError(f"Updater is already running for project '{existing.project}' (pid={existing.pid}).")

        lock_info = LockInfo(
            pid=self.pid,
            startedAt=self.now_provider().isoformat(),
            project=self.project,
            mode=self.mode,
        )
        self.lock_path.write_text(json.dumps(asdict(lock_info), ensure_ascii=False, indent=2), encoding="utf-8")
        self.acquired = True
        return lock_info

    def release(self) -> None:
        if self.lock_path.exists():
            self.lock_path.unlink()
        self.acquired = False

    def read_lock_info(self) -> LockInfo | None:
        if not self.lock_path.exists():
            return None

        try:
            raw = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

        try:
            return LockInfo(
                pid=int(raw["pid"]),
                startedAt=str(raw["startedAt"]),
                project=str(raw["project"]),
                mode=str(raw.get("mode", "update")),
            )
        except (KeyError, TypeError, ValueError):
            return None


def _default_pid_checker(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
