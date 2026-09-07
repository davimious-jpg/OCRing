from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from ocring.ocr.capture_backend import CaptureBackendKind, CaptureFrame, CaptureStatus
from ocring.ocr.event_bus import EventBus, UIEvent
from ocring.ocr.recorded_frame_source import (
    FrameSpoolRecorder,
    RECORDING_MANIFEST,
    RecordedFrameSource,
    atomic_write_png,
    capture_format_decision,
    finalize_recording,
    reconcile_recording_summary_with_spool,
    recorded_frame_selection_report,
    select_useful_recorded_frames,
    validate_recorded_frame,
)


def test_recorded_frame_source_preserves_chronological_sequence(tmp_path: Path) -> None:
    first = tmp_path / "frame-000001.png"
    second = tmp_path / "frame-000002.png"
    Image.new("RGB", (8, 8), (10, 10, 10)).save(first)
    Image.new("RGB", (8, 8), (20, 20, 20)).save(second)

    source = RecordedFrameSource.from_directory(tmp_path, session_id="session-recorded")
    frames = source.frames()

    assert [frame.sequence_id for frame in frames] == [1, 2]
    assert [frame.frame_id for frame in frames] == [
        "session-recorded-recorded-frame-000001",
        "session-recorded-recorded-frame-000002",
    ]


def test_recorded_frame_source_reduces_adjacent_static_duplicates(tmp_path: Path) -> None:
    paths = [tmp_path / f"frame-{index:06d}.png" for index in range(1, 4)]
    Image.new("RGB", (8, 8), (10, 10, 10)).save(paths[0])
    Image.new("RGB", (8, 8), (10, 10, 10)).save(paths[1])
    Image.new("RGB", (8, 8), (20, 20, 20)).save(paths[2])
    source = RecordedFrameSource.from_directory(tmp_path, session_id="session-recorded")

    useful = select_useful_recorded_frames(source.frames())

    assert [frame.sequence_id for frame in useful] == [1, 3]


def test_recorded_frame_source_reduces_near_static_png_variants(tmp_path: Path) -> None:
    paths = [tmp_path / f"frame-{index:06d}.png" for index in range(1, 4)]
    Image.new("RGB", (32, 18), (10, 10, 10)).save(paths[0])
    Image.new("RGB", (32, 18), (11, 11, 11)).save(paths[1])
    Image.new("RGB", (32, 18), (40, 40, 40)).save(paths[2])
    source = RecordedFrameSource.from_directory(tmp_path, session_id="session-recorded")

    report = recorded_frame_selection_report(source.frames())

    assert [frame.sequence_id for frame in report["useful_frames"]] == [1, 3]
    assert report["exact_duplicates_removed"] == 0
    assert report["static_redundant_frames_removed"] == 1


def test_recorded_frame_source_requires_finalized_manifest_when_requested(tmp_path: Path) -> None:
    Image.new("RGB", (8, 8), (10, 10, 10)).save(tmp_path / "frame-000001.png")

    try:
        RecordedFrameSource.from_directory(tmp_path, session_id="session-recorded", require_finalized=True)
    except ValueError as error:
        assert "not finalized" in str(error)
    else:
        raise AssertionError("expected unfinalized recording to be rejected")


def test_finalize_recording_publishes_manifest_after_valid_frames(tmp_path: Path) -> None:
    frame_path = tmp_path / "frame-000001.png"
    Image.new("RGB", (8, 8), (10, 10, 10)).save(frame_path)
    summary = _summary(tmp_path, source_frames=1, bytes_written=frame_path.stat().st_size)

    manifest = finalize_recording(tmp_path, summary)
    source = RecordedFrameSource.from_directory(tmp_path, session_id="session-recorded", require_finalized=True)

    assert (tmp_path / RECORDING_MANIFEST).exists()
    assert manifest["status"] == "RECORDED_VERIFIED"
    assert manifest["verification"]["frame_count"] == 1
    assert manifest["verification"]["sequence_ids"] == [1]
    assert source.frames()[0].sequence_id == 1


