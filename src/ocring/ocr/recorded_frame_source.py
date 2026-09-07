from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from PIL import Image

from .capture_backend import CaptureBackend, CaptureStatus, get_foreground_window_handle
from .event_bus import EventBus, UIEvent

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
RECORDING_MANIFEST = "recording_manifest.json"
STATIC_FRAME_DIFF_THRESHOLD = 3.0
MIN_USEFUL_FRAME_INTERVAL_SECONDS = 1.0
HIGH_MOTION_DIFF_THRESHOLD = 8.0
PERCEPTUAL_SIGNATURE_SIZE = (32, 18)
# A perfectly static dwell (no scroll motion) previously collapsed to exactly one
# retained frame forever, because static-duplicate suppression had no time-based
# re-admission. Temporal identity stabilization needs >=2 independent frames per
# real row observation (see temporal.merge_ranked_candidates), so a dwell that
# never re-admits a second frame can never produce a corroborated identity no
# matter how long the user holds still. These two constants bound that repair:
# re-admit a static-duplicate frame as a fresh independent observation once, if
# enough time has passed since the last kept frame, up to a small per-dwell cap.
DWELL_REOBSERVATION_INTERVAL_SECONDS = 0.4
MAX_KEPT_FRAMES_PER_DWELL = 3
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecordedFrame:
    sequence_id: int
    frame_id: str
    session_id: str
    image_path: Path
    capture_timestamp: float
    timestamp_utc: str
    content_hash: str


@dataclass(frozen=True)
class CaptureFormatDecision:
    selected_format: str
    reasons: tuple[str, ...]
    rejected_formats: dict[str, tuple[str, ...]]

    def as_dict(self) -> dict[str, object]:
        return {
            "selected_format": self.selected_format,
            "reasons": list(self.reasons),
            "rejected_formats": {key: list(value) for key, value in self.rejected_formats.items()},
        }


@dataclass(frozen=True)
class RecordingSummary:
    recording_dir: Path
    session_id: str
    requested_fps: float
    duration_seconds: float
    source_frames: int
    dropped_frames: int
    achieved_fps: float
    bytes_written: int
    disk_write_mbps: float
    memory_growth_bytes: int
    sequence_gaps: int
    first_sequence_id: int
    last_sequence_id: int
    cpu_user_seconds: float
    cpu_system_seconds: float

    def as_dict(self) -> dict[str, object]:
        return {
            "recording_dir": str(self.recording_dir),
            "session_id": self.session_id,
            "requested_fps": self.requested_fps,
            "duration_seconds": self.duration_seconds,
            "source_frames": self.source_frames,
            "dropped_frames": self.dropped_frames,
            "achieved_fps": self.achieved_fps,
            "bytes_written": self.bytes_written,
            "disk_write_mbps": self.disk_write_mbps,
            "memory_growth_bytes": self.memory_growth_bytes,
            "sequence_gaps": self.sequence_gaps,
            "first_sequence_id": self.first_sequence_id,
            "last_sequence_id": self.last_sequence_id,
            "cpu_user_seconds": self.cpu_user_seconds,
            "cpu_system_seconds": self.cpu_system_seconds,
        }


