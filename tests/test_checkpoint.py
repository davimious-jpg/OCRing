from __future__ import annotations

import os
from pathlib import Path
import time

from ocring.ocr.checkpoint import CheckpointManager, SessionState
from ocring.ocr.recovery import RecoveryManager


def _sample_state(session_id: str = "session-001") -> SessionState:
    return SessionState(
        session_id=session_id,
        last_frame_id="frame-009",
        continuity_state=[{"continuity_key": "abc"}],
        overlap_provenance=[{"frame_a_id": "f1", "frame_b_id": "f2"}],
        assembled_records=[{"row_slot": 1}],
        buffer_metadata={"trim_count": 1},
        profile_id="defiance",
        profile_version="1",
        timestamp="2026-08-15T00:00:00+00:00",
    )


def test_save_and_load_checkpoint_round_trip(tmp_path: Path) -> None:
    manager = CheckpointManager(tmp_path)
    path = manager.checkpoint_path_for_session("session-001")
    state = _sample_state()

    manager.save_checkpoint(state, path)
    loaded = manager.load_checkpoint(path)

    assert loaded == state


def test_save_checkpoint_uses_atomic_rename_and_leaves_no_tmp(tmp_path: Path) -> None:
    manager = CheckpointManager(tmp_path)
    path = manager.checkpoint_path_for_session("session-001")

    manager.save_checkpoint(_sample_state(), path)

    assert path.exists()
    assert not path.with_suffix(path.suffix + ".tmp").exists()


def test_cleanup_stale_checkpoints_removes_tmp_files(tmp_path: Path) -> None:
    manager = CheckpointManager(tmp_path)
    session_dir = tmp_path / "session-001"
    session_dir.mkdir(parents=True)
    stale = session_dir / "latest_checkpoint.json.tmp"
    stale.write_text("{}", encoding="utf-8")

    removed = manager.cleanup_stale_checkpoints("session-001")

    assert removed == (stale,)
    assert not stale.exists()


def test_save_checkpoint_retries_atomic_replace_on_transient_lock(tmp_path: Path, monkeypatch) -> None:
    manager = CheckpointManager(tmp_path)
    path = manager.checkpoint_path_for_session("session-001")
    attempts = {"count": 0}
    original_replace = os.replace

    def flaky_replace(src: str, dst: str) -> None:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise PermissionError("transient file lock")
        original_replace(src, dst)

    monkeypatch.setattr("ocring.ocr.checkpoint.os.replace", flaky_replace)

    manager.save_checkpoint(_sample_state(), path)

    assert attempts["count"] == 3
    assert path.exists()


def test_recovery_scan_cleans_tmp_files_older_than_one_hour(tmp_path: Path) -> None:
    manager = CheckpointManager(tmp_path)
    session_dir = tmp_path / "session-001"
    session_dir.mkdir(parents=True)
    stale = session_dir / "latest_checkpoint.json.tmp"
    stale.write_text("{}", encoding="utf-8")
    old_time = time.time() - 3700
    os.utime(stale, (old_time, old_time))

    scan = RecoveryManager(tmp_path).scan_for_checkpoints("session-001")

    assert scan.stale_checkpoints == ()
    assert not stale.exists()