def test_finalize_recording_rejects_mismatched_frame_count(tmp_path: Path) -> None:
    Image.new("RGB", (8, 8), (10, 10, 10)).save(tmp_path / "frame-000001.png")

    try:
        finalize_recording(tmp_path, _summary(tmp_path, source_frames=2))
    except ValueError as error:
        assert "frame count mismatch" in str(error)
    else:
        raise AssertionError("expected frame count mismatch to be rejected")


def test_recorded_capture_format_prefers_segmented_frame_spool() -> None:
    decision = capture_format_decision()

    assert decision.selected_format == "segmented_frame_spool"
    assert "encoded_video" in decision.rejected_formats
    assert "DIRECT_COMPATIBILITY_WITH_EXISTING_IMAGE_PIPELINE" in decision.reasons


def test_atomic_write_png_produces_valid_png(tmp_path: Path) -> None:
    path = tmp_path / "capture.png"

    atomic_write_png(Image.new("RGB", (8, 8), (30, 30, 30)), path)

    assert validate_recorded_frame(path)


def test_frame_spool_recorder_publishes_first_frame_from_capture_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (8, 8), (30, 30, 30)).save(source)

    class OneFrameBackend:
        def __init__(self) -> None:
            self.calls = 0
            self.on_first_capture = lambda: None

        def capture(self, **_kwargs) -> CaptureFrame:
            self.calls += 1
            status = CaptureStatus.CAPTURE_ACTIVE if self.calls == 1 else CaptureStatus.CAPTURE_PAUSED
            if self.calls == 1:
                self.on_first_capture()
            return CaptureFrame(
                backend=CaptureBackendKind.REGION_SCREENSHOT_FALLBACK,
                width=8,
                height=8,
                source="test",
                status=status,
                image_path=str(source) if status is CaptureStatus.CAPTURE_ACTIVE else "",
                capture_metadata={"capture_timestamp": 123.5},
            )

    bus = EventBus()
    backend = OneFrameBackend()
    recorder = FrameSpoolRecorder(
        capture_backend=backend,
        recording_dir=tmp_path / "recording",
        session_id="recording-test",
        target_window_handle=101,
        requested_fps=30,
        event_bus=bus,
    )
    backend.on_first_capture = recorder._stop_event.set
    recorder.recording_dir.mkdir(parents=True, exist_ok=True)

    recorder._run()
    summary = recorder.stop()

    assert summary.source_frames >= 1
    assert (recorder.recording_dir / RECORDING_MANIFEST).exists()
    assert any(message.event_type == UIEvent.FIRST_FRAME_RECORDED for message in bus.history())
    frame_events = [message for message in bus.history() if message.event_type == UIEvent.FRAME_CAPTURED]
    assert frame_events[0].payload["capture_timestamp"] == 123.5


def test_frame_spool_recorder_summary_matches_multiple_written_frames(tmp_path: Path) -> None:
    source_paths = []
    for index in range(1, 4):
        source = tmp_path / f"source-{index}.png"
        Image.new("RGB", (8, 8), (index * 30, index * 30, index * 30)).save(source)
        source_paths.append(source)

    class ThreeFrameBackend:
        def __init__(self) -> None:
            self.calls = 0

        def capture(self, **_kwargs) -> CaptureFrame:
            self.calls += 1
            if self.calls > 3:
                return CaptureFrame(
                    backend=CaptureBackendKind.REGION_SCREENSHOT_FALLBACK,
                    width=0,
                    height=0,
                    source="test",
                    status=CaptureStatus.CAPTURE_PAUSED,
                    image_path="",
                )
            return CaptureFrame(
                backend=CaptureBackendKind.REGION_SCREENSHOT_FALLBACK,
                width=8,
                height=8,
                source="test",
                status=CaptureStatus.CAPTURE_ACTIVE,
                image_path=str(source_paths[self.calls - 1]),
                capture_metadata={"capture_timestamp": 100.0 + self.calls},
            )

    backend = ThreeFrameBackend()
    recorder = FrameSpoolRecorder(
        capture_backend=backend,
        recording_dir=tmp_path / "recording",
        session_id="recording-test",
        target_window_handle=101,
        requested_fps=60,
    )
    recorder.start()
    while backend.calls < 4:
        pass
    summary = recorder.stop()
    frame_files = sorted(recorder.recording_dir.glob("frame-*.png"))

    assert len(frame_files) == 3
    assert summary.source_frames == 3
    assert summary.first_sequence_id == 1
    assert summary.last_sequence_id == 3
    assert (recorder.recording_dir / RECORDING_MANIFEST).exists()


