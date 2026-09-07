from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
import time
from types import SimpleNamespace

from ocring.ocr.capture_backend import CaptureBackendKind, CaptureFrame, CaptureStatus
from ocring.ocr.event_bus import EventBus, UIEvent
from ocring.ocr.normalize import build_field_candidates
from ocring.ocr.pipeline import CaptureLoop, SelectedDetailTemporalGuard, SelectedRowIdentityEpoch, _apply_selected_detail_temporal_guard, _frame_fingerprint
from ocring.ocr.models import AssembledCandidateRecord, CandidateDecision, FieldKind, OcrAttempt, OcrEngineStatus, OcrEngineSummary, PreparedFieldCrop, PreprocessVariant, RankedFieldCandidate, RecordAssemblyState, Rect, ScanScope


class _FakeCaptureBackend:
    kind = CaptureBackendKind.REGION_SCREENSHOT_FALLBACK

    def __init__(self) -> None:
        self.calls = 0

    def capture(self, target_window_handle=None, **kwargs) -> CaptureFrame:
        del target_window_handle, kwargs
        self.calls += 1
        return CaptureFrame(
            backend=self.kind,
            width=800,
            height=600,
            source="fake",
            status=CaptureStatus.CAPTURE_ACTIVE,
            image_path=f"frame-{self.calls}.png",
            window_handle=101,
            window_title="Defiance",
        )


class _SequenceCaptureBackend:
    kind = CaptureBackendKind.REGION_SCREENSHOT_FALLBACK

    def __init__(self, statuses: list[CaptureStatus], *, failure_reason: str = "FRAME_CAPTURE_FAILED") -> None:
        self.statuses = list(statuses)
        self.failure_reason = failure_reason
        self.calls = 0

    def capture(self, target_window_handle=None, **kwargs) -> CaptureFrame:
        del target_window_handle, kwargs
        self.calls += 1
        status = self.statuses[min(self.calls - 1, len(self.statuses) - 1)]
        return CaptureFrame(
            backend=self.kind,
            width=800,
            height=600,
            source="fake",
            status=status,
            reason="" if status is CaptureStatus.CAPTURE_ACTIVE else self.failure_reason,
            image_path=f"frame-{self.calls}.png" if status is CaptureStatus.CAPTURE_ACTIVE else "",
            window_handle=101,
            window_title="Defiance",
        )


class _BoundedSequenceCaptureBackend:
    kind = CaptureBackendKind.REGION_SCREENSHOT_FALLBACK

    def __init__(self, statuses: list[CaptureStatus], *, metadata_sequence: list[dict[str, object]] | None = None) -> None:
        self.statuses = list(statuses)
        self.metadata_sequence = list(metadata_sequence or [{} for _ in statuses])
        self.calls = 0
        self.loop = None

    def capture(self, target_window_handle=None, **kwargs) -> CaptureFrame:
        del target_window_handle, kwargs
        index = min(self.calls, len(self.statuses) - 1)
        status = self.statuses[index]
        metadata = dict(self.metadata_sequence[min(index, len(self.metadata_sequence) - 1)])
        self.calls += 1
        if self.loop is not None and self.calls >= len(self.statuses):
            self.loop._stop_event.set()
        return CaptureFrame(
            backend=self.kind,
            width=int(metadata.get("width", 800)),
            height=int(metadata.get("height", 600)),
            source="fake",
            status=status,
            reason="" if status is CaptureStatus.CAPTURE_ACTIVE else str(metadata.get("reason", "FRAME_CAPTURE_FAILED")),
            image_path=f"frame-{self.calls}.png" if status is CaptureStatus.CAPTURE_ACTIVE else "",
            window_handle=int(metadata.get("window_handle", 101)),
            window_title=str(metadata.get("window_title", "Defiance")),
            capture_metadata=dict(metadata.get("capture_metadata", {})),
        )


@dataclass(frozen=True)
class _TemporalReport:
    frame: object
    selected_detail_correlation: dict[str, object]
    prepared_crops: tuple[object, ...]
    ocr_attempts: tuple[object, ...]
    field_candidates: tuple[object, ...]
    ranked_candidates: tuple[object, ...]


def test_capture_loop_publishes_frames_and_stops_cleanly() -> None:
    bus = EventBus()
    backend = _FakeCaptureBackend()
    captured = []
    stopped = []
    bus.subscribe(UIEvent.FRAME_CAPTURED, lambda message: captured.append(message.payload))
    bus.subscribe(UIEvent.SCAN_STOPPED, lambda message: stopped.append(message.payload))

    loop = CaptureLoop(
        event_bus=bus,
        capture_backend=backend,
        session_id="session-loop",
        target_window_handle=101,
        target_window_label="Defiance [101]",
        frame_interval_seconds=0.02,
    )

    started = loop.start_capture_loop()
    time.sleep(0.12)
    diagnostics = loop.stop_capture_loop()

    assert started is True
    assert backend.calls >= 2
    assert len(captured) >= 2
    assert captured[0]["frame_id"].startswith("session-loop-frame-")
    assert stopped
    assert diagnostics["item_count"] == 0
    assert diagnostics["total_bytes"] == 0


def test_capture_loop_does_not_double_start() -> None:
    bus = EventBus()
    loop = CaptureLoop(
        event_bus=bus,
        capture_backend=_FakeCaptureBackend(),
        session_id="session-loop",
        target_window_handle=101,
        target_window_label="Defiance [101]",
        frame_interval_seconds=0.05,
    )

    assert loop.start_capture_loop() is True
    assert loop.start_capture_loop() is False
    loop.stop_capture_loop()


def test_frame_fingerprint_allows_static_frames_and_marks_changed_content(tmp_path: Path) -> None:
    from PIL import Image

    static_path = tmp_path / "static.png"
    changed_path = tmp_path / "changed.png"
    Image.new("RGB", (32, 32), (20, 20, 20)).save(static_path)
    Image.new("RGB", (32, 32), (220, 220, 220)).save(changed_path)

    static_fingerprint = _frame_fingerprint(static_path)
    assert static_fingerprint
    assert _frame_fingerprint(static_path) == static_fingerprint
    assert _frame_fingerprint(changed_path) != static_fingerprint


def test_capture_proof_reports_ordered_frames_without_stale_path_reuse(tmp_path: Path) -> None:
    from PIL import Image

    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"
    Image.new("RGB", (32, 32), (20, 20, 20)).save(first_path)
    Image.new("RGB", (32, 32), (220, 220, 220)).save(second_path)
    loop = CaptureLoop(
        event_bus=EventBus(),
        session_id="ordered-proof",
        target_window_handle=101,
        target_window_label="Defiance [101]",
    )
    for timestamp, path in ((1.0, first_path), (1.1, first_path), (1.2, second_path)):
        loop._record_capture_attempt(
            frame=CaptureFrame(
                backend=CaptureBackendKind.REGION_SCREENSHOT_FALLBACK,
                width=32,
                height=32,
                source="test",
                status=CaptureStatus.CAPTURE_ACTIVE,
                image_path=str(path),
                window_handle=101,
                window_title="Defiance",
            ),
            capture_timestamp=timestamp,
        )

    proof = loop.capture_proof()
    assert proof["unique_sequence_ids"] == 3
    assert proof["unique_timestamps"] == 3
    assert proof["sequence_gaps"] == 0
    assert proof["out_of_order_frames"] == 0
    assert proof["static_frames"] == 1
    assert proof["stale_frame_reuse"] == 1


