from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mcp_project_updater.lock import LockError, LockManager


def test_acquire_and_release_lock(tmp_path) -> None:
    lock_path = tmp_path / "state" / "lock"
    manager = LockManager(
        lock_path,
        "orders",
        "update",
        pid=1234,
        now_provider=lambda: datetime(2026, 5, 12, 10, 30, 0, tzinfo=timezone.utc),
        pid_checker=lambda pid: False,
    )

    info = manager.acquire()

    assert info.pid == 1234
    assert lock_path.exists()

    manager.release()

    assert not lock_path.exists()


def test_duplicate_live_lock_raises(tmp_path) -> None:
    lock_path = tmp_path / "state" / "lock"
    first = LockManager(lock_path, "orders", "update", pid=2222, pid_checker=lambda pid: False)
    first.acquire()

    second = LockManager(lock_path, "orders", "update", pid=3333, pid_checker=lambda pid: pid == 2222)

    with pytest.raises(LockError):
        second.acquire()


def test_stale_lock_is_replaced(tmp_path) -> None:
    lock_path = tmp_path / "state" / "lock"
    first = LockManager(lock_path, "orders", "update", pid=2222, pid_checker=lambda pid: False)
    first.acquire()

    second = LockManager(lock_path, "orders", "update", pid=3333, pid_checker=lambda pid: False)
    info = second.acquire()

    assert info.pid == 3333
    assert "3333" in lock_path.read_text(encoding="utf-8")
