from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .settings import DEFAULT_SETTINGS_PATH, ensure_output_workspace
from .snapshot import build_replay_snapshot


LOGGER = logging.getLogger(__name__)


def commit_session_artifacts(
    report: dict[str, object],
    output_dir: Path | None = None,
    *,
    settings_path: Path = DEFAULT_SETTINGS_PATH,
) -> Path:
    if output_dir is None:
        output_dir = ensure_output_workspace(path=settings_path).sessions_dir
    session_id = _extract_session_id(report)
    created_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    transaction_id = f"{created_utc}-{uuid4().hex[:8]}"
    session_root = output_dir / session_id
    commit_dir = session_root / transaction_id
    staging_dir = session_root / f".{transaction_id}.staging"

    session_root.mkdir(parents=True, exist_ok=True)
    _cleanup_orphaned_staging_dirs(output_dir)

    if staging_dir.exists():
        raise FileExistsError(f"Staging directory already exists: {staging_dir}")
    if commit_dir.exists():
        raise FileExistsError(f"Commit directory already exists: {commit_dir}")
    staging_dir.mkdir()

    snapshot = build_replay_snapshot(report)
    manifest = {
        "transaction_id": transaction_id,
        "created_utc": _iso_utc_now(),
        "session_id": session_id,
        "profile_id": report.get("profile_id"),
        "frame_ids": _extract_frame_ids(report),
        "scan_scope": report.get("scan_integrity", {}).get("scan_scope"),
        "completeness_state": report.get("scan_integrity", {}).get("completeness_state"),
        "completeness_reason": report.get("scan_integrity", {}).get("completeness_reason"),
        "artifacts": {
            "report": "report.json",
            "snapshot": "snapshot.json",
            "manifest": "manifest.json",
        },
    }

    _write_json(staging_dir / "report.json", report)
    _write_json(staging_dir / "snapshot.json", snapshot)
    _write_json(staging_dir / "manifest.json", manifest)

    _rename_with_retry(staging_dir, commit_dir)
    _fsync_directory(session_root)
    return commit_dir


def load_committed_session(commit_dir: Path) -> dict[str, object]:
    return {
        "manifest": _read_json(commit_dir / "manifest.json"),
        "report": _read_json(commit_dir / "report.json"),
        "snapshot": _read_json(commit_dir / "snapshot.json"),
    }


def _extract_session_id(report: dict[str, object]) -> str:
    frame_reports = report.get("frame_reports", [])
    if frame_reports:
        frame = frame_reports[0].get("frame", {})
        session_id = frame.get("session_id")
        if session_id:
            return str(session_id)
    return "session-unknown"


def _extract_frame_ids(report: dict[str, object]) -> list[str]:
    frame_ids: list[str] = []
    for frame_report in report.get("frame_reports", []):
        frame = frame_report.get("frame", {})
        frame_id = frame.get("frame_id")
        if frame_id:
            frame_ids.append(str(frame_id))
    return frame_ids


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cleanup_orphaned_staging_dirs(output_dir: Path) -> None:
    if not output_dir.exists():
        return
    for path in output_dir.rglob("*.staging"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def _rename_with_retry(source: Path, destination: Path, *, attempts: int = 3, delay_seconds: float = 0.1) -> None:
    last_error: OSError | None = None
    for attempt in range(1, attempts + 1):
        try:
            os.rename(source, destination)
            return
        except OSError as error:
            last_error = error
            if attempt >= attempts:
                break
            LOGGER.warning(
                "session_store rename retry %s/%s failed for %s -> %s: %s",
                attempt,
                attempts,
                source,
                destination,
                error,
            )
            time.sleep(delay_seconds)
    assert last_error is not None
    raise last_error


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        fd = os.open(str(directory), flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))