class FrameSpoolRecorder:
    """Low-overhead recorder that stores chronological external pixel evidence."""

    def __init__(
        self,
        *,
        capture_backend: CaptureBackend,
        recording_dir: Path,
        session_id: str,
        target_window_handle: int | None,
        target_visible: bool = True,
        requested_fps: float = 12.0,
        event_bus: EventBus | None = None,
    ) -> None:
        self.capture_backend = capture_backend
        self.recording_dir = Path(recording_dir)
        self.session_id = session_id
        self.target_window_handle = target_window_handle
        self.target_visible = target_visible
        self.requested_fps = max(1.0, float(requested_fps))
        self.event_bus = event_bus
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._summary: RecordingSummary | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if self.running:
            return False
        self.recording_dir.mkdir(parents=True, exist_ok=True)
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name=f"ocring-recorder-{self.session_id}", daemon=True)
        self._thread.start()
        return True

    def stop(self, *, timeout: float = 5.0) -> RecordingSummary:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                raise TimeoutError("recorder did not stop before timeout; spool preserved")
        if self._summary is None:
            self._summary = recover_recording_summary_from_spool(
                self.recording_dir,
                session_id=self.session_id,
                requested_fps=self.requested_fps,
            )
        self._summary = reconcile_recording_summary_with_spool(self.recording_dir, self._summary)
        if self._summary.source_frames > 0:
            finalize_recording(self.recording_dir, self._summary)
        return self._summary

    def _run(self) -> None:
        try:
            self._record_loop()
        except Exception as error:  # pragma: no cover - defensive thread boundary.
            LOGGER.exception("Frame spool recorder stopped unexpectedly")
            if self.event_bus is not None:
                self.event_bus.publish(
                    UIEvent.RECORDER_START_FAILED,
                    {
                        "session_id": self.session_id,
                        "reason": f"{type(error).__name__}: {error}",
                        "recording_dir": str(self.recording_dir),
                    },
                )
            self._summary = _empty_recording_summary(
                recording_dir=self.recording_dir,
                session_id=self.session_id,
                requested_fps=self.requested_fps,
            )

    def _record_loop(self) -> None:
        interval = 1.0 / self.requested_fps
        start = time.perf_counter()
        start_wall = time.time()
        start_process = time.process_time()
        start_memory = _process_memory_bytes()
        source_frames = 0
        dropped_frames = 0
        bytes_written = 0
        sequence_ids: list[int] = []
        while not self._stop_event.is_set():
            loop_start = time.perf_counter()
            sequence_id = source_frames + dropped_frames + 1
            frame = self.capture_backend.capture(
                target_window_handle=self.target_window_handle,
                foreground_window_handle=get_foreground_window_handle(),
                target_visible=self.target_visible,
            )
            if frame.status is CaptureStatus.CAPTURE_ACTIVE and frame.image_path and validate_recorded_frame(Path(frame.image_path)):
                destination = self.recording_dir / f"frame-{sequence_id:06d}.png"
                shutil.copy2(frame.image_path, destination)
                bytes_written += destination.stat().st_size
                source_frames += 1
                sequence_ids.append(sequence_id)
                capture_timestamp = _frame_capture_timestamp(frame)
                if self.event_bus is not None:
                    if source_frames == 1:
                        self.event_bus.publish(
                            UIEvent.FIRST_FRAME_RECORDED,
                            {
                                "session_id": self.session_id,
                                "frame_id": destination.stem,
                                "sequence_id": sequence_id,
                                "capture_timestamp": capture_timestamp,
                                "recording_dir": str(self.recording_dir),
                            },
                        )
                    self.event_bus.publish(
                        UIEvent.FRAME_CAPTURED,
                        {
                            "session_id": self.session_id,
                            "frame_id": destination.stem,
                            "sequence_id": sequence_id,
                            "capture_timestamp": capture_timestamp,
                            "window_handle": self.target_window_handle,
                            "recording_dir": str(self.recording_dir),
                            "recording_frame_count": source_frames,
                            "buffer_bytes": bytes_written,
                        },
                    )
            else:
                dropped_frames += 1
            elapsed = time.perf_counter() - loop_start
            sleep_for = interval - elapsed
            if sleep_for > 0:
                self._stop_event.wait(sleep_for)
        duration = max(0.0, time.perf_counter() - start)
        cpu_seconds = max(0.0, time.process_time() - start_process)
        self._summary = RecordingSummary(
            recording_dir=self.recording_dir,
            session_id=self.session_id,
            requested_fps=self.requested_fps,
            duration_seconds=round(duration, 3),
            source_frames=source_frames,
            dropped_frames=dropped_frames,
            achieved_fps=round(source_frames / duration, 3) if duration else 0.0,
            bytes_written=bytes_written,
            disk_write_mbps=round((bytes_written / (1024 * 1024)) / duration, 3) if duration else 0.0,
            memory_growth_bytes=max(0, _process_memory_bytes() - start_memory),
            sequence_gaps=_sequence_gaps(sequence_ids),
            first_sequence_id=sequence_ids[0] if sequence_ids else 0,
            last_sequence_id=sequence_ids[-1] if sequence_ids else 0,
            cpu_user_seconds=round(cpu_seconds, 3),
            cpu_system_seconds=0.0,
        )
        del start_wall