def test_temporal_detail_guard_holds_stale_detail_until_new_pair_is_stable() -> None:
    guard = SelectedDetailTemporalGuard()
    old = {
        "correlated": True,
        "selected_row_id": "frame-1:row:6",
        "row_name_ocr": {"normalized_text": "Old Item"},
        "detail_title_ocr": {"normalized_text": "Old Item"},
    }
    assert guard.observe(old, frame_id="frame-1", capture_timestamp=1.0, scrolling=False)["correlated"] is False
    assert guard.observe(old, frame_id="frame-2", capture_timestamp=1.1, scrolling=False)["correlated"] is True

    stale = {
        "correlated": False,
        "hold_reason": "SELECTED_ROW_CORRELATION_NOT_PROVEN",
        "selected_row_id": "frame-3:row:7",
        "row_name_ocr": {"normalized_text": "New Item"},
        "detail_title_ocr": {"normalized_text": "Old Item"},
    }
    held = guard.observe(stale, frame_id="frame-3", capture_timestamp=1.2, scrolling=False)
    assert held["correlated"] is False
    assert held["hold_reason"] == "DETAIL_PANEL_SELECTION_TRANSITION"

    new = {
        "correlated": True,
        "selected_row_id": "frame-4:row:7",
        "row_name_ocr": {"normalized_text": "New Item"},
        "detail_title_ocr": {"normalized_text": "New Item"},
    }
    assert guard.observe(new, frame_id="frame-4", capture_timestamp=1.3, scrolling=False)["correlated"] is False
    settled = guard.observe(new, frame_id="frame-5", capture_timestamp=1.4, scrolling=False)
    assert settled["correlated"] is True
    assert settled["temporal_state"] == "STABLE_CORRELATED"


def test_selected_row_identity_epoch_reconciles_without_concatenating_observations() -> None:
    epoch = SelectedRowIdentityEpoch()
    observations = (
        ("Hurrcane Berserker V", 0.71),
        ("Hurricane Berserker V", 0.83),
        ("Hurricane Berserker V", 0.88),
    )
    result = {}
    for index, (text, confidence) in enumerate(observations, start=1):
        result = epoch.observe(
            {
                "correlated": False,
                "selected_row_id": f"frame-{index}:row:7",
                "row_name_ocr": {"raw_text": text, "normalized_text": text, "confidence": confidence, "crop_bounds": {"x1": 1}, "preprocess_variant": "sharpened"},
                "detail_title_ocr": {"normalized_text": "Hurricane Berserker V"},
            },
            frame_id=f"frame-{index}",
            capture_timestamp=float(index),
            scrolling=False,
        )

    assert result["correlated"] is True
    assert result["row_name_ocr"]["normalized_text"] == "Hurricane Berserker V"
    assert "Hurrcane Berserker V Hurricane" not in result["row_name_ocr"]["normalized_text"]
    assert len(result["row_identity_epoch"]["observations"]) == 3


def test_selected_row_identity_epoch_resets_votes_on_selection_change_and_holds_conflict() -> None:
    epoch = SelectedRowIdentityEpoch()
    for index in (1, 2):
        held = epoch.observe(
            {"selected_row_id": f"frame-{index}:row:6", "row_name_ocr": {"normalized_text": "Old Item", "confidence": 0.9}, "detail_title_ocr": {"normalized_text": "Old Item"}},
            frame_id=f"frame-{index}",
            capture_timestamp=float(index),
            scrolling=False,
        )
        assert held["correlated"] is False

    new = epoch.observe(
        {"selected_row_id": "frame-3:row:7", "row_name_ocr": {"normalized_text": "New Item", "confidence": 0.9}, "detail_title_ocr": {"normalized_text": "New Item"}},
        frame_id="frame-3",
        capture_timestamp=3.0,
        scrolling=False,
    )
    assert new["hold_reason"] == "ROW_IDENTITY_PENDING"
    assert len(new["row_identity_epoch"]["observations"]) == 1

    conflict_epoch = SelectedRowIdentityEpoch()
    for index, text in enumerate(("Alpha", "Zebra", "Omega"), start=1):
        conflicted = conflict_epoch.observe(
            {"selected_row_id": f"frame-{index}:row:7", "row_name_ocr": {"normalized_text": text, "confidence": 0.9}, "detail_title_ocr": {"normalized_text": text}},
            frame_id=f"frame-{index}",
            capture_timestamp=float(index),
            scrolling=False,
        )
    assert conflicted["correlated"] is False
    assert conflicted["hold_reason"] == "ROW_IDENTITY_CONFLICTED"


def test_selected_row_identity_epoch_holds_stale_detail_after_row_identity_stabilizes() -> None:
    epoch = SelectedRowIdentityEpoch()
    for index in (1, 2, 3):
        result = epoch.observe(
            {"selected_row_id": f"frame-{index}:row:7", "row_name_ocr": {"normalized_text": "New Item", "confidence": 0.9}, "detail_title_ocr": {"normalized_text": "Old Item"}},
            frame_id=f"frame-{index}",
            capture_timestamp=float(index),
            scrolling=False,
        )
    assert result["correlated"] is False
    assert result["hold_reason"] == "ROW_IDENTITY_DETAIL_INCOMPATIBLE"


def test_temporal_guard_strips_detail_candidates_until_stable_and_holds_scrolling() -> None:
    guard = SelectedDetailTemporalGuard()
    detail_crop = SimpleNamespace(crop_id="detail-row:7:item_type")
    row_crop = SimpleNamespace(crop_id="row:7:item_name")
    detail_candidate = SimpleNamespace(source_crop_id=detail_crop.crop_id)
    row_candidate = SimpleNamespace(source_crop_id=row_crop.crop_id)
    report = _TemporalReport(
        frame=SimpleNamespace(frame_id="frame-1"),
        selected_detail_correlation={
            "correlated": True,
            "selected_row_id": "frame-1:row:7",
            "row_name_ocr": {"normalized_text": "New Item"},
            "detail_title_ocr": {"normalized_text": "New Item"},
        },
        prepared_crops=(row_crop, detail_crop),
        ocr_attempts=(SimpleNamespace(crop_id=row_crop.crop_id), SimpleNamespace(crop_id=detail_crop.crop_id)),
        field_candidates=(row_candidate, detail_candidate),
        ranked_candidates=(row_candidate, detail_candidate),
    )
    held = _apply_selected_detail_temporal_guard(report, guard=guard, capture_timestamp=1.0, scrolling=False)
    assert held.selected_detail_correlation["correlated"] is False
    assert [crop.crop_id for crop in held.prepared_crops] == [row_crop.crop_id]
    assert [candidate.source_crop_id for candidate in held.ranked_candidates] == [row_crop.crop_id]

    scrolling = _apply_selected_detail_temporal_guard(report, guard=SelectedDetailTemporalGuard(), capture_timestamp=1.1, scrolling=True)
    assert scrolling.selected_detail_correlation["hold_reason"] == "DETAIL_PANEL_SCROLLING_TRANSITION"


def test_capture_loop_waits_for_watchdog_before_emitting_capture_lost() -> None:
    bus = EventBus()
    backend = _SequenceCaptureBackend(
        [CaptureStatus.CAPTURE_ACTIVE] + [CaptureStatus.CAPTURE_PAUSED] * 16,
    )
    lost = []
    bus.subscribe(UIEvent.CAPTURE_LOST, lambda message: lost.append(message.payload))

    loop = CaptureLoop(
        event_bus=bus,
        capture_backend=backend,
        session_id="session-loop",
        target_window_handle=101,
        target_window_label="Defiance [101]",
        frame_interval_seconds=0.1,
    )

    assert loop.start_capture_loop() is True
    time.sleep(0.65)
    loop.flush_pending_events()
    assert lost == []

    time.sleep(0.7)
    loop.flush_pending_events()
    loop.stop_capture_loop()

    assert len(lost) == 1
    assert lost[0]["reason"] == "FRAME_CAPTURE_FAILED"
    assert lost[0]["elapsed_without_frame_seconds"] > 1.0


