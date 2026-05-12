from __future__ import annotations

import pytest

from mcp_project_updater.constants import ExitCode
from mcp_project_updater.source_detector import SourceDetectionError, detect_sources


def test_detect_sources_cf_only(tmp_path) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "cf").mkdir(parents=True)

    result = detect_sources(repo, "src/cf", False, "src/cfe", False)

    assert result.main_exists is True
    assert result.extension_exists is False


def test_detect_sources_cfe_only(tmp_path) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "cfe").mkdir(parents=True)

    result = detect_sources(repo, "src/cf", False, "src/cfe", False)

    assert result.main_exists is False
    assert result.extension_exists is True


def test_detect_sources_both(tmp_path) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "cf").mkdir(parents=True)
    (repo / "src" / "cfe").mkdir(parents=True)

    result = detect_sources(repo, "src/cf", False, "src/cfe", False)

    assert result.main_exists is True
    assert result.extension_exists is True


def test_detect_sources_none_raises(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(SourceDetectionError) as exc:
        detect_sources(repo, "src/cf", False, "src/cfe", False)

    assert exc.value.exit_code == ExitCode.MISSING_SOURCES


def test_required_main_missing_raises(tmp_path) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "cfe").mkdir(parents=True)

    with pytest.raises(SourceDetectionError) as exc:
        detect_sources(repo, "src/cf", True, "src/cfe", False)

    assert exc.value.exit_code == ExitCode.MAIN_CONFIG_REQUIRED_MISSING


def test_required_extension_missing_raises(tmp_path) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "cf").mkdir(parents=True)

    with pytest.raises(SourceDetectionError) as exc:
        detect_sources(repo, "src/cf", False, "src/cfe", True)

    assert exc.value.exit_code == ExitCode.EXTENSION_REQUIRED_MISSING