class RecordedFrameSource:
    """Chronological frame spool that feeds the existing OCRing pipeline."""

    def __init__(self, frames: Iterable[RecordedFrame]) -> None:
        self._frames = tuple(
            sorted(frames, key=lambda recorded: (recorded.sequence_id, recorded.capture_timestamp, str(recorded.image_path)))
        )

    @classmethod
    def from_directory(
        cls,
        directory: Path,
        *,
        session_id: str = "recorded-session",
        require_finalized: bool = False,
    ) -> "RecordedFrameSource":
        if require_finalized:
            load_finalized_recording_manifest(directory)
        image_paths = tuple(
            sorted(
                path
                for path in Path(directory).iterdir()
                if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg"}
            )
        )
        frames: list[RecordedFrame] = []
        for sequence_id, image_path in enumerate(image_paths, start=1):
            frames.append(
                RecordedFrame(
                    sequence_id=sequence_id,
                    frame_id=f"{session_id}-recorded-frame-{sequence_id:06d}",
                    session_id=session_id,
                    image_path=image_path,
                    capture_timestamp=image_path.stat().st_mtime,
                    timestamp_utc=datetime.fromtimestamp(image_path.stat().st_mtime, timezone.utc).isoformat(),
                    content_hash=_file_hash(image_path),
                )
            )
        return cls(frames)

    def frames(self) -> tuple[RecordedFrame, ...]:
        return self._frames

    def useful_frames(self) -> tuple[RecordedFrame, ...]:
        return select_useful_recorded_frames(self._frames)

    def useful_frame_selection_report(self) -> dict[str, object]:
        return recorded_frame_selection_report(self._frames)

    def as_dict(self) -> dict[str, object]:
        return {
            "frame_count": len(self._frames),
            "sequence_ids": [frame.sequence_id for frame in self._frames],
            "first_timestamp_utc": self._frames[0].timestamp_utc if self._frames else "",
            "last_timestamp_utc": self._frames[-1].timestamp_utc if self._frames else "",
        }


def capture_format_decision() -> CaptureFormatDecision:
    return CaptureFormatDecision(
        selected_format="segmented_frame_spool",
        reasons=(
            "LOW_GAMEPLAY_ENCODE_OVERHEAD",
            "EXACT_FRAME_ORDER_AND_TIMESTAMPS",
            "RANDOM_ACCESS_FOR_NEIGHBORING_FRAME_OCR",
            "DIRECT_COMPATIBILITY_WITH_EXISTING_IMAGE_PIPELINE",
        ),
        rejected_formats={
            "encoded_video": (
                "LOWER_STORAGE_SIZE",
                "BUT_HIGHER_ENCODE_OR_DECODE_DEPENDENCY_AND_RANDOM_ACCESS_COST",
            ),
            "compressed_frame_stream": (
                "PROMISING_FUTURE_FORMAT",
                "BUT_REQUIRES_NEW_STREAM_CONTAINER_AND_INDEXING_BEFORE_PIPELINE_FEED",
            ),
        },
    )


def select_useful_recorded_frames(frames: Iterable[RecordedFrame]) -> tuple[RecordedFrame, ...]:
    return tuple(recorded_frame_selection_report(frames)["useful_frames"])