def test_capture_loop_recovers_immediately_when_frames_resume() -> None:
    bus = EventBus()
    backend = _SequenceCaptureBackend(
        [CaptureStatus.CAPTURE_ACTIVE] + [CaptureStatus.CAPTURE_PAUSED] * 12 + [CaptureStatus.CAPTURE_ACTIVE] * 3,
    )
    lost = []
    recovered = []
    bus.subscribe(UIEvent.CAPTURE_LOST, lambda message: lost.append(message.payload))
    bus.subscribe(UIEvent.CAPTURE_RECOVERED, lambda message: recovered.append(message.payload))

    loop = CaptureLoop(
        event_bus=bus,
        capture_backend=backend,
        session_id="session-loop",
        target_window_handle=101,
        target_window_label="Defiance [101]",
        frame_interval_seconds=0.1,
    )

    assert loop.start_capture_loop() is True
    time.sleep(1.7)
    loop.flush_pending_events()
    loop.stop_capture_loop()

    assert len(lost) == 1
    assert len(recovered) == 1
    assert recovered[0]["reason"] == "FRAME_CAPTURE_FAILED"


def test_capture_loop_commits_live_pipeline_report(monkeypatch, tmp_path: Path) -> None:
    from ocring.ocr import pipeline as pipeline_module
    from PIL import Image

    image_path = tmp_path / "frame-1.png"
    Image.new("RGB", (32, 32), (80, 120, 160)).save(image_path)
    committed_reports: list[dict[str, object]] = []

    class _PathCaptureBackend:
        kind = CaptureBackendKind.REGION_SCREENSHOT_FALLBACK

        def __init__(self, image_path: Path) -> None:
            self.image_path = image_path
            self.calls = 0

        def capture(self, target_window_handle=None, **kwargs) -> CaptureFrame:
            del target_window_handle, kwargs
            self.calls += 1
            return CaptureFrame(
                backend=self.kind,
                width=800,
                height=600,
                source="fake",
                status=CaptureStatus.CAPTURE_ACTIVE,
                image_path=str(self.image_path),
                window_handle=101,
                window_title="Defiance",
            )

    def fake_capture_frame_state(image_path, *, profile_id, frame_id=None, session_id=None, timestamp_utc=None, image_source=None):
        del image_path, profile_id, image_source
        frame = SimpleNamespace(
            frame_id=frame_id or "frame-1",
            session_id=session_id or "session-live",
            timestamp_utc=timestamp_utc or datetime.now(timezone.utc).isoformat(),
        )
        quality = SimpleNamespace(
            action=SimpleNamespace(value="keep"),
            sharpness=0.9,
            motion_penalty=0.1,
            partial_row_penalty=0.0,
        )
        return SimpleNamespace(
            frame=frame,
            quality=quality,
            row_signatures={1: "row-a"},
            capture_timestamp=1.0,
            debug_capture_enabled=False,
        )

    def fake_build_frame_report(image_path, *, profile_id, frame_id=None, session_id=None, timestamp_utc=None, capture_state=None, changed_row_ids=None, **kwargs):
        del image_path, profile_id, changed_row_ids, kwargs
        ranked = (SimpleNamespace(field_kind=SimpleNamespace(value="item_name")),)
        return SimpleNamespace(
            frame=SimpleNamespace(
                frame_id=frame_id or "frame-1",
                session_id=session_id or "session-live",
                timestamp_utc=timestamp_utc or datetime.now(timezone.utc).isoformat(),
            ),
            ranked_candidates=ranked,
            retained_evidence=(),
        )

    def fake_build_session_report(frame_reports, *, profile_id, scan_scope):
        return {
            "profile_id": profile_id,
            "frame_reports": [
                {
                    "frame": {
                        "session_id": frame_reports[0].frame.session_id,
                        "frame_id": frame_reports[0].frame.frame_id,
                    }
                }
            ],
            "assembled_records": [
                {
                    "row_slot": 1,
                    "state": "complete",
                    "fields": {
                        "item_name": "Power Bore",
                        "item_rarity": "Tier IV",
                        "item_type": "Rocket Launcher",
                        "item_count": "2",
                    },
                    "support_summary": {},
                    "source_frame_ids": [frame_reports[0].frame.frame_id],
                    "source_row_ids": [f"{frame_reports[0].frame.frame_id}:row:1"],
                    "overlap_provenance": {},
                    "reasons": [],
                }
            ],
            "scan_integrity": {
                "scan_scope": scan_scope.value,
                "completeness_state": "partial",
                "completeness_reason": "inferred_complete",
            },
        }

    monkeypatch.setattr(pipeline_module, "_capture_frame_state", fake_capture_frame_state)
    monkeypatch.setattr(pipeline_module, "_build_frame_report", fake_build_frame_report)
    monkeypatch.setattr(pipeline_module, "_build_session_report", fake_build_session_report)
    monkeypatch.setattr(pipeline_module, "_attach_throughput", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline_module, "commit_session_artifacts", lambda report, output_dir=None: committed_reports.append(report) or (tmp_path / "commit"))

    bus = EventBus()
    backend = _PathCaptureBackend(image_path)
    loop = CaptureLoop(
        event_bus=bus,
        capture_backend=backend,
        session_id="session-live",
        target_window_handle=101,
        target_window_label="Defiance [101]",
        profile_id="defiance",
        scan_scope="Full",
        persist_dir=tmp_path,
        frame_interval_seconds=0.02,
    )

    assert loop.start_capture_loop() is True
    time.sleep(0.12)
    diagnostics = loop.stop_capture_loop()

    assert committed_reports
    assert committed_reports[0]["assembled_records"][0]["fields"]["item_name"] == "Power Bore"
    assert committed_reports[0]["capture_proof"]["accepted_frames"] >= 1
    assert diagnostics["report"]["assembled_records"][0]["fields"]["item_name"] == "Power Bore"
    assert diagnostics["capture_proof"]["accepted_frames"] >= 1


def test_capture_loop_skips_invalid_png_frame_files(monkeypatch, tmp_path: Path) -> None:
    from ocring.ocr import pipeline as pipeline_module

    invalid_path = tmp_path / "frame-invalid.png"
    invalid_path.write_bytes(b"not-a-png")

    class _InvalidPathCaptureBackend:
        kind = CaptureBackendKind.REGION_SCREENSHOT_FALLBACK

        def capture(self, target_window_handle=None, **kwargs) -> CaptureFrame:
            del target_window_handle, kwargs
            return CaptureFrame(
                backend=self.kind,
                width=800,
                height=600,
                source="fake",
                status=CaptureStatus.CAPTURE_ACTIVE,
                image_path=str(invalid_path),
                window_handle=101,
                window_title="Defiance",
            )

    called = {"capture_state": 0}

    def fake_capture_frame_state(*args, **kwargs):
        called["capture_state"] += 1
        raise AssertionError("_capture_frame_state should not run for invalid PNG files")

    monkeypatch.setattr(pipeline_module, "_capture_frame_state", fake_capture_frame_state)

    loop = CaptureLoop(
        event_bus=EventBus(),
        capture_backend=_InvalidPathCaptureBackend(),
        session_id="session-invalid",
        target_window_handle=101,
        target_window_label="Defiance [101]",
        frame_interval_seconds=0.5,
    )

    loop._process_live_frame(
        {
            "frame_id": "session-invalid-frame-000001",
            "image_path": str(invalid_path),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "capture_timestamp": 1.0,
        }
    )

    assert called["capture_state"] == 0


