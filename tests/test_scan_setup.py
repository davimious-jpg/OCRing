from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from ocring.ocr.capture_backend import WindowDescriptor
from ocring.ocr.recorded_frame_source import RECORDING_MANIFEST, finalize_recording
from ocring.ui.event_bus import EventBus, UIEvent
from ocring.ui.scan_setup import ScanSetup


class FakeVar:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class FakeButton:
    def __init__(self) -> None:
        self.state = "normal"

    def configure(self, **kwargs) -> None:
        if "state" in kwargs:
            self.state = kwargs["state"]


class FakeCombo:
    def __init__(self) -> None:
        self.values = ()

    def configure(self, **kwargs) -> None:
        if "values" in kwargs:
            self.values = kwargs["values"]


class FakeOverlay:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.waiting: list[str] = []
        self.processing = False
        self.hidden = False
        self.finalizing = False
        self.recorded_ready = False

    def mark_recording_failed(self, reason: str) -> None:
        self.failures.append(reason)

    def mark_recording_waiting(self, reason: str = "target") -> None:
        self.waiting.append(reason)

    def mark_recording_processing(self) -> None:
        self.processing = True

    def mark_recording_finalizing(self) -> None:
        self.finalizing = True

    def mark_recorded_ready(self) -> None:
        self.recorded_ready = True

    def hide(self) -> None:
        self.hidden = True


class FakeRecorder:
    instances = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.started = False
        FakeRecorder.instances.append(self)

    def start(self) -> bool:
        self.started = True
        return True

    def stop(self):
        recording_dir = self.kwargs["recording_dir"]
        recording_dir.mkdir(parents=True, exist_ok=True)
        frame_path = recording_dir / "frame-000001.png"
        Image.new("RGB", (8, 8), (30, 30, 30)).save(frame_path)
        return SimpleNamespace(
            recording_dir=recording_dir,
            session_id=self.kwargs["session_id"],
            requested_fps=self.kwargs.get("requested_fps", 12.0),
            duration_seconds=1.0,
            source_frames=1,
            dropped_frames=0,
            achieved_fps=11.8,
            bytes_written=frame_path.stat().st_size,
            disk_write_mbps=0.75,
            memory_growth_bytes=0,
            sequence_gaps=0,
            first_sequence_id=1,
            last_sequence_id=1,
            cpu_user_seconds=0.0,
            cpu_system_seconds=0.0,
            as_dict=lambda: {
                "recording_dir": str(recording_dir),
                "session_id": self.kwargs["session_id"],
                "requested_fps": self.kwargs.get("requested_fps", 12.0),
                "duration_seconds": 1.0,
                "source_frames": 1,
                "dropped_frames": 0,
                "achieved_fps": 11.8,
                "bytes_written": frame_path.stat().st_size,
                "disk_write_mbps": 0.75,
                "memory_growth_bytes": 0,
                "sequence_gaps": 0,
                "first_sequence_id": 1,
                "last_sequence_id": 1,
                "cpu_user_seconds": 0.0,
                "cpu_system_seconds": 0.0,
            },
        )


