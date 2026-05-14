from __future__ import annotations

from mcp_project_updater.fingerprints import compute_report_hash, compute_source_fingerprint
from mcp_project_updater.source_detector import detect_sources


def test_compute_report_hash_changes_with_content(tmp_path) -> None:
    report_path = tmp_path / "Report.txt"
    report_path.write_text("one", encoding="utf-8")
    first = compute_report_hash(report_path)

    report_path.write_text("two", encoding="utf-8")
    second = compute_report_hash(report_path)

    assert first != second


def test_compute_source_fingerprint_changes_with_source_content(tmp_path) -> None:
    repo = tmp_path / "repo"
    main_path = repo / "src" / "cf"
    main_path.mkdir(parents=True)
    (main_path / "module.bsl").write_text("Procedure A() EndProcedure", encoding="utf-8")

    source_result = detect_sources(repo, "src/cf", False, "src/cfe", False)
    first = compute_source_fingerprint(source_result)

    (main_path / "module.bsl").write_text("Procedure B() EndProcedure", encoding="utf-8")
    second = compute_source_fingerprint(source_result)

    assert first != second