def test_capture_loop_processes_changed_rows_when_rate_controller_defers(monkeypatch, tmp_path: Path) -> None:
    from PIL import Image
    from ocring.ocr import pipeline as pipeline_module

    image_path = tmp_path / "changed-row.png"
    Image.new("RGB", (32, 32), (80, 120, 160)).save(image_path)
    built_reports: list[str] = []

    def fake_capture_frame_state(image_path, *, profile_id, frame_id=None, session_id=None, timestamp_utc=None, image_source=None):
        del image_path, profile_id, image_source
        return SimpleNamespace(
            frame=SimpleNamespace(frame_id=frame_id, session_id=session_id, timestamp_utc=timestamp_utc),
            quality=SimpleNamespace(action=SimpleNamespace(value="keep"), sharpness=0.9, motion_penalty=0.0, partial_row_penalty=0.0),
            row_signatures={1: "new-selected-row"},
            capture_timestamp=2.0,
            debug_capture_enabled=False,
        )

    def fake_build_frame_report(image_path, *, frame_id=None, **kwargs):
        del image_path, kwargs
        built_reports.append(frame_id)
        return SimpleNamespace(
            frame=SimpleNamespace(frame_id=frame_id, session_id="session-changed", timestamp_utc="2026-09-02T00:00:00+00:00"),
            ranked_candidates=(),
            retained_evidence=(),
        )

    monkeypatch.setattr(pipeline_module, "_capture_frame_state", fake_capture_frame_state)
    monkeypatch.setattr(pipeline_module, "_build_frame_report", fake_build_frame_report)

    loop = CaptureLoop(
        event_bus=EventBus(),
        session_id="session-changed",
        target_window_handle=101,
        frame_interval_seconds=0.5,
    )
    loop._previous_signatures = {1: "old-selected-row"}
    loop._processed_frame_ids.add("previous-frame")
    loop._selected_row_identity_epoch = SimpleNamespace(needs_observation=False)
    loop._controller = SimpleNamespace(evaluate=lambda **kwargs: SimpleNamespace(should_extract=False))

    loop._process_live_frame(
        {
            "frame_id": "session-changed-frame-000002",
            "image_path": str(image_path),
            "timestamp_utc": "2026-09-02T00:00:00+00:00",
            "capture_timestamp": 2.0,
        }
    )

    assert built_reports == ["session-changed-frame-000002"]


def test_pipeline_png_validation_checks_signature_and_size(tmp_path: Path) -> None:
    from ocring.ocr import pipeline as pipeline_module

    missing_path = tmp_path / "missing.png"
    empty_path = tmp_path / "empty.png"
    bad_path = tmp_path / "bad.png"
    good_path = tmp_path / "good.png"
    temp_path = tmp_path / "live.tmp"

    empty_path.write_bytes(b"")
    bad_path.write_bytes(b"not-a-png")
    good_path.write_bytes(b"\x89PNG\r\n\x1a\nrest")
    temp_path.write_bytes(b"\x89PNG\r\n\x1a\nrest")

    assert pipeline_module._is_valid_png_file(missing_path) is False
    assert pipeline_module._is_valid_png_file(empty_path) is False
    assert pipeline_module._is_valid_png_file(bad_path) is False
    assert pipeline_module._is_valid_png_file(temp_path) is False
    assert pipeline_module._is_valid_png_file(good_path) is False


def test_pipeline_live_and_general_image_validation_are_separated(tmp_path: Path) -> None:
    from PIL import Image
    from ocring.ocr import pipeline as pipeline_module

    live_png = tmp_path / "live.png"
    fixture_pgm = tmp_path / "fixture.pgm"

    Image.new("RGB", (8, 8), (25, 50, 75)).save(live_png)
    Image.new("L", (8, 8), 128).save(fixture_pgm)

    assert pipeline_module._is_valid_image_for_source(live_png, image_source=pipeline_module.IMAGE_SOURCE_LIVE_CAPTURE) is True
    assert pipeline_module._is_valid_image_for_source(fixture_pgm, image_source=pipeline_module.IMAGE_SOURCE_REPLAY_FIXTURE) is True
    assert pipeline_module._is_valid_image_for_source(fixture_pgm, image_source=pipeline_module.IMAGE_SOURCE_LIVE_CAPTURE) is False


def test_run_semantic_allocation_prefers_assembled_field_fragments_over_ranked_pile() -> None:
    from ocring.ocr import pipeline as pipeline_module

    record = AssembledCandidateRecord(
        row_slot=1,
        profile_id="defiance",
        state=RecordAssemblyState.PARTIAL,
        fields={
            FieldKind.ITEM_NAME: "Overclocked Prime Evolver",
            FieldKind.ITEM_COUNT: "7",
        },
        support_summary={},
        source_frame_ids=("f1",),
        source_row_ids=("f1:row:1",),
        missing_fields=(FieldKind.ITEM_RARITY, FieldKind.ITEM_TYPE),
        field_details={
            "item_name": {"source_text": "Overclocked Prime Evolver"},
            "item_count": {"source_text": "7"},
        },
        profile_version="1.0",
        scan_timestamp="2026-08-20T01:07:13+00:00",
    )
    ranked_candidates = (
        RankedFieldCandidate(
            row_id="f1:row:1",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Overclocked Prime Evolver Overclocked Prime Evalver Overdlocked Prime Evolver",
            source_crop_id="crop-1",
            source_variant=type("Variant", (), {"value": "grayscale"})(),
            source_engine="rapidocr",
            decision=CandidateDecision.SELECTED,
            confidence=0.82,
            reasons=(),
        ),
    )

    candidate_records, organization_summary, reconstruction_results, allocation_results = pipeline_module._run_semantic_allocation(
        (record,),
        ranked_candidates=ranked_candidates,
        profile_id="defiance",
    )

    assert candidate_records
    assert isinstance(organization_summary, dict)
    # Keyed by temporal_identity_id now, not row_slot: the record
    # above has no temporal_identity_id set, so it falls back to str(row_slot).
    assert reconstruction_results["1"]["repaired_fragments"][0] == "Overclocked Prime Evolver"
    assert allocation_results["1"]["field_values"]["item_name"] == "Overclocked Prime Evolver"
    assert candidate_records[0].field_values["item_name"] == "Overclocked Prime Evolver"


def test_apply_truth_progression_preserves_field_details_and_semantic_notes() -> None:
    from ocring.ocr import pipeline as pipeline_module
    from ocring.ocr.truth_state import TruthState

    record = AssembledCandidateRecord(
        row_slot=1,
        profile_id="defiance",
        state=RecordAssemblyState.PARTIAL,
        fields={
            FieldKind.ITEM_NAME: "Extended Sniper Mag V",
        },
        support_summary={},
        source_frame_ids=("f1",),
        source_row_ids=("f1:row:1",),
        missing_fields=(FieldKind.ITEM_RARITY, FieldKind.ITEM_TYPE, FieldKind.ITEM_COUNT),
        overlap_provenance={"allocation_provenance": {"record_class": "WeaponMod"}},
        truth_state=TruthState.RECOGNIZED.value,
        progression_reason="FIELDS_RECOGNIZED_FROM_TEMPORAL_EVIDENCE",
        profile_version="1.0",
        scan_timestamp="2026-08-20T05:00:00+00:00",
        definition_used="WeaponMod",
        field_details={"item_name": {"source_text": "Extended Sniper Mag V"}},
        semantic_notes=("REFERENCE_DATA_MISSING",),
    )

    progressed = pipeline_module._apply_truth_progression(
        (record,),
        continuity_records=(SimpleNamespace(row_slots=(1,)),),
        correctness={"record_correctness": []},
    )

    assert progressed[0].field_details["item_name"]["source_text"] == "Extended Sniper Mag V"
    assert progressed[0].definition_used == "WeaponMod"
    assert progressed[0].semantic_notes == ("REFERENCE_DATA_MISSING",)