def test_recorder_stop_does_not_publish_manifest_when_worker_is_still_alive(tmp_path: Path) -> None:
    class HangingBackend:
        def capture(self, **_kwargs) -> CaptureFrame:
            time.sleep(0.2)
            return CaptureFrame(
                backend=CaptureBackendKind.REGION_SCREENSHOT_FALLBACK,
                width=0,
                height=0,
                source="test",
                status=CaptureStatus.CAPTURE_PAUSED,
                image_path="",
            )

    recorder = FrameSpoolRecorder(
        capture_backend=HangingBackend(),
        recording_dir=tmp_path / "recording",
        session_id="recording-test",
        target_window_handle=101,
        requested_fps=60,
    )
    recorder.start()

    try:
        recorder.stop(timeout=0.001)
    except TimeoutError as error:
        assert "spool preserved" in str(error)
    else:
        raise AssertionError("expected stop timeout to prevent finalization")

    assert not (recorder.recording_dir / RECORDING_MANIFEST).exists()
    recorder.stop(timeout=1.0)


def test_summary_zero_with_written_files_recovers_before_manifest(tmp_path: Path) -> None:
    for index in range(1, 4):
        Image.new("RGB", (8, 8), (index * 30, index * 30, index * 30)).save(tmp_path / f"frame-{index:06d}.png")

    recovered = reconcile_recording_summary_with_spool(tmp_path, _summary(tmp_path, source_frames=0))
    manifest = finalize_recording(tmp_path, recovered)

    assert recovered.source_frames == 3
    assert manifest["verification"]["frame_count"] == 3
    assert manifest["summary"]["source_frames"] == 3


def _summary(recording_dir: Path, *, source_frames: int, bytes_written: int = 0):
    return type(
        "Summary",
        (),
        {
            "recording_dir": recording_dir,
            "session_id": "session-recorded",
            "requested_fps": 12.0,
            "duration_seconds": 1.0,
            "source_frames": source_frames,
            "dropped_frames": 0,
            "achieved_fps": 1.0,
            "bytes_written": bytes_written,
            "disk_write_mbps": 0.001,
            "memory_growth_bytes": 0,
            "sequence_gaps": 0,
            "first_sequence_id": 1 if source_frames else 0,
            "last_sequence_id": source_frames,
            "cpu_user_seconds": 0.0,
            "cpu_system_seconds": 0.0,
            "as_dict": lambda self: {
                "recording_dir": str(recording_dir),
                "session_id": "session-recorded",
                "requested_fps": 12.0,
                "duration_seconds": 1.0,
                "source_frames": source_frames,
                "dropped_frames": 0,
                "achieved_fps": 1.0,
                "bytes_written": bytes_written,
                "disk_write_mbps": 0.001,
                "memory_growth_bytes": 0,
                "sequence_gaps": 0,
                "first_sequence_id": 1 if source_frames else 0,
                "last_sequence_id": source_frames,
                "cpu_user_seconds": 0.0,
                "cpu_system_seconds": 0.0,
            },
        },
    )()