def wait_for(predicate, *, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def finalize_test_recording(recording_dir: Path, *, session_id: str = "recording-1") -> None:
    recording_dir.mkdir(parents=True, exist_ok=True)
    frame_path = recording_dir / "frame-000001.png"
    Image.new("RGB", (8, 8), (30, 30, 30)).save(frame_path)
    finalize_recording(
        recording_dir,
        SimpleNamespace(
            recording_dir=recording_dir,
            session_id=session_id,
            requested_fps=12.0,
            duration_seconds=1.0,
            source_frames=1,
            dropped_frames=0,
            achieved_fps=1.0,
            bytes_written=frame_path.stat().st_size,
            disk_write_mbps=0.001,
            memory_growth_bytes=0,
            sequence_gaps=0,
            first_sequence_id=1,
            last_sequence_id=1,
            cpu_user_seconds=0.0,
            cpu_system_seconds=0.0,
            as_dict=lambda: {
                "recording_dir": str(recording_dir),
                "session_id": session_id,
                "requested_fps": 12.0,
                "duration_seconds": 1.0,
                "source_frames": 1,
                "dropped_frames": 0,
                "achieved_fps": 1.0,
                "bytes_written": frame_path.stat().st_size,
                "disk_write_mbps": 0.001,
                "memory_growth_bytes": 0,
                "sequence_gaps": 0,
                "first_sequence_id": 1,
                "last_sequence_id": 1,
                "cpu_user_seconds": 0.0,
                "cpu_system_seconds": 0.0,
            },
        ),
    )


def test_scan_setup_publishes_scan_start_requested() -> None:
    bus = EventBus()
    received = []
    bus.subscribe(UIEvent.SCAN_START_REQUESTED, lambda message: received.append(message.payload))
    widget = object.__new__(ScanSetup)
    widget.event_bus = bus
    widget.profile_var = FakeVar("defiance")
    widget.window_var = FakeVar("")
    widget.scope_var = FakeVar("Full")
    widget.mode_var = FakeVar("Balanced")
    widget.memory_limit_var = FakeVar("3 GB")
    widget.profile_var.set("defiance")
    widget.window_var.set("Defiance [101]")
    widget.scope_var.set("Full")
    widget.mode_var.set("Balanced")
    widget.memory_limit_var.set("3 GB")
    widget.target_status_var = FakeVar()
    widget.next_action_var = FakeVar()
    widget.start_button = FakeButton()
    widget.header_start_button = FakeButton()
    widget.record_button = FakeButton()
    widget.stop_recording_button = FakeButton()
    widget.extract_recording_button = FakeButton()
    widget._window_descriptors = {
        "Defiance [101]": WindowDescriptor(
            handle=101,
            title="Defiance",
            left=0,
            top=0,
            right=1280,
            bottom=720,
            is_visible=True,
            is_foreground=True,
        )
    }
    widget._perform_test_capture = lambda: {"success": True, "error_message": ""}

    widget._start_scan()

    assert received == [
        {
            "session_id": received[0]["session_id"],
            "profile_id": "defiance",
            "window_id": "Defiance [101]",
            "window_handle": 101,
            "window_title": "Defiance",
            "window_class": "",
            "window_pid": 0,
            "scan_scope": "Full",
            "recognition_mode": "Balanced",
            "memory_limit": "3 GB",
        }
    ]


def test_scan_setup_ready_state_disables_start_without_window() -> None:
    widget = object.__new__(ScanSetup)
    widget.window_var = FakeVar("")
    widget.scope_var = FakeVar("Full")
    widget.mode_var = FakeVar("Balanced")
    widget.target_status_var = FakeVar()
    widget.next_action_var = FakeVar()
    widget.start_button = FakeButton()
    widget.header_start_button = FakeButton()
    widget.record_button = FakeButton()
    widget.stop_recording_button = FakeButton()
    widget.extract_recording_button = FakeButton()
    widget._window_descriptors = {}

    ready = widget._refresh_ready_state()

    assert ready is False
    assert widget.start_button.state == "disabled"
    assert widget.header_start_button.state == "disabled"
    assert widget.record_button.state == "disabled"
    assert widget.target_status_var.get() == "Target: no game window selected"


def test_scan_setup_ready_state_enables_start_for_visible_window() -> None:
    widget = object.__new__(ScanSetup)
    widget.window_var = FakeVar("Defiance [101]")
    widget.scope_var = FakeVar("Mods")
    widget.mode_var = FakeVar("Balanced")
    widget.target_status_var = FakeVar()
    widget.next_action_var = FakeVar()
    widget.start_button = FakeButton()
    widget.header_start_button = FakeButton()
    widget.record_button = FakeButton()
    widget.stop_recording_button = FakeButton()
    widget.extract_recording_button = FakeButton()
    widget._window_descriptors = {
        "Defiance [101]": WindowDescriptor(
            handle=101,
            title="Defiance",
            left=0,
            top=0,
            right=1366,
            bottom=768,
            is_visible=True,
            is_foreground=True,
        )
    }

    ready = widget._refresh_ready_state()

    assert ready is True
    assert widget.start_button.state == "normal"
    assert widget.header_start_button.state == "normal"
    assert widget.record_button.state == "normal"
    assert "Defiance [101]" in widget.target_status_var.get()
    assert "Scope: Mods" in widget.next_action_var.get()


def test_scan_setup_prefers_visible_gameplay_defiance_over_stale_matching_title(monkeypatch) -> None:
    widget = object.__new__(ScanSetup)
    widget.window_var = FakeVar("Defiance notes - Visual Studio Code [202]")
    widget.status_var = FakeVar()
    widget.target_status_var = FakeVar()
    widget.next_action_var = FakeVar()
    widget.scope_var = FakeVar("Mods")
    widget.mode_var = FakeVar("Balanced")
    widget.start_button = FakeButton()
    widget.header_start_button = FakeButton()
    widget.record_button = FakeButton()
    widget.stop_recording_button = FakeButton()
    widget.extract_recording_button = FakeButton()
    widget.window_combo = FakeCombo()
    stale_editor = WindowDescriptor(
        handle=202,
        title="Defiance notes - Visual Studio Code",
        left=0,
        top=0,
        right=1400,
        bottom=900,
        is_visible=True,
        is_foreground=False,
        class_name="Chrome_WidgetWin_1",
    )
    minimized_game = WindowDescriptor(
        handle=303,
        title="Defiance",
        left=0,
        top=0,
        right=1366,
        bottom=768,
        is_visible=True,
        is_foreground=False,
        class_name="LaunchUnrealUWindowsClient",
        is_iconic=True,
    )
    live_game = WindowDescriptor(
        handle=101,
        title="Defiance",
        left=0,
        top=0,
        right=1366,
        bottom=768,
        is_visible=True,
        is_foreground=True,
        class_name="LaunchUnrealUWindowsClient",
    )
    monkeypatch.setattr("ocring.ui.scan_setup.list_available_windows", lambda: [stale_editor, minimized_game, live_game])

    widget._refresh_window_choices()

    assert widget.window_var.get() == "Defiance [101]"
    assert widget.start_button.state == "normal"
    assert widget.record_button.state == "normal"


def test_scan_setup_keeps_minimized_defiance_selected_instead_of_overlay(monkeypatch) -> None:
    widget = object.__new__(ScanSetup)
    widget.window_var = FakeVar("")
    widget.status_var = FakeVar()
    widget.target_status_var = FakeVar()
    widget.next_action_var = FakeVar()
    widget.scope_var = FakeVar("Full")
    widget.mode_var = FakeVar("Balanced")
    widget.start_button = FakeButton()
    widget.header_start_button = FakeButton()
    widget.record_button = FakeButton()
    widget.stop_recording_button = FakeButton()
    widget.extract_recording_button = FakeButton()
    widget.window_combo = FakeCombo()
    minimized_game = WindowDescriptor(
        handle=303,
        title="Defiance",
        left=-10667,
        top=-10667,
        right=-10511,
        bottom=-10643,
        is_visible=True,
        is_foreground=False,
        class_name="TwnAppWindowClass",
        is_iconic=True,
    )
    geforce_overlay = WindowDescriptor(
        handle=404,
        title="NVIDIA GeForce Overlay",
        left=0,
        top=0,
        right=1280,
        bottom=720,
        is_visible=True,
        is_foreground=False,
        class_name="CEF-OSC-WIDGET",
    )
    monkeypatch.setattr("ocring.ui.scan_setup.list_available_windows", lambda: [geforce_overlay, minimized_game])

    widget._refresh_window_choices()

    assert widget.window_var.get() == "Defiance [303]"
    assert widget.start_button.state == "normal"
    assert widget.record_button.state == "normal"
    assert "not capture-ready" in widget.target_status_var.get()


def test_scan_setup_recording_controls_capture_pixels_without_ocr(tmp_path: Path) -> None:
    bus = EventBus()
    widget = object.__new__(ScanSetup)
    widget.event_bus = bus
    widget.capture_backend = object()
    widget.recorder_factory = FakeRecorder
    widget.output_workspace_factory = lambda: SimpleNamespace(root=tmp_path, sessions_dir=tmp_path / "sessions")
    widget.window_var = FakeVar("Defiance [101]")
    widget.profile_var = FakeVar("defiance")
    widget.scope_var = FakeVar("Mods")
    widget.mode_var = FakeVar("Balanced")
    widget.status_var = FakeVar()
    widget.target_status_var = FakeVar()
    widget.next_action_var = FakeVar()
    widget.record_button = FakeButton()
    widget.stop_recording_button = FakeButton()
    widget.extract_recording_button = FakeButton()
    widget.start_button = FakeButton()
    widget.header_start_button = FakeButton()
    widget._window_descriptors = {
        "Defiance [101]": WindowDescriptor(
            handle=101,
            title="Defiance",
            left=0,
            top=0,
            right=1366,
            bottom=768,
            is_visible=True,
            is_foreground=True,
        )
    }

    widget._start_recording()

    assert FakeRecorder.instances[-1].started is True
    assert FakeRecorder.instances[-1].kwargs["target_window_handle"] == 101
    assert [message.event_type for message in bus.history()] == [
        UIEvent.START_RECORDING_CALLBACK_ENTERED,
        UIEvent.RECORDER_START_REQUESTED,
        UIEvent.RECORDER_STARTED,
    ]
    assert "Recording pixels only" in widget.status_var.get()
    assert widget.record_button.state == "disabled"
    assert widget.stop_recording_button.state == "normal"
    assert widget.extract_recording_button.state == "disabled"

    widget._stop_recording()

    assert "Recording verified: 1 frames" in widget.status_var.get()
    assert widget.record_button.state == "normal"
    assert widget.stop_recording_button.state == "disabled"
    assert widget.extract_recording_button.state == "normal"


def test_scan_setup_recording_start_failure_is_visible(tmp_path: Path) -> None:
    class FailingRecorder:
        def __init__(self, **_kwargs) -> None:
            return None

        def start(self) -> bool:
            return False

    bus = EventBus()
    widget = object.__new__(ScanSetup)
    widget.event_bus = bus
    widget.capture_backend = object()
    widget.recorder_factory = FailingRecorder
    widget.output_workspace_factory = lambda: SimpleNamespace(root=tmp_path, sessions_dir=tmp_path / "sessions")
    widget.window_var = FakeVar("Defiance [101]")
    widget.profile_var = FakeVar("defiance")
    widget.scope_var = FakeVar("Mods")
    widget.mode_var = FakeVar("Balanced")
    widget.status_var = FakeVar()
    widget.target_status_var = FakeVar()
    widget.next_action_var = FakeVar()
    widget.record_button = FakeButton()
    widget.stop_recording_button = FakeButton()
    widget.extract_recording_button = FakeButton()
    widget.start_button = FakeButton()
    widget.header_start_button = FakeButton()
    widget._window_descriptors = {
        "Defiance [101]": WindowDescriptor(
            handle=101,
            title="Defiance",
            left=0,
            top=0,
            right=1366,
            bottom=768,
            is_visible=True,
            is_foreground=True,
        )
    }

    widget._start_recording()

    assert "recorder did not enter running state" in widget.status_var.get()
    assert [message.event_type for message in bus.history()] == [
        UIEvent.START_RECORDING_CALLBACK_ENTERED,
        UIEvent.RECORDER_START_REQUESTED,
        UIEvent.RECORDER_START_FAILED,
    ]


def test_scan_setup_recording_waits_for_minimized_target_without_dead_error(tmp_path: Path) -> None:
    bus = EventBus()
    overlay = FakeOverlay()
    widget = object.__new__(ScanSetup)
    widget.event_bus = bus
    widget.capture_backend = object()
    widget.recorder_factory = FakeRecorder
    widget.output_workspace_factory = lambda: SimpleNamespace(root=tmp_path, sessions_dir=tmp_path / "sessions")
    widget.window_var = FakeVar("Defiance [303]")
    widget.profile_var = FakeVar("defiance")
    widget.status_var = FakeVar()
    widget.target_status_var = FakeVar()
    widget.next_action_var = FakeVar()
    widget.record_button = FakeButton()
    widget.stop_recording_button = FakeButton()
    widget.extract_recording_button = FakeButton()
    widget.start_button = FakeButton()
    widget.header_start_button = FakeButton()
    widget._recording_overlay = overlay
    widget._window_descriptors = {
        "Defiance [303]": WindowDescriptor(
            handle=303,
            title="Defiance",
            left=-10667,
            top=-10667,
            right=-10511,
            bottom=-10643,
            is_visible=True,
            is_foreground=False,
            is_iconic=True,
        )
    }

    widget._refresh_ready_state()
    widget._start_recording()

    assert widget.start_button.state == "normal"
    assert widget.record_button.state == "normal"
    assert "Waiting for target" in widget.status_var.get()
    assert overlay.failures == []
    assert overlay.waiting == ["target"]
    assert bus.history()[-1].event_type == UIEvent.RECORDER_START_FAILED
    assert bus.history()[-1].payload["reason"] == "WINDOW_NOT_CAPTURE_READY"


def test_scan_setup_control_state_matrix_separates_arm_record_and_extract() -> None:
    widget = object.__new__(ScanSetup)
    widget.window_var = FakeVar("")
    widget.scope_var = FakeVar("Mods")
    widget.mode_var = FakeVar("Balanced")
    widget.target_status_var = FakeVar()
    widget.next_action_var = FakeVar()
    widget.start_button = FakeButton()
    widget.header_start_button = FakeButton()
    widget.record_button = FakeButton()
    widget.stop_recording_button = FakeButton()
    widget.extract_recording_button = FakeButton()
    widget._recording_active = False
    widget._has_recording = False
    widget._recording_finalizing = False
    widget._recording_verified = False
    widget._extraction_active = False
    widget._window_descriptors = {}

    widget._refresh_ready_state()
    assert (widget.start_button.state, widget.record_button.state, widget.stop_recording_button.state, widget.extract_recording_button.state) == (
        "disabled",
        "disabled",
        "disabled",
        "disabled",
    )

    widget._window_descriptors = {
        "Defiance [303]": WindowDescriptor(
            handle=303,
            title="Defiance",
            left=-10667,
            top=-10667,
            right=-10511,
            bottom=-10643,
            is_visible=True,
            is_foreground=False,
            is_iconic=True,
        )
    }
    widget.window_var.set("Defiance [303]")
    widget._refresh_ready_state()
    assert (widget.start_button.state, widget.record_button.state, widget.stop_recording_button.state, widget.extract_recording_button.state) == (
        "normal",
        "normal",
        "disabled",
        "disabled",
    )

    widget._window_descriptors = {
        "Defiance [101]": WindowDescriptor(
            handle=101,
            title="Defiance",
            left=0,
            top=0,
            right=1366,
            bottom=768,
            is_visible=True,
            is_foreground=True,
        )
    }
    widget.window_var.set("Defiance [101]")
    widget._refresh_ready_state()
    assert (widget.start_button.state, widget.record_button.state, widget.stop_recording_button.state, widget.extract_recording_button.state) == (
        "normal",
        "normal",
        "disabled",
        "disabled",
    )

    widget._set_recording_state(recording=True, has_recording=False)
    assert (widget.start_button.state, widget.record_button.state, widget.stop_recording_button.state, widget.extract_recording_button.state) == (
        "normal",
        "disabled",
        "normal",
        "disabled",
    )

    widget._set_recording_state(recording=False, has_recording=True)
    widget._recording_verified = True
    widget._sync_recording_controls()
    assert (widget.start_button.state, widget.record_button.state, widget.stop_recording_button.state, widget.extract_recording_button.state) == (
        "normal",
        "normal",
        "disabled",
        "normal",
    )


def test_scan_setup_action_diagnostics_include_state_and_target() -> None:
    bus = EventBus()
    widget = object.__new__(ScanSetup)
    widget.event_bus = bus
    widget.window_var = FakeVar("Defiance [101]")
    widget.target_status_var = FakeVar("Target: Defiance [101] • 1366x768")
    widget.next_action_var = FakeVar("Next: Start Scan opens the READY overlay.")

    widget._publish_action_event("START_SCAN_MOUSE_ENTER", SimpleNamespace(cget=lambda key: "normal"))
    widget._publish_action_event("START_SCAN_CLICK", SimpleNamespace(cget=lambda key: "normal"))

    assert [message.event_type for message in bus.history()] == [
        UIEvent.START_SCAN_MOUSE_ENTER,
        UIEvent.START_SCAN_CLICK,
    ]
    assert bus.history()[0].payload["state"] == "normal"
    assert bus.history()[0].payload["window_id"] == "Defiance [101]"


def test_scan_setup_extract_recording_publishes_review_summary(tmp_path: Path) -> None:
    bus = EventBus()
    received = []
    bus.subscribe(UIEvent.REVIEW_SESSION_READY, lambda message: received.append(message.payload))
    widget = object.__new__(ScanSetup)
    widget.event_bus = bus
    widget.profile_var = FakeVar("defiance")
    widget.status_var = FakeVar()
    widget._last_recording_dir = tmp_path / "recordings" / "recording-1"
    finalize_test_recording(widget._last_recording_dir)
    widget._last_recording_session_id = "recording-1"
    widget._recording_active = False
    widget._has_recording = True
    widget._recording_finalizing = False
    widget._recording_verified = True
    widget._extraction_active = False
    widget._extraction_thread = None
    widget._recording_overlay = FakeOverlay()
    widget.window_var = FakeVar("Defiance [101]")
    widget.record_button = FakeButton()
    widget.stop_recording_button = FakeButton()
    widget.extract_recording_button = FakeButton()
    widget._window_descriptors = {
        "Defiance [101]": WindowDescriptor(
            handle=101,
            title="Defiance",
            left=0,
            top=0,
            right=1366,
            bottom=768,
            is_visible=True,
            is_foreground=True,
        )
    }
    widget.output_workspace_factory = lambda: SimpleNamespace(root=tmp_path, sessions_dir=tmp_path / "sessions")
    widget.extract_recording_func = lambda *_args, **_kwargs: {
        "assembled_records": [{}, {}],
        "coverage_summary": {
            "unique_entries_observed": 4,
            "stable_identities": 2,
            "coverage_gaps": 1,
        },
        "review_summary": {
            "automatically_stored": 1,
            "needs_manual_review": 1,
            "hold_unknown": 0,
        },
    }

    report = widget._extract_recording()

    assert report is None
    assert widget._recording_overlay.processing is True
    assert wait_for(lambda: len(received) == 1)
    assert "Entries observed 4" in widget.status_var.get()
    assert received == [
        {
            "session_id": "recording-1",
            "record_count": 2,
            "review_summary": {
                "automatically_stored": 1,
                "needs_manual_review": 1,
                "hold_unknown": 0,
            },
            "recorded_capture_mode": True,
        }
    ]
    assert widget._recording_overlay.hidden is True
    assert UIEvent.EXTRACTION_WORKER_START_REQUESTED in [message.event_type for message in bus.history()]
    assert UIEvent.EXTRACTION_WORKER_STARTED in [message.event_type for message in bus.history()]
    assert UIEvent.RECORDED_EXTRACTION_COMPLETED in [message.event_type for message in bus.history()]
    assert UIEvent.REVIEW_SESSION_READY_PUBLISHED in [message.event_type for message in bus.history()]


def test_scan_setup_extract_recording_returns_promptly_and_runs_off_ui_thread(tmp_path: Path) -> None:
    bus = EventBus()
    started = threading.Event()
    release = threading.Event()
    worker_thread_names: list[str] = []
    widget = object.__new__(ScanSetup)
    widget.event_bus = bus
    widget.profile_var = FakeVar("defiance")
    widget.status_var = FakeVar()
    widget._last_recording_dir = tmp_path / "recordings" / "recording-1"
    finalize_test_recording(widget._last_recording_dir)
    widget._last_recording_session_id = "recording-1"
    widget._recording_active = False
    widget._has_recording = True
    widget._recording_finalizing = False
    widget._recording_verified = True
    widget._extraction_active = False
    widget._extraction_thread = None
    widget._recording_overlay = FakeOverlay()
    widget.window_var = FakeVar("Defiance [101]")
    widget.record_button = FakeButton()
    widget.stop_recording_button = FakeButton()
    widget.extract_recording_button = FakeButton()
    widget._window_descriptors = {
        "Defiance [101]": WindowDescriptor(
            handle=101,
            title="Defiance",
            left=0,
            top=0,
            right=1366,
            bottom=768,
            is_visible=True,
            is_foreground=True,
        )
    }
    widget.output_workspace_factory = lambda: SimpleNamespace(root=tmp_path, sessions_dir=tmp_path / "sessions")

    def slow_extract(*_args, **_kwargs):
        worker_thread_names.append(threading.current_thread().name)
        started.set()
        release.wait(timeout=2)
        return {"assembled_records": [], "coverage_summary": {}, "review_summary": {}}

    widget.extract_recording_func = slow_extract

    begin = time.monotonic()
    result = widget._extract_recording()
    elapsed = time.monotonic() - begin

    assert result is None
    assert elapsed < 0.2
    assert started.wait(timeout=1)
    assert worker_thread_names[0].startswith("ocring-extract-")
    assert threading.current_thread().name != worker_thread_names[0]
    assert widget.extract_recording_button.state == "disabled"
    release.set()
    assert wait_for(lambda: widget._extraction_active is False)


def test_scan_setup_extract_recording_reports_progress_and_stalls(tmp_path: Path) -> None:
    bus = EventBus()
    progress: list[dict[str, object]] = []
    stalled: list[dict[str, object]] = []
    bus.subscribe(UIEvent.RECORDED_EXTRACTION_PROGRESS, lambda message: progress.append(message.payload))
    bus.subscribe(UIEvent.RECORDED_EXTRACTION_STALLED, lambda message: stalled.append(message.payload))
    release = threading.Event()
    widget = object.__new__(ScanSetup)
    widget.EXTRACTION_STALL_SECONDS = 0.05
    widget.event_bus = bus
    widget.profile_var = FakeVar("defiance")
    widget.status_var = FakeVar()
    widget._last_recording_dir = tmp_path / "recordings" / "recording-1"
    finalize_test_recording(widget._last_recording_dir)
    widget._last_recording_session_id = "recording-1"
    widget._recording_active = False
    widget._has_recording = True
    widget._recording_finalizing = False
    widget._recording_verified = True
    widget._extraction_active = False
    widget._extraction_thread = None
    widget._recording_overlay = FakeOverlay()
    widget.window_var = FakeVar("Defiance [101]")
    widget.record_button = FakeButton()
    widget.stop_recording_button = FakeButton()
    widget.extract_recording_button = FakeButton()
    widget._window_descriptors = {
        "Defiance [101]": WindowDescriptor(
            handle=101,
            title="Defiance",
            left=0,
            top=0,
            right=1366,
            bottom=768,
            is_visible=True,
            is_foreground=True,
        )
    }
    widget.output_workspace_factory = lambda: SimpleNamespace(root=tmp_path, sessions_dir=tmp_path / "sessions")

    def slow_extract(*_args, progress_callback=None, **_kwargs):
        assert progress_callback is not None
        progress_callback({"stage": "OCR", "current_index": 1, "total_count": 3})
        release.wait(timeout=2)
        return {"assembled_records": [], "coverage_summary": {}, "review_summary": {}}

    widget.extract_recording_func = slow_extract

    widget._extract_recording()

    assert wait_for(lambda: any(item.get("stage") == "OCR" for item in progress))
    assert wait_for(lambda: len(stalled) == 1)
    assert stalled[0]["stage"] == "OCR"
    assert "stalled at OCR" in widget.status_var.get()
    release.set()
    assert wait_for(lambda: widget._extraction_active is False)


def test_scan_setup_extract_recording_ignores_duplicate_clicks_while_worker_active(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()
    calls = 0
    widget = object.__new__(ScanSetup)
    widget.event_bus = EventBus()
    widget.profile_var = FakeVar("defiance")
    widget.status_var = FakeVar()
    widget._last_recording_dir = tmp_path / "recordings" / "recording-1"
    finalize_test_recording(widget._last_recording_dir)
    widget._last_recording_session_id = "recording-1"
    widget._recording_active = False
    widget._has_recording = True
    widget._recording_finalizing = False
    widget._recording_verified = True
    widget._extraction_active = False
    widget._extraction_thread = None
    widget._recording_overlay = FakeOverlay()
    widget.window_var = FakeVar("Defiance [101]")
    widget.record_button = FakeButton()
    widget.stop_recording_button = FakeButton()
    widget.extract_recording_button = FakeButton()
    widget._window_descriptors = {
        "Defiance [101]": WindowDescriptor(
            handle=101,
            title="Defiance",
            left=0,
            top=0,
            right=1366,
            bottom=768,
            is_visible=True,
            is_foreground=True,
        )
    }
    widget.output_workspace_factory = lambda: SimpleNamespace(root=tmp_path, sessions_dir=tmp_path / "sessions")

    def slow_extract(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=2)
        return {"assembled_records": [], "coverage_summary": {}, "review_summary": {}}

    widget.extract_recording_func = slow_extract

    widget._extract_recording()
    assert started.wait(timeout=1)
    widget._extract_recording()

    assert calls == 1
    assert "already processing" in widget.status_var.get()
    release.set()
    assert wait_for(lambda: widget._extraction_active is False)


def test_scan_setup_extract_recording_failure_restores_retry_state(tmp_path: Path) -> None:
    bus = EventBus()
    failed = []
    bus.subscribe(UIEvent.RECORDED_EXTRACTION_FAILED, lambda message: failed.append(message.payload))
    widget = object.__new__(ScanSetup)
    widget.event_bus = bus
    widget.profile_var = FakeVar("defiance")
    widget.status_var = FakeVar()
    widget._last_recording_dir = tmp_path / "recordings" / "recording-1"
    finalize_test_recording(widget._last_recording_dir)
    widget._last_recording_session_id = "recording-1"
    widget._recording_active = False
    widget._has_recording = True
    widget._recording_finalizing = False
    widget._recording_verified = True
    widget._extraction_active = False
    widget._extraction_thread = None
    widget._recording_overlay = FakeOverlay()
    widget.window_var = FakeVar("Defiance [101]")
    widget.record_button = FakeButton()
    widget.stop_recording_button = FakeButton()
    widget.extract_recording_button = FakeButton()
    widget._window_descriptors = {
        "Defiance [101]": WindowDescriptor(
            handle=101,
            title="Defiance",
            left=0,
            top=0,
            right=1366,
            bottom=768,
            is_visible=True,
            is_foreground=True,
        )
    }
    widget.output_workspace_factory = lambda: SimpleNamespace(root=tmp_path, sessions_dir=tmp_path / "sessions")

    def failing_extract(*_args, **_kwargs):
        raise RuntimeError("boom")

    widget.extract_recording_func = failing_extract

    widget._extract_recording()

    assert wait_for(lambda: len(failed) == 1)
    assert failed[0]["reason"] == "RuntimeError: boom"
    assert "Recording preserved for retry" in widget.status_var.get()
    assert widget.extract_recording_button.state == "normal"
    assert widget._recording_overlay.failures == ["extract failed"]


def test_scan_setup_extract_requires_recorded_verified_boundary(tmp_path: Path) -> None:
    widget = object.__new__(ScanSetup)
    widget.event_bus = EventBus()
    widget.profile_var = FakeVar("defiance")
    widget.status_var = FakeVar()
    widget._last_recording_dir = tmp_path / "recordings" / "recording-1"
    widget._last_recording_dir.mkdir(parents=True)
    widget._last_recording_session_id = "recording-1"
    widget._recording_active = False
    widget._recording_finalizing = False
    widget._recording_verified = False
    widget._has_recording = True
    widget._extraction_active = False
    widget._extraction_thread = None
    widget._recording_overlay = FakeOverlay()

    result = widget._extract_recording()

    assert result is None
    assert "RECORDED_VERIFIED" in widget.status_var.get()


def test_scan_setup_extract_recovers_valid_preserved_spool_before_extracting(tmp_path: Path) -> None:
    bus = EventBus()
    recovered = []
    bus.subscribe(UIEvent.RECORDING_FINALIZED, lambda message: recovered.append(message.payload))
    received = []
    bus.subscribe(UIEvent.REVIEW_SESSION_READY, lambda message: received.append(message.payload))
    widget = object.__new__(ScanSetup)
    widget.event_bus = bus
    widget.profile_var = FakeVar("defiance")
    widget.status_var = FakeVar()
    widget._last_recording_dir = tmp_path / "recordings" / "recording-1"
    widget._last_recording_dir.mkdir(parents=True)
    for index in range(1, 4):
        Image.new("RGB", (8, 8), (index * 30, index * 30, index * 30)).save(widget._last_recording_dir / f"frame-{index:06d}.png")
    widget._last_recording_session_id = "recording-1"
    widget._recording_active = False
    widget._recording_finalizing = False
    widget._recording_verified = False
    widget._has_recording = True
    widget._extraction_active = False
    widget._extraction_thread = None
    widget._recording_overlay = FakeOverlay()
    widget.window_var = FakeVar("Defiance [101]")
    widget.record_button = FakeButton()
    widget.stop_recording_button = FakeButton()
    widget.extract_recording_button = FakeButton()
    widget._window_descriptors = {
        "Defiance [101]": WindowDescriptor(
            handle=101,
            title="Defiance",
            left=0,
            top=0,
            right=1366,
            bottom=768,
            is_visible=True,
            is_foreground=True,
        )
    }
    widget.output_workspace_factory = lambda: SimpleNamespace(root=tmp_path, sessions_dir=tmp_path / "sessions")
    widget.extract_recording_func = lambda *_args, **_kwargs: {
        "assembled_records": [],
        "coverage_summary": {},
        "review_summary": {},
    }

    assert widget._extract_recording() is None

    assert wait_for(lambda: len(received) == 1)
    assert recovered[0]["recovered_from_spool"] is True
    assert recovered[0]["frame_count"] == 3
    assert widget._recording_verified is True


def test_scan_setup_extract_cannot_run_while_recording_or_finalizing(tmp_path: Path) -> None:
    widget = object.__new__(ScanSetup)
    widget.event_bus = EventBus()
    widget.profile_var = FakeVar("defiance")
    widget.status_var = FakeVar()
    widget._last_recording_dir = tmp_path / "recordings" / "recording-1"
    finalize_test_recording(widget._last_recording_dir)
    widget._last_recording_session_id = "recording-1"
    widget._recording_verified = True
    widget._has_recording = True
    widget._extraction_active = False
    widget._extraction_thread = None
    widget._frame_spool_recorder = object()
    widget._recording_active = True
    widget._recording_finalizing = False

    assert widget._extract_recording() is None
    assert "recording is active" in widget.status_var.get()

    widget._frame_spool_recorder = None
    widget._recording_active = False
    widget._recording_finalizing = True

    assert widget._extract_recording() is None
    assert "recording is finalizing" in widget.status_var.get()


def test_scan_setup_stop_finalizes_recording_before_extract_enabled(tmp_path: Path) -> None:
    bus = EventBus()
    overlay = FakeOverlay()
    widget = object.__new__(ScanSetup)
    widget.event_bus = bus
    widget.capture_backend = object()
    widget.recorder_factory = FakeRecorder
    widget.output_workspace_factory = lambda: SimpleNamespace(root=tmp_path, sessions_dir=tmp_path / "sessions")
    widget.window_var = FakeVar("Defiance [101]")
    widget.profile_var = FakeVar("defiance")
    widget.scope_var = FakeVar("Mods")
    widget.mode_var = FakeVar("Balanced")
    widget.status_var = FakeVar()
    widget.target_status_var = FakeVar()
    widget.next_action_var = FakeVar()
    widget.record_button = FakeButton()
    widget.stop_recording_button = FakeButton()
    widget.extract_recording_button = FakeButton()
    widget.start_button = FakeButton()
    widget.header_start_button = FakeButton()
    widget._recording_overlay = overlay
    widget._window_descriptors = {
        "Defiance [101]": WindowDescriptor(
            handle=101,
            title="Defiance",
            left=0,
            top=0,
            right=1366,
            bottom=768,
            is_visible=True,
            is_foreground=True,
        )
    }

    widget._start_recording()
    widget._stop_recording()

    assert overlay.finalizing is True
    assert overlay.recorded_ready is True
    assert widget._recording_verified is True
    assert widget.extract_recording_button.state == "normal"
    assert (widget._last_recording_dir / RECORDING_MANIFEST).exists()
    assert [message.event_type for message in bus.history() if message.event_type in {UIEvent.RECORDING_FINALIZING, UIEvent.RECORDING_FINALIZED}] == [
        UIEvent.RECORDING_FINALIZING,
        UIEvent.RECORDING_FINALIZED,
    ]


def test_scan_setup_stop_recovers_valid_spool_after_finalize_accounting_mismatch(tmp_path: Path) -> None:
    class MismatchedStopRecorder:
        def stop(self):
            raise ValueError("recording frame count mismatch: summary=0 files=3")

    bus = EventBus()
    finalized = []
    bus.subscribe(UIEvent.RECORDING_FINALIZED, lambda message: finalized.append(message.payload))
    failures = []
    bus.subscribe(UIEvent.RECORDING_FINALIZE_FAILED, lambda message: failures.append(message.payload))
    overlay = FakeOverlay()
    recording_dir = tmp_path / "recordings" / "recording-1"
    recording_dir.mkdir(parents=True)
    for index in range(1, 4):
        Image.new("RGB", (8, 8), (index * 30, index * 30, index * 30)).save(recording_dir / f"frame-{index:06d}.png")
    widget = object.__new__(ScanSetup)
    widget.event_bus = bus
    widget.status_var = FakeVar()
    widget.window_var = FakeVar("Defiance [101]")
    widget.record_button = FakeButton()
    widget.stop_recording_button = FakeButton()
    widget.extract_recording_button = FakeButton()
    widget._recording_overlay = overlay
    widget._frame_spool_recorder = MismatchedStopRecorder()
    widget._last_recording_dir = recording_dir
    widget._last_recording_session_id = "recording-1"
    widget._recording_active = True
    widget._recording_finalizing = False
    widget._recording_verified = False
    widget._has_recording = False
    widget._extraction_active = False
    widget._window_descriptors = {
        "Defiance [101]": WindowDescriptor(
            handle=101,
            title="Defiance",
            left=0,
            top=0,
            right=1366,
            bottom=768,
            is_visible=True,
            is_foreground=True,
        )
    }

    widget._stop_recording()

    assert failures[0]["reason"] == "ValueError: recording frame count mismatch: summary=0 files=3"
    assert failures[0]["recovered_from_spool"] is True
    assert finalized[0]["frame_count"] == 3
    assert finalized[0]["recovered_from_spool"] is True
    assert widget._recording_verified is True
    assert widget.extract_recording_button.state == "normal"
    assert overlay.recorded_ready is True
    assert "Recording recovered and verified: 3 frames" in widget.status_var.get()