def test_build_frame_report_downgrades_live_frame_without_item_name_evidence(monkeypatch, tmp_path: Path) -> None:
    from ocring.ocr import pipeline as pipeline_module
    from ocring.ocr.models import CandidateDecision, DiagnosticReport, OcrEngineSummary, RankedFieldCandidate, Rect
    from ocring.ocr.screen_classifier import ScreenClass, ScreenClassification
    from PIL import Image

    image_path = tmp_path / "frame.png"
    Image.new("RGB", (1366, 768), (20, 40, 60)).save(image_path)

    fake_capture = SimpleNamespace(
        frame=SimpleNamespace(
            frame_id="frame-1",
            session_id="session-1",
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            image=SimpleNamespace(path=str(image_path), width=1366, height=768),
            inventory_region=Rect(51, 63, 982, 654),
        ),
        ocr_engine=OcrEngineSummary(engine_name="rapidocr", available=True, reason="test"),
        quality=SimpleNamespace(action=SimpleNamespace(value="keep"), sharpness=0.9, motion_penalty=0.0, contrast=0.8, occlusion_penalty=0.0, partial_row_penalty=0.0, reasons=()),
        row_zones=(SimpleNamespace(row_id="frame-1:row:1", row_bounds=Rect(51, 63, 982, 116), fields={}),),
        preprocessed_regions=(),
        capture_timestamp=1.0,
        row_signatures={1: "abc"},
        screen_classification=ScreenClassification(ScreenClass.INVENTORY, "PANEL_GEOMETRY_HEURISTIC"),
        debug_capture_enabled=False,
    )

    fake_recognition = SimpleNamespace(
        ocr_attempts=(),
        field_candidates=(),
        recognition_mode_used="Classic-Only",
    )

    monkeypatch.setattr(pipeline_module, "_capture_frame_state", lambda *args, **kwargs: fake_capture)
    monkeypatch.setattr(
        pipeline_module.RecognitionOrchestrator,
        "run",
        lambda self, **kwargs: fake_recognition,
    )
    monkeypatch.setattr(
        pipeline_module,
        "rank_field_candidates",
        lambda *args, **kwargs: (
            RankedFieldCandidate(
                row_id="frame-1:row:1",
                field_kind=FieldKind.ITEM_RARITY,
                candidate_value="Epic",
                source_crop_id="crop-rarity",
                source_variant=type("Variant", (), {"value": "high_contrast"})(),
                source_engine="color_classifier",
                decision=CandidateDecision.SELECTED,
                confidence=0.8,
                reasons=(),
            ),
        ),
    )

    report = pipeline_module._build_frame_report(
        image_path,
        profile_id="defiance",
        capture_state=fake_capture,
        image_source=pipeline_module.IMAGE_SOURCE_LIVE_CAPTURE,
    )

    assert isinstance(report, DiagnosticReport)
    assert report.screen_class == ScreenClass.UNKNOWN.value
    assert report.hold_reason == "UNKNOWN_SCREEN"
    assert report.ranked_candidates == ()


def test_pipeline_prefers_profile_roi_and_row_count_for_live_inventory_layout(monkeypatch, tmp_path: Path) -> None:
    from ocring.ocr import pipeline as pipeline_module
    from ocring.ocr.profile import Profile

    profile = Profile(
        profile_id="defiance",
        profile_name="Defiance",
        version="1.0",
        screens=[
            {
                "screen_class": "inventory",
                "roi": {"x1": 72, "y1": 88, "x2": 1380, "y2": 920},
                "rows": 11,
            }
        ],
    )
    monkeypatch.setattr(pipeline_module, "load_profile", lambda profile_id: profile)

    region, detector_name, expected_rows = pipeline_module._resolve_inventory_layout(
        tmp_path / "unused.png",
        profile_id="defiance",
        image_width=1366,
        image_height=768,
        image_source=pipeline_module.IMAGE_SOURCE_LIVE_CAPTURE,
    )

    assert detector_name == "profile_roi_projection"
    assert expected_rows == 11
    assert region.x1 == 51
    assert region.y1 == 63
    assert region.x2 == 982
    assert region.y2 == 654


def test_capture_loop_collects_capture_proof_summary() -> None:
    bus = EventBus()
    backend = _BoundedSequenceCaptureBackend(
        [CaptureStatus.CAPTURE_ACTIVE, CaptureStatus.CAPTURE_PAUSED, CaptureStatus.CAPTURE_ACTIVE],
        metadata_sequence=[
            {
                "width": 1366,
                "height": 768,
                "window_handle": 200,
                "capture_metadata": {
                    "selected_window_handle": 101,
                    "resolved_window": {
                        "hwnd": 200,
                        "title": "Defiance",
                        "class_name": "GameClass",
                        "pid": 555,
                        "client_screen_rect": {"left": 10, "top": 20, "right": 1376, "bottom": 788},
                    },
                    "capture_rect": {"left": 10, "top": 20, "right": 1376, "bottom": 788, "width": 1366, "height": 768},
                    "returned_image_size": {"width": 1366, "height": 768},
                    "surface_check": {"valid": True, "reason": ""},
                    "returned_surface_check": {"valid": True, "reason": ""},
                },
            },
            {
                "width": 156,
                "height": 24,
                "window_handle": 202,
                "reason": "CAPTURE_WIDTH_TOO_SMALL",
                "capture_metadata": {
                    "selected_window_handle": 101,
                    "reacquired_to_handle": 202,
                    "resolved_window": {
                        "hwnd": 202,
                        "title": "Defiance",
                        "class_name": "GameClass",
                        "pid": 555,
                        "client_screen_rect": {"left": 10, "top": 20, "right": 166, "bottom": 44},
                    },
                    "capture_rect": {"left": 10, "top": 20, "right": 166, "bottom": 44, "width": 156, "height": 24},
                    "returned_image_size": {"width": 156, "height": 24},
                    "surface_check": {"valid": False, "reason": "CAPTURE_WIDTH_TOO_SMALL"},
                    "returned_surface_check": {"valid": False, "reason": "CAPTURE_WIDTH_TOO_SMALL"},
                },
            },
            {
                "width": 1366,
                "height": 768,
                "window_handle": 202,
                "capture_metadata": {
                    "selected_window_handle": 101,
                    "reacquired_to_handle": 202,
                    "resolved_window": {
                        "hwnd": 202,
                        "title": "Defiance",
                        "class_name": "GameClass",
                        "pid": 555,
                        "client_screen_rect": {"left": 10, "top": 20, "right": 1376, "bottom": 788},
                    },
                    "capture_rect": {"left": 10, "top": 20, "right": 1376, "bottom": 788, "width": 1366, "height": 768},
                    "returned_image_size": {"width": 1366, "height": 768},
                    "surface_check": {"valid": True, "reason": ""},
                    "returned_surface_check": {"valid": True, "reason": ""},
                },
            },
        ],
    )

    loop = CaptureLoop(
        event_bus=bus,
        capture_backend=backend,
        session_id="session-proof",
        target_window_handle=101,
        target_window_label="Defiance [101]",
        frame_interval_seconds=0.01,
    )
    backend.loop = loop

    assert loop.start_capture_loop() is True
    time.sleep(0.1)
    diagnostics = loop.stop_capture_loop()

    proof = diagnostics["capture_proof"]
    assert proof["attempted_frames"] == 3
    assert proof["accepted_frames"] == 2
    assert proof["rejected_frames"] == 1
    assert proof["reacquisitions"] == 2
    assert proof["consecutive_accepted_frame_max"] == 1
    assert proof["unique_hwnds_observed"] == [200, 202]
    assert {"width": 156, "height": 24} in proof["dimensions_observed"]
    assert {"width": 1366, "height": 768} in proof["dimensions_observed"]
    assert len(proof["attempt_log"]) == 3
    assert proof["attempt_log"][1]["reacquisition_occurred"] is True
    assert proof["attempt_log"][1]["failure_reason"] == "CAPTURE_WIDTH_TOO_SMALL"


