from __future__ import annotations

from pathlib import Path

from mcp_project_updater.state import StateStore


def test_read_missing_last_indexed_commit(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")

    assert store.read_last_indexed_commit() is None


def test_read_write_current_and_previous_commit(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")

    store.write_current_commit("abc123")
    store.write_previous_commit("def456")

    assert store.read_current_commit() == "abc123"
    assert store.read_previous_commit() == "def456"


def test_read_snapshot(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    store.write_last_indexed_commit("aaa")
    store.write_current_commit("bbb")
    store.write_previous_commit("ccc")

    snapshot = store.read_snapshot()

    assert snapshot.last_indexed_commit == "aaa"
    assert snapshot.current_commit == "bbb"
    assert snapshot.previous_commit == "ccc"
