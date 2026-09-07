from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any


@dataclass(frozen=True)
class SessionState:
    session_id: str
    last_frame_id: str
    continuity_state: list[dict[str, Any]]
    overlap_provenance: list[dict[str, Any]]
    assembled_records: list[dict[str, Any]]
    buffer_metadata: dict[str, Any]
    profile_id: str
    profile_version: str
    timestamp: str


class CheckpointManager:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir

    def save_checkpoint(self, session_state: SessionState, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        payload = json.dumps(asdict(session_state), indent=2)
        tmp_path.write_text(payload, encoding="utf-8")
        self._replace_with_retry(tmp_path, path)
        return path

    def load_checkpoint(self, path: Path) -> SessionState:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return SessionState(**payload)

    def cleanup_stale_checkpoints(self, session_id: str, *, max_age_seconds: int | None = None) -> tuple[Path, ...]:
        session_dir = self.root_dir / session_id
        if not session_dir.exists():
            return ()
        removed: list[Path] = []
        for path in session_dir.glob("*.tmp"):
            if path.is_file() and self._should_remove_tmp(path, max_age_seconds=max_age_seconds):
                path.unlink()
                removed.append(path)
        return tuple(removed)

    def checkpoint_path_for_session(self, session_id: str) -> Path:
        session_dir = self.root_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir / "latest_checkpoint.json"

    def build_session_state(
        self,
        *,
        report: dict[str, Any],
        buffer_metadata: dict[str, Any],
        profile_version: str = "1",
    ) -> SessionState:
        frame_reports = report.get("frame_reports", [])
        session_id = "session-unknown"
        last_frame_id = ""
        if frame_reports:
            session_id = str(frame_reports[0].get("frame", {}).get("session_id") or session_id)
            last_frame_id = str(frame_reports[-1].get("frame", {}).get("frame_id") or "")
        return SessionState(
            session_id=session_id,
            last_frame_id=last_frame_id,
            continuity_state=list(report.get("continuity_records", [])),
            overlap_provenance=list(report.get("frame_overlaps", [])),
            assembled_records=list(report.get("assembled_records", [])),
            buffer_metadata=dict(buffer_metadata),
            profile_id=str(report.get("profile_id") or ""),
            profile_version=profile_version,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def _replace_with_retry(self, tmp_path: Path, path: Path, *, attempts: int = 3) -> None:
        last_error: OSError | None = None
        for attempt in range(1, attempts + 1):
            try:
                os.replace(tmp_path, path)
                return
            except OSError as error:
                last_error = error
                if attempt >= attempts:
                    break
                time.sleep(0.1 * attempt)
        if last_error is not None:
            raise last_error

    def _should_remove_tmp(self, path: Path, *, max_age_seconds: int | None) -> bool:
        if max_age_seconds is None:
            return True
        age_seconds = time.time() - path.stat().st_mtime
        return age_seconds >= max_age_seconds
