from __future__ import annotations

from pathlib import Path

from ocring.ocr.checkpoint import CheckpointManager
from ocring.ocr.recovery import RecoveryManager


def _write_checkpoint(manager: CheckpointManager, session_id: str, last_frame_id: str) -> Path:
    path = manager.checkpoint_path_for_session(session_id)
    state = manager.build_session_state(
        report={
            "profile_id": "defiance",
            "frame_reports": [{"frame": {"session_id": session_id, "frame_id": last_frame_id}}],
            "assembled_records": [],
            "continuity_records": [],
            "frame_overlaps": [],
        },
        buffer_metadata={},
    )
    manager.save_checkpoint(state, path)
    return path


def test_scan_detects_crash_tmp_and_checkpoint(tmp_path: Path) -> None:
    recovery = RecoveryManager(tmp_path)
    manager = recovery.checkpoint_manager
    _write_checkpoint(manager, "session-001", "frame-009")
    stale = tmp_path / "session-001" / "latest_checkpoint.json.tmp"
    stale.write_text("{}", encoding="utf-8")

    scan = recovery.scan_for_checkpoints("session-001")

    assert scan.latest_checkpoint is not None
    assert scan.stale_checkpoints == (stale,)


def test_resume_from_last_checkpoint_returns_next_index(tmp_path: Path) -> None:
    recovery = RecoveryManager(tmp_path)
    _write_checkpoint(recovery.checkpoint_manager, "session-001", "frame-009")

    resumed = recovery.resume_from_last_checkpoint("session-001")

    assert resumed.session_state.session_id == "session-001"
    assert resumed.next_frame_index == 9


def test_discard_flow_removes_checkpoint_and_tmp(tmp_path: Path) -> None:
    recovery = RecoveryManager(tmp_path)
    checkpoint = _write_checkpoint(recovery.checkpoint_manager, "session-001", "frame-009")
    stale = tmp_path / "session-001" / "latest_checkpoint.json.tmp"
    stale.write_text("{}", encoding="utf-8")

    removed = recovery.discard_and_start_fresh("session-001")

    assert checkpoint in removed
    assert stale in removed
    assert not checkpoint.exists()
    assert not stale.exists()
