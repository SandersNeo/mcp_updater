from __future__ import annotations

import hashlib
from pathlib import Path

from .source_detector import SourceDetectionResult


def compute_report_hash(report_path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(report_path.read_bytes())
    return digest.hexdigest()


def compute_source_fingerprint(source_result: SourceDetectionResult) -> str:
    digest = hashlib.sha256()

    if source_result.main_path is not None:
        _update_digest_for_directory(digest, source_result.main_path, prefix="main")
    if source_result.extension_path is not None:
        _update_digest_for_directory(digest, source_result.extension_path, prefix="extension")
    if source_result.native_report_path is not None:
        _update_digest_for_file(digest, source_result.native_report_path, prefix="native-report")

    return digest.hexdigest()


def _update_digest_for_directory(digest: "hashlib._Hash", root: Path, *, prefix: str) -> None:
    digest.update(f"{prefix}:{root.name}\n".encode("utf-8"))
    for file_path in sorted(path for path in root.rglob("*") if path.is_file()):
        relative_path = file_path.relative_to(root).as_posix()
        digest.update(f"{prefix}:{relative_path}\n".encode("utf-8"))
        digest.update(file_path.read_bytes())


def _update_digest_for_file(digest: "hashlib._Hash", file_path: Path, *, prefix: str) -> None:
    digest.update(f"{prefix}:{file_path.name}\n".encode("utf-8"))
    digest.update(file_path.read_bytes())