def recorded_frame_selection_report(frames: Iterable[RecordedFrame]) -> dict[str, object]:
    useful: list[RecordedFrame] = []
    source_frames = tuple(sorted(frames, key=lambda item: (item.sequence_id, item.capture_timestamp)))
    previous_hash = ""
    previous_signature: tuple[int, ...] | None = None
    exact_duplicates = 0
    static_duplicates = 0
    temporal_redundant = 0
    dwell_reobservations = 0
    last_useful_timestamp: float | None = None
    frames_kept_in_dwell = 0
    for frame in source_frames:
        if frame.content_hash == previous_hash:
            exact_duplicates += 1
            continue
        signature = _perceptual_signature(frame.image_path)
        difference = float("inf")
        if previous_signature is not None and signature is not None:
            difference = _mean_absolute_difference(previous_signature, signature)
        if difference <= STATIC_FRAME_DIFF_THRESHOLD:
            # Same dwell as the last kept frame. Re-admit a bounded number of
            # additional independent observations instead of suppressing every
            # frame after the first one forever, so a genuinely static row can
            # still reach the >=2-frame temporal identity requirement. The
            # dwell's anchor signature (previous_signature) is deliberately not
            # advanced here, so drift is still measured from the dwell's start.
            elapsed_since_last_kept = (
                frame.capture_timestamp - last_useful_timestamp
                if last_useful_timestamp is not None
                else float("inf")
            )
            if (
                frames_kept_in_dwell < MAX_KEPT_FRAMES_PER_DWELL
                and elapsed_since_last_kept >= DWELL_REOBSERVATION_INTERVAL_SECONDS
            ):
                useful.append(frame)
                previous_hash = frame.content_hash
                last_useful_timestamp = frame.capture_timestamp
                frames_kept_in_dwell += 1
                dwell_reobservations += 1
                continue
            static_duplicates += 1
            continue
        if (
            last_useful_timestamp is not None
            and frame.capture_timestamp - last_useful_timestamp < MIN_USEFUL_FRAME_INTERVAL_SECONDS
            and difference < HIGH_MOTION_DIFF_THRESHOLD
        ):
            temporal_redundant += 1
            continue
        useful.append(frame)
        previous_hash = frame.content_hash
        last_useful_timestamp = frame.capture_timestamp
        frames_kept_in_dwell = 1
        if signature is not None:
            previous_signature = signature
    return {
        "source_frame_count": len(source_frames),
        "useful_frames": tuple(useful),
        "useful_frame_count": len(useful),
        "exact_duplicates_removed": exact_duplicates,
        "static_redundant_frames_removed": static_duplicates,
        "temporal_redundant_frames_removed": temporal_redundant,
        "dwell_reobservation_frames_kept": dwell_reobservations,
        "duplicate_static_frames_suppressed": exact_duplicates + static_duplicates + temporal_redundant,
        "static_frame_diff_threshold": STATIC_FRAME_DIFF_THRESHOLD,
        "min_useful_frame_interval_seconds": MIN_USEFUL_FRAME_INTERVAL_SECONDS,
        "high_motion_diff_threshold": HIGH_MOTION_DIFF_THRESHOLD,
        "dwell_reobservation_interval_seconds": DWELL_REOBSERVATION_INTERVAL_SECONDS,
        "max_kept_frames_per_dwell": MAX_KEPT_FRAMES_PER_DWELL,
    }


def validate_recorded_frame(path: Path) -> bool:
    if not path.exists() or path.stat().st_size <= 0:
        return False
    if path.suffix.lower() != ".png":
        return True
    with path.open("rb") as handle:
        return handle.read(8) == PNG_SIGNATURE


def finalize_recording(recording_dir: Path, summary: RecordingSummary) -> dict[str, object]:
    """Atomically publish the marker that makes a recording immutable for extraction."""
    recording_dir = Path(recording_dir)
    verification = verify_recording_directory(recording_dir, summary=summary)
    manifest = {
        "status": "RECORDED_VERIFIED",
        "session_id": summary.session_id,
        "recording_dir": str(recording_dir),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "summary": summary.as_dict(),
        "verification": verification,
    }
    manifest_path = recording_dir / RECORDING_MANIFEST
    tmp_path = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, manifest_path)
    return manifest