def test_build_frame_report_correlates_selected_row_with_detail_panel(monkeypatch, tmp_path: Path) -> None:
    from ocring.ocr import pipeline as pipeline_module
    from ocring.ocr.screen_classifier import ScreenClass, ScreenClassification
    from PIL import Image, ImageDraw

    image_path = tmp_path / "frame.png"
    image = Image.new("RGB", (1366, 768), (20, 20, 20))
    draw = ImageDraw.Draw(image)
    inventory_region = Rect(51, 63, 982, 654)
    row_10 = Rect(90, 510, 520, 548)
    row_11 = Rect(90, 552, 520, 590)
    draw.rectangle((row_10.x1, row_10.y2 - 6, row_10.x1 + 30, row_10.y2), fill=(220, 130, 50))
    draw.rectangle((row_11.x1, row_11.y2 - 6, row_11.x2, row_11.y2), fill=(220, 130, 50))
    image.save(image_path)

    fake_capture = SimpleNamespace(
        frame=SimpleNamespace(
            frame_id="frame-1",
            session_id="session-1",
            profile_id="defiance",
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            image=SimpleNamespace(path=str(image_path), width=1366, height=768),
            inventory_region=inventory_region,
            detector_name="profile_roi_projection",
        ),
        ocr_engine=OcrEngineSummary(engine_name="rapidocr", available=True, reason="test"),
        quality=SimpleNamespace(action=SimpleNamespace(value="keep"), sharpness=0.9, motion_penalty=0.0, contrast=0.8, occlusion_penalty=0.0, partial_row_penalty=0.0, reasons=()),
        row_zones=(
            SimpleNamespace(row_id="frame-1:row:10", row_bounds=row_10, fields={}),
            SimpleNamespace(row_id="frame-1:row:11", row_bounds=row_11, fields={}),
        ),
        preprocessed_regions=(),
        capture_timestamp=1.0,
        row_signatures={10: "row-10", 11: "row-11"},
        screen_classification=ScreenClassification(ScreenClass.INVENTORY, "PANEL_GEOMETRY_HEURISTIC"),
        debug_capture_enabled=False,
    )

    def fake_run(self, *, prepared_crops, profile_id, **kwargs):
        del self, profile_id, kwargs
        attempts = []
        for crop in prepared_crops:
            normalized = ""
            raw_text = ""
            confidence = 0.0
            status = OcrEngineStatus.ERROR
            reasons = ("EMPTY_OCR_TEXT",)
            if crop.row_id == "frame-1:row:11" and crop.field_kind is FieldKind.ITEM_NAME:
                if str(crop.crop_id).startswith("detail-"):
                    normalized = "Perimeter Overthruster IV"
                    raw_text = normalized
                    confidence = 0.96
                    status = OcrEngineStatus.OK
                    reasons = ()
                elif crop.source_region.x1 < 400:
                    normalized = "Perimeter Overthruster IV"
                    raw_text = normalized
                    confidence = 0.95
                    status = OcrEngineStatus.OK
                    reasons = ()
            elif crop.row_id == "frame-1:row:11" and crop.field_kind is FieldKind.ITEM_TYPE and str(crop.crop_id).startswith("detail-"):
                normalized = "Barrel"
                raw_text = "Barrel"
                confidence = 0.82
                status = OcrEngineStatus.OK
                reasons = ()
            elif crop.row_id == "frame-1:row:11" and crop.field_kind is FieldKind.ITEM_SYNERGY and str(crop.crop_id).startswith("detail-"):
                normalized = "Synergy: Sol's Prominence"
                raw_text = normalized
                confidence = 0.97
                status = OcrEngineStatus.OK
                reasons = ()
            attempts.append(
                OcrAttempt(
                    crop_id=crop.crop_id,
                    row_id=crop.row_id,
                    field_kind=crop.field_kind,
                    variant=crop.variant,
                    engine_name="rapidocr",
                    status=status,
                    raw_text=raw_text,
                    normalized_text=normalized,
                    confidence=confidence,
                    reasons=reasons,
                )
            )
        return SimpleNamespace(
            ocr_attempts=tuple(attempts),
            field_candidates=build_field_candidates(tuple(attempts), profile_id="defiance"),
            recognition_mode_used="Classic-Only",
        )

    monkeypatch.setattr(pipeline_module, "_capture_frame_state", lambda *args, **kwargs: fake_capture)
    monkeypatch.setattr(pipeline_module.RecognitionOrchestrator, "run", fake_run)
    monkeypatch.setattr(
        pipeline_module,
        "run_ocr_attempts",
        lambda image_path, prepared_crops, max_attempts=0: tuple(
            OcrAttempt(
                crop_id=crop.crop_id,
                row_id=crop.row_id,
                field_kind=crop.field_kind,
                variant=crop.variant,
                engine_name="rapidocr",
                status=OcrEngineStatus.OK,
                raw_text="Perimeter Overthruster IV",
                normalized_text="Perimeter Overthruster IV",
                confidence=0.96,
                reasons=(),
            )
            for crop in prepared_crops
        ),
    )

    report = pipeline_module._build_frame_report(
        image_path,
        profile_id="defiance",
        capture_state=fake_capture,
        image_source=pipeline_module.IMAGE_SOURCE_LIVE_CAPTURE,
    )

    selected = [candidate for candidate in report.ranked_candidates if candidate.decision is CandidateDecision.SELECTED]
    assert report.selected_detail_correlation["correlated"] is True
    assert report.selected_detail_correlation["selected_row_id"] == "frame-1:row:11"
    assert any(candidate.field_kind is FieldKind.ITEM_NAME and candidate.candidate_value == "Perimeter Overthruster IV" for candidate in selected)
    assert any(candidate.field_kind is FieldKind.ITEM_TYPE and candidate.candidate_value == "Barrel" for candidate in selected)
    assert any(candidate.field_kind is FieldKind.ITEM_SYNERGY and candidate.candidate_value == "Sol's Prominence" for candidate in selected)
    assert report.selected_detail_correlation["layout_name"] == "left_comparison_panel"


