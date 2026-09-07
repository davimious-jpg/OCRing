from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .checkpoint import CheckpointManager, SessionState


@dataclass(frozen=True)
class RecoveryScanResult:
    session_id: str
    latest_checkpoint: Path | None
    stale_checkpoints: tuple[Path, ...]


@dataclass(frozen=True)
class ResumedSession:
    session_state: SessionState
    next_frame_index: int


class RecoveryManager:
    def __init__(self, checkpoint_root: Path) -> None:
        self.checkpoint_root = checkpoint_root
        self.checkpoint_manager = CheckpointManager(checkpoint_root)

    def scan_for_checkpoints(self, session_id: str) -> RecoveryScanResult:
        session_dir = self.checkpoint_root / session_id
        latest_checkpoint = None
        stale: list[Path] = list(self.checkpoint_manager.cleanup_stale_checkpoints(session_id, max_age_seconds=3600))
        if session_dir.exists():
            checkpoint_path = session_dir / "latest_checkpoint.json"
            if checkpoint_path.exists():
                latest_checkpoint = checkpoint_path
            stale = [path for path in session_dir.glob("*.tmp") if path.is_file()]
        return RecoveryScanResult(
            session_id=session_id,
            latest_checkpoint=latest_checkpoint,
            stale_checkpoints=tuple(sorted(stale)),
        )

    def get_recovery_options(self, session_id: str) -> tuple[str, ...]:
        scan = self.scan_for_checkpoints(session_id)
        if scan.latest_checkpoint is not None or scan.stale_checkpoints:
            return ("resume", "discard")
        return ("start_fresh",)

    def resume_from_last_checkpoint(self, session_id: str) -> ResumedSession:
        scan = self.scan_for_checkpoints(session_id)
        if scan.latest_checkpoint is None:
            raise FileNotFoundError(f"No checkpoint available for {session_id!r}")
        state = self.checkpoint_manager.load_checkpoint(scan.latest_checkpoint)
        return ResumedSession(
            session_state=state,
            next_frame_index=_next_frame_index(state.last_frame_id),
        )

    def discard_and_start_fresh(self, session_id: str) -> tuple[Path, ...]:
        scan = self.scan_for_checkpoints(session_id)
        removed: list[Path] = []
        if scan.latest_checkpoint is not None and scan.latest_checkpoint.exists():
            scan.latest_checkpoint.unlink()
            removed.append(scan.latest_checkpoint)
        for path in scan.stale_checkpoints:
            if path.exists():
                path.unlink()
                removed.append(path)
        return tuple(removed)


def _next_frame_index(last_frame_id: str) -> int:
    digits = []
    for character in reversed(last_frame_id):
        if character.isdigit():
            digits.append(character)
        elif digits:
            break
    if not digits:
        return 0
    return int("".join(reversed(digits)))