def recover_recording_summary_from_spool(recording_dir: Path, *, session_id: str, requested_fps: float) -> RecordingSummary:
    verification = verify_recording_directory(recording_dir)
    frame_count = int(verification.get("frame_count", 0))
    if frame_count <= 0:
        return _empty_recording_summary(recording_dir=Path(recording_dir), session_id=session_id, requested_fps=requested_fps)
    first_timestamp = _timestamp_from_utc(str(verification.get("first_timestamp_utc") or ""))
    last_timestamp = _timestamp_from_utc(str(verification.get("last_timestamp_utc") or ""))
    duration = max(0.001, last_timestamp - first_timestamp)
    return RecordingSummary(
        recording_dir=Path(recording_dir),
        session_id=session_id,
        requested_fps=requested_fps,
        duration_seconds=round(duration, 3),
        source_frames=frame_count,
        dropped_frames=0,
        achieved_fps=round(frame_count / duration, 3),
        bytes_written=int(verification.get("total_bytes", 0)),
        disk_write_mbps=round((int(verification.get("total_bytes", 0)) / (1024 * 1024)) / duration, 3),
        memory_growth_bytes=0,
        sequence_gaps=int(verification.get("sequence_gaps", 0)),
        first_sequence_id=int(verification.get("first_sequence_id", 0)),
        last_sequence_id=int(verification.get("last_sequence_id", 0)),
        cpu_user_seconds=0.0,
        cpu_system_seconds=0.0,
    )


def reconcile_recording_summary_with_spool(recording_dir: Path, summary: RecordingSummary) -> RecordingSummary:
    verification = verify_recording_directory(recording_dir)
    frame_count = int(verification.get("frame_count", 0))
    if int(summary.source_frames) == frame_count:
        return summary
    if int(summary.source_frames) == 0 and frame_count > 0:
        return recover_recording_summary_from_spool(
            recording_dir,
            session_id=summary.session_id,
            requested_fps=summary.requested_fps,
        )
    raise ValueError(f"recording frame count mismatch: summary={summary.source_frames} files={frame_count}")