def test_build_frame_report_selects_right_detail_layout_when_title_matches(monkeypatch, tmp_path: Path) -> None:
    from ocring.ocr import pipeline as pipeline_module
    from ocring.ocr.screen_classifier import ScreenClass, ScreenClassification
    from PIL import Image, ImageDraw

    image_path = tmp_path / "frame.png"
    image = Image.new("RGB", (1366, 768), (20, 20, 20))
    draw = ImageDraw.Draw(image)
    inventory_region = Rect(51, 63, 982, 654)
    row_4 = Rect(90, 220, 520, 258)
    draw.rectangle((row_4.x1, row_4.y2 - 6, row_4.x2, row_4.y2), fill=(220, 130, 50))
    image.save(image_path)

    fake_capture = SimpleNamespace(
        frame=SimpleNamespace(
            frame_id="frame-1",
            session_id="session-1",
            profile_id="defiance",
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            image=SimpleNamespace(path=str(image_path), width=1366, height=768),
            inventory_region=inventory_region,
            detector_name="profile_roi_projection",
        ),
        ocr_engine=OcrEngineSummary(engine_name="rapidocr", available=True, reason="test"),
        quality=SimpleNamespace(action=SimpleNamespace(value="keep"), sharpness=0.9, motion_penalty=0.0, contrast=0.8, occlusion_penalty=0.0, partial_row_penalty=0.0, reasons=()),
        row_zones=(SimpleNamespace(row_id="frame-1:row:4", row_bounds=row_4, fields={}),),
        preprocessed_regions=(),
        capture_timestamp=1.0,
        row_signatures={4: "row-4"},
        screen_classification=ScreenClassification(ScreenClass.INVENTORY, "PANEL_GEOMETRY_HEURISTIC"),
        debug_capture_enabled=False,
    )

    def fake_run(self, *, prepared_crops, profile_id, **kwargs):
        del self, profile_id, kwargs
        attempts = []
        for crop in prepared_crops:
            normalized = ""
            raw_text = ""
            confidence = 0.0
            status = OcrEngineStatus.ERROR
            reasons = ("EMPTY_OCR_TEXT",)
            crop_id = str(crop.crop_id)
            if crop.field_kind is FieldKind.ITEM_NAME and crop_id.startswith("detail-"):
                if "right" in crop_id or crop.source_region.x1 >= 1000:
                    normalized = "Bio-Stabilizer IV"
                    raw_text = normalized
                    confidence = 0.91
                    status = OcrEngineStatus.OK
                    reasons = ()
                else:
                    normalized = "★"
                    raw_text = normalized
                    confidence = 0.39
                    status = OcrEngineStatus.OK
                    reasons = ()
            elif crop.field_kind is FieldKind.ITEM_NAME:
                normalized = "Bio-Stabilizer IV"
                raw_text = normalized
                confidence = 0.86
                status = OcrEngineStatus.OK
                reasons = ()
            elif crop.field_kind is FieldKind.ITEM_TYPE and crop.source_region.x1 >= 1000:
                normalized = "Stock"
                raw_text = normalized
                confidence = 0.92
                status = OcrEngineStatus.OK
                reasons = ()
            elif crop.field_kind is FieldKind.ITEM_SYNERGY and crop.source_region.x1 >= 1000:
                normalized = "Synergy: Parasitic Impetus"
                raw_text = normalized
                confidence = 0.95
                status = OcrEngineStatus.OK
                reasons = ()
            attempts.append(
                OcrAttempt(
                    crop_id=crop.crop_id,
                    row_id=crop.row_id,
                    field_kind=crop.field_kind,
                    variant=crop.variant,
                    engine_name="rapidocr",
                    status=status,
                    raw_text=raw_text,
                    normalized_text=normalized,
                    confidence=confidence,
                    reasons=reasons,
                )
            )
        return SimpleNamespace(
            ocr_attempts=tuple(attempts),
            field_candidates=build_field_candidates(tuple(attempts), profile_id="defiance"),
            recognition_mode_used="Classic-Only",
        )

    monkeypatch.setattr(pipeline_module, "_capture_frame_state", lambda *args, **kwargs: fake_capture)
    monkeypatch.setattr(pipeline_module.RecognitionOrchestrator, "run", fake_run)
    monkeypatch.setattr(
        pipeline_module,
        "run_ocr_attempts",
        lambda image_path, prepared_crops, max_attempts=0: tuple(
            OcrAttempt(
                crop_id=crop.crop_id,
                row_id=crop.row_id,
                field_kind=crop.field_kind,
                variant=crop.variant,
                engine_name="rapidocr",
                status=OcrEngineStatus.OK,
                raw_text="Bio-Stabilizer IV" if crop.source_region.x1 >= 1000 else "★",
                normalized_text="Bio-Stabilizer IV" if crop.source_region.x1 >= 1000 else "★",
                confidence=0.91 if crop.source_region.x1 >= 1000 else 0.39,
                reasons=(),
            )
            for crop in prepared_crops
        ),
    )

    report = pipeline_module._build_frame_report(
        image_path,
        profile_id="defiance",
        capture_state=fake_capture,
        image_source=pipeline_module.IMAGE_SOURCE_LIVE_CAPTURE,
    )

    selected = [candidate for candidate in report.ranked_candidates if candidate.decision is CandidateDecision.SELECTED]
    assert report.selected_detail_correlation["correlated"] is True
    assert report.selected_detail_correlation["layout_name"] == "right_single_panel"
    assert any(candidate.field_kind is FieldKind.ITEM_TYPE and candidate.candidate_value == "Stock" for candidate in selected)
    assert any(candidate.field_kind is FieldKind.ITEM_SYNERGY and candidate.candidate_value == "Parasitic Impetus" for candidate in selected)


def test_build_frame_report_prefers_horizontal_selection_border_over_left_orange_noise(monkeypatch, tmp_path: Path) -> None:
    from ocring.ocr import pipeline as pipeline_module
    from ocring.ocr.screen_classifier import ScreenClass, ScreenClassification
    from PIL import Image, ImageDraw

    image_path = tmp_path / "frame.png"
    image = Image.new("RGB", (1366, 768), (20, 20, 20))
    draw = ImageDraw.Draw(image)
    inventory_region = Rect(51, 63, 982, 654)
    distractor_row = Rect(90, 220, 520, 258)
    selected_row = Rect(90, 430, 520, 468)
    draw.rectangle((distractor_row.x1, distractor_row.y1, distractor_row.x1 + 28, distractor_row.y2), fill=(220, 130, 50))
    draw.rectangle((selected_row.x1, selected_row.y1, selected_row.x2, selected_row.y2), outline=(220, 130, 50), width=6)
    image.save(image_path)

    fake_capture = SimpleNamespace(
        frame=SimpleNamespace(
            frame_id="frame-1",
            session_id="session-1",
            profile_id="defiance",
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            image=SimpleNamespace(path=str(image_path), width=1366, height=768),
            inventory_region=inventory_region,
            detector_name="profile_roi_projection",
        ),
        ocr_engine=OcrEngineSummary(engine_name="rapidocr", available=True, reason="test"),
        quality=SimpleNamespace(action=SimpleNamespace(value="keep"), sharpness=0.9, motion_penalty=0.0, contrast=0.8, occlusion_penalty=0.0, partial_row_penalty=0.0, reasons=()),
        row_zones=(
            SimpleNamespace(row_id="frame-1:row:4", row_bounds=distractor_row, fields={}),
            SimpleNamespace(row_id="frame-1:row:8", row_bounds=selected_row, fields={}),
        ),
        preprocessed_regions=(),
        capture_timestamp=1.0,
        row_signatures={4: "row-4", 8: "row-8"},
        screen_classification=ScreenClassification(ScreenClass.INVENTORY, "PANEL_GEOMETRY_HEURISTIC"),
        debug_capture_enabled=False,
    )

    def fake_run(self, *, prepared_crops, profile_id, **kwargs):
        del self, profile_id, kwargs
        attempts = []
        for crop in prepared_crops:
            normalized = ""
            raw_text = ""
            confidence = 0.0
            status = OcrEngineStatus.ERROR
            reasons = ("EMPTY_OCR_TEXT",)
            if crop.field_kind is FieldKind.ITEM_NAME and crop.row_id == "frame-1:row:4":
                normalized = "Orange Distractor"
                raw_text = normalized
                confidence = 0.88
                status = OcrEngineStatus.OK
                reasons = ()
            elif crop.field_kind is FieldKind.ITEM_NAME and crop.row_id == "frame-1:row:8":
                normalized = "Hurricane Berserker V ARK"
                raw_text = normalized
                confidence = 0.93
                status = OcrEngineStatus.OK
                reasons = ()
            elif crop.field_kind is FieldKind.ITEM_TYPE and str(crop.crop_id).startswith("detail-"):
                normalized = "Shield"
                raw_text = normalized
                confidence = 0.91
                status = OcrEngineStatus.OK
                reasons = ()
            elif crop.field_kind is FieldKind.ITEM_SYNERGY and str(crop.crop_id).startswith("detail-"):
                normalized = "Synergy: Overnight Express"
                raw_text = normalized
                confidence = 0.94
                status = OcrEngineStatus.OK
                reasons = ()
            attempts.append(
                OcrAttempt(
                    crop_id=crop.crop_id,
                    row_id=crop.row_id,
                    field_kind=crop.field_kind,
                    variant=crop.variant,
                    engine_name="rapidocr",
                    status=status,
                    raw_text=raw_text,
                    normalized_text=normalized,
                    confidence=confidence,
                    reasons=reasons,
                )
            )
        return SimpleNamespace(
            ocr_attempts=tuple(attempts),
            field_candidates=build_field_candidates(tuple(attempts), profile_id="defiance"),
            recognition_mode_used="Classic-Only",
        )

    monkeypatch.setattr(pipeline_module, "_capture_frame_state", lambda *args, **kwargs: fake_capture)
    monkeypatch.setattr(pipeline_module.RecognitionOrchestrator, "run", fake_run)
    monkeypatch.setattr(
        pipeline_module,
        "run_ocr_attempts",
        lambda image_path, prepared_crops, max_attempts=0: tuple(
            OcrAttempt(
                crop_id=crop.crop_id,
                row_id=crop.row_id,
                field_kind=crop.field_kind,
                variant=crop.variant,
                engine_name="rapidocr",
                status=OcrEngineStatus.OK,
                raw_text="Hurricane Berserker V ARK" if crop.source_region.x1 >= 1000 else "",
                normalized_text="Hurricane Berserker V ARK" if crop.source_region.x1 >= 1000 else "",
                confidence=0.96 if crop.source_region.x1 >= 1000 else 0.0,
                reasons=(),
            )
            for crop in prepared_crops
        ),
    )

    report = pipeline_module._build_frame_report(
        image_path,
        profile_id="defiance",
        capture_state=fake_capture,
        image_source=pipeline_module.IMAGE_SOURCE_LIVE_CAPTURE,
    )

    assert report.selected_detail_correlation["correlated"] is True
    assert report.selected_detail_correlation["selected_row_id"] == "frame-1:row:8"
    assert report.selected_detail_correlation["highlight_scores"]["frame-1:row:8"]["horizontal_border"] is True