def load_finalized_recording_manifest(recording_dir: Path) -> dict[str, object]:
    manifest_path = Path(recording_dir) / RECORDING_MANIFEST
    if not manifest_path.exists():
        raise ValueError(f"recording is not finalized: missing {RECORDING_MANIFEST}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"recording manifest is unreadable: {error}") from error
    if manifest.get("status") != "RECORDED_VERIFIED":
        raise ValueError("recording manifest is not RECORDED_VERIFIED")
    verification = verify_recording_directory(Path(recording_dir))
    if int(verification.get("frame_count", 0)) <= 0:
        raise ValueError("recording has no valid frames")
    return manifest


def is_recording_finalized(recording_dir: Path | None) -> bool:
    if recording_dir is None:
        return False
    try:
        load_finalized_recording_manifest(recording_dir)
    except (OSError, ValueError):
        return False
    return True


def verify_recording_directory(recording_dir: Path, *, summary: RecordingSummary | None = None) -> dict[str, object]:
    recording_dir = Path(recording_dir)
    if not recording_dir.exists() or not recording_dir.is_dir():
        raise ValueError(f"recording directory does not exist: {recording_dir}")
    image_paths = tuple(
        sorted(path for path in recording_dir.iterdir() if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg"})
    )
    invalid_frames = [str(path.name) for path in image_paths if not validate_recorded_frame(path)]
    if invalid_frames:
        raise ValueError(f"recording contains invalid frame files: {', '.join(invalid_frames[:5])}")
    sequence_ids = [_sequence_id_from_path(path) for path in image_paths]
    sequence_ids = [sequence_id for sequence_id in sequence_ids if sequence_id > 0]
    bytes_written = sum(path.stat().st_size for path in image_paths)
    first_timestamp = image_paths[0].stat().st_mtime if image_paths else 0.0
    last_timestamp = image_paths[-1].stat().st_mtime if image_paths else 0.0
    expected_count = int(summary.source_frames) if summary is not None else len(image_paths)
    if summary is not None and len(image_paths) != expected_count:
        raise ValueError(f"recording frame count mismatch: summary={expected_count} files={len(image_paths)}")
    return {
        "frame_count": len(image_paths),
        "expected_frame_count": expected_count,
        "sequence_ids": sequence_ids,
        "first_sequence_id": sequence_ids[0] if sequence_ids else 0,
        "last_sequence_id": sequence_ids[-1] if sequence_ids else 0,
        "sequence_gaps": _sequence_gaps(sequence_ids),
        "first_timestamp_utc": datetime.fromtimestamp(first_timestamp, timezone.utc).isoformat() if first_timestamp else "",
        "last_timestamp_utc": datetime.fromtimestamp(last_timestamp, timezone.utc).isoformat() if last_timestamp else "",
        "total_bytes": bytes_written,
    }


def atomic_write_png(image: object, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("wb") as handle:
        image.save(handle, format="PNG")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)
    return path


def _file_hash(path: Path) -> str:
    digest = hashlib.sha1()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _perceptual_signature(path: Path) -> tuple[int, ...] | None:
    try:
        with Image.open(path) as image:
            return tuple(image.convert("L").resize(PERCEPTUAL_SIGNATURE_SIZE).tobytes())
    except OSError:
        LOGGER.exception("Unable to build recorded-frame perceptual signature for %s", path)
        return None


def _mean_absolute_difference(left: tuple[int, ...], right: tuple[int, ...]) -> float:
    if not left or not right or len(left) != len(right):
        return float("inf")
    return sum(abs(a - b) for a, b in zip(left, right)) / len(left)


def _empty_recording_summary(*, recording_dir: Path, session_id: str, requested_fps: float) -> RecordingSummary:
    return RecordingSummary(
        recording_dir=recording_dir,
        session_id=session_id,
        requested_fps=requested_fps,
        duration_seconds=0.0,
        source_frames=0,
        dropped_frames=0,
        achieved_fps=0.0,
        bytes_written=0,
        disk_write_mbps=0.0,
        memory_growth_bytes=0,
        sequence_gaps=0,
        first_sequence_id=0,
        last_sequence_id=0,
        cpu_user_seconds=0.0,
        cpu_system_seconds=0.0,
    )


def _frame_capture_timestamp(frame: object) -> float:
    direct = getattr(frame, "capture_timestamp", None)
    if direct not in {None, ""}:
        try:
            return float(direct)
        except (TypeError, ValueError):
            pass
    metadata = getattr(frame, "capture_metadata", {})
    if isinstance(metadata, dict):
        for key in ("capture_timestamp", "timestamp", "captured_at"):
            value = metadata.get(key)
            if value not in {None, ""}:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
    return time.time()


def _sequence_gaps(sequence_ids: list[int]) -> int:
    if len(sequence_ids) < 2:
        return 0
    gaps = 0
    for previous, current in zip(sequence_ids, sequence_ids[1:]):
        if current != previous + 1:
            gaps += max(0, current - previous - 1)
    return gaps


def _sequence_id_from_path(path: Path) -> int:
    stem = path.stem
    suffix = stem.rsplit("-", 1)[-1]
    try:
        return int(suffix)
    except ValueError:
        return 0


def _process_memory_bytes() -> int:
    try:
        import psutil  # type: ignore
    except ImportError:
        return 0
    try:
        return int(psutil.Process(os.getpid()).memory_info().rss)
    except Exception:
        return 0


def _timestamp_from_utc(value: str) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0