def test_build_session_report_preserves_separate_row_and_detail_provenance(monkeypatch, tmp_path: Path) -> None:
    from ocring.ocr import pipeline as pipeline_module
    from ocring.ocr.screen_classifier import ScreenClass, ScreenClassification
    from PIL import Image, ImageDraw

    image_path = tmp_path / "frame.png"
    image = Image.new("RGB", (1366, 768), (20, 20, 20))
    draw = ImageDraw.Draw(image)
    inventory_region = Rect(51, 63, 982, 654)
    row_11 = Rect(90, 552, 520, 590)
    draw.rectangle((row_11.x1, row_11.y2 - 6, row_11.x2, row_11.y2), fill=(220, 130, 50))
    image.save(image_path)

    def make_capture(frame_id: str, capture_timestamp: float) -> SimpleNamespace:
        return SimpleNamespace(
            frame=SimpleNamespace(
                frame_id=frame_id,
                session_id="session-1",
                profile_id="defiance",
                timestamp_utc=datetime.now(timezone.utc).isoformat(),
                image=SimpleNamespace(path=str(image_path), width=1366, height=768),
                inventory_region=inventory_region,
                detector_name="profile_roi_projection",
            ),
            ocr_engine=OcrEngineSummary(engine_name="rapidocr", available=True, reason="test"),
            quality=SimpleNamespace(action=SimpleNamespace(value="keep"), sharpness=0.9, motion_penalty=0.0, contrast=0.8, occlusion_penalty=0.0, partial_row_penalty=0.0, reasons=()),
            row_zones=(SimpleNamespace(row_id=f"{frame_id}:row:11", row_bounds=row_11, fields={}),),
            preprocessed_regions=(),
            capture_timestamp=capture_timestamp,
            row_signatures={11: "row-11"},
            screen_classification=ScreenClassification(ScreenClass.INVENTORY, "PANEL_GEOMETRY_HEURISTIC"),
            debug_capture_enabled=False,
        )

    fake_capture = make_capture("frame-1", 1.0)
    fake_capture_2 = make_capture("frame-2", 2.0)

    def fake_run(self, *, prepared_crops, profile_id, **kwargs):
        del self, profile_id, kwargs
        attempts = []
        for crop in prepared_crops:
            normalized = ""
            raw_text = ""
            confidence = 0.0
            status = OcrEngineStatus.ERROR
            reasons = ("EMPTY_OCR_TEXT",)
            if crop.field_kind is FieldKind.ITEM_NAME:
                normalized = "Perimeter Overthruster IV"
                raw_text = normalized
                confidence = 0.95
                status = OcrEngineStatus.OK
                reasons = ()
            elif crop.field_kind is FieldKind.ITEM_TYPE and str(crop.crop_id).startswith("detail-"):
                normalized = "Barrel"
                raw_text = normalized
                confidence = 0.82
                status = OcrEngineStatus.OK
                reasons = ()
            elif crop.field_kind is FieldKind.ITEM_SYNERGY and str(crop.crop_id).startswith("detail-"):
                normalized = "Synergy: Sol's Prominence"
                raw_text = normalized
                confidence = 0.97
                status = OcrEngineStatus.OK
                reasons = ()
            attempts.append(
                OcrAttempt(
                    crop_id=crop.crop_id,
                    row_id=crop.row_id,
                    field_kind=crop.field_kind,
                    variant=crop.variant,
                    engine_name="rapidocr",
                    status=status,
                    raw_text=raw_text,
                    normalized_text=normalized,
                    confidence=confidence,
                    reasons=reasons,
                )
            )
        return SimpleNamespace(
            ocr_attempts=tuple(attempts),
            field_candidates=build_field_candidates(tuple(attempts), profile_id="defiance"),
            recognition_mode_used="Classic-Only",
        )

    monkeypatch.setattr(pipeline_module, "_capture_frame_state", lambda *args, **kwargs: fake_capture)
    monkeypatch.setattr(pipeline_module.RecognitionOrchestrator, "run", fake_run)
    monkeypatch.setattr(
        pipeline_module,
        "run_ocr_attempts",
        lambda image_path, prepared_crops, max_attempts=0: tuple(
            OcrAttempt(
                crop_id=crop.crop_id,
                row_id=crop.row_id,
                field_kind=crop.field_kind,
                variant=crop.variant,
                engine_name="rapidocr",
                status=OcrEngineStatus.OK,
                raw_text="Perimeter Overthruster IV",
                normalized_text="Perimeter Overthruster IV",
                confidence=0.96,
                reasons=(),
            )
            for crop in prepared_crops
        ),
    )

    report = pipeline_module._build_frame_report(
        image_path,
        profile_id="defiance",
        capture_state=fake_capture,
        image_source=pipeline_module.IMAGE_SOURCE_LIVE_CAPTURE,
    )
    report_2 = pipeline_module._build_frame_report(
        image_path,
        profile_id="defiance",
        capture_state=fake_capture_2,
        image_source=pipeline_module.IMAGE_SOURCE_LIVE_CAPTURE,
    )
    session_report = pipeline_module._build_session_report((report, report_2), profile_id="defiance", scan_scope=ScanScope.CURRENT_PAGE)
    assembled = session_report["assembled_records"][0]

    assert assembled["fields"]["item_name"] == "Perimeter Overthruster IV"
    assert assembled["fields"]["item_type"] == "Barrel"
    assert assembled["fields"]["item_synergy"] == "Sol's Prominence"
    assert assembled["field_details"]["item_name"]["evidence_source"] == "row_list"
    assert assembled["field_details"]["item_type"]["evidence_source"] == "detail_panel"
    assert assembled["field_details"]["item_synergy"]["status"] == "OBSERVED"
    assert "REFERENCE_DATA_MISSING" in assembled["field_details"]["item_synergy"]["policy_result"]
    assert assembled["field_details"]["item_count"]["status"] == "FIELD_NOT_VISIBLE"
