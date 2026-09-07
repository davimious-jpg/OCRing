from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path

import pytest

import run_ocring
from ocring.ocr.capture_backend import WindowDescriptor
from ocring.ocr.event_bus import EventBus, UIEvent
from ocring.ui.main_window import MainWindow


class _FakeOverlay:
    def __init__(self, _master: tk.Misc, _event_bus: EventBus) -> None:
        self.visible = False
        self.snapshots = []
        self.recording_prepared = False
        self.handlers = {}
        self.prepare_calls = []

    def hide(self) -> None:
        self.visible = False

    def show(self) -> None:
        self.visible = True

    def prepare_recording(self, *, target_window_handle: int | None) -> None:
        self.recording_prepared = True
        self.target_window_handle = target_window_handle
        self.prepare_calls.append(target_window_handle)
        self.visible = True

    def set_recording_handlers(self, **handlers) -> None:
        self.handlers = dict(handlers)

    def apply_snapshot(self, snapshot) -> None:
        self.snapshots.append(snapshot)

    def close(self) -> None:
        return None


class _FakeHotkeyManager:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.hotkey = "Alt+F8"
        self.closed = False
        self.is_global_backend = False
        self.backend_scope_label = "window-scoped fallback"
        self.backend_status_label = "Alt+F8 via fake (window-scoped fallback)"

    def register(self) -> str:
        return "fake"

    def close(self) -> None:
        self.closed = True


class _FakeCaptureLoop:
    def __init__(self, *, event_bus: EventBus, session_id: str, target_window_handle: int | None, **_kwargs) -> None:
        self.event_bus = event_bus
        self.session_id = session_id
        self.target_window_handle = target_window_handle
        self.running = False

    def start_capture_loop(self) -> bool:
        self.running = True
        self.event_bus.publish(UIEvent.SCAN_STARTED, {"session_id": self.session_id})
        return True

    def stop_capture_loop(self) -> dict[str, object]:
        self.running = False
        self.event_bus.publish(UIEvent.SCAN_STOPPED, {"session_id": self.session_id})
        return {}

    def flush_pending_events(self) -> int:
        return 0


def _screen_factory(name: str):
    def build(master: tk.Misc) -> tk.Widget:
        frame = tk.Frame(master)
        tk.Label(frame, text=name).pack()
        return frame

    return build


def test_main_window_initializes_and_navigates(tmp_path: Path) -> None:
    screen_factories = {name: _screen_factory(name) for name in MainWindow.NAV_ITEMS}
    window = MainWindow(
        event_bus=EventBus(),
        settings_path=tmp_path / "settings.json",
        sessions_root=tmp_path / "sessions",
        overlay_factory=_FakeOverlay,
        hotkey_manager_factory=_FakeHotkeyManager,
        screen_factories=screen_factories,
    )
    window.withdraw()

    assert window.title() == "OCRing"
    assert window.current_screen == "Scan"

    window.show_screen("Settings")
    assert window.current_screen == "Settings"

    window.event_bus.publish(UIEvent.SCAN_START_REQUESTED, {})
    assert window.overlay_window.visible is True

    window._on_close()


def test_main_window_stop_scan_hands_off_to_review(tmp_path: Path) -> None:
    try:
        window = MainWindow(
            event_bus=EventBus(),
            settings_path=tmp_path / "settings.json",
            sessions_root=tmp_path / "sessions",
            overlay_factory=_FakeOverlay,
            hotkey_manager_factory=_FakeHotkeyManager,
        )
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable for main window review handoff check: {error}")
    window.withdraw()

    scan = window.screens["Scan"]
    scan.profile_var.set("defiance")
    scan.window_var.set("Window 1")
    scan.scope_var.set("Full")
    scan._test_capture()
    scan._start_scan()
    window.event_bus.publish(UIEvent.SCAN_STOP_REQUESTED, {})

    assert window.current_screen == "Review"
    assert any(message.event_type == UIEvent.REVIEW_SESSION_READY for message in window.event_bus.history())
    review_frame = window.screens["Review"]
    assert review_frame.winfo_children()

    window._on_close()


def test_main_window_prepares_before_overlay_control_starts_capture(tmp_path: Path) -> None:
    try:
        window = MainWindow(
            event_bus=EventBus(),
            settings_path=tmp_path / "settings.json",
            sessions_root=tmp_path / "sessions",
            overlay_factory=_FakeOverlay,
            hotkey_manager_factory=_FakeHotkeyManager,
            capture_loop_factory=_FakeCaptureLoop,
        )
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable for capture-control check: {error}")
    window.withdraw()

    window.event_bus.publish(
        UIEvent.SCAN_START_REQUESTED,
        {"session_id": "session-control", "window_handle": 101, "window_id": "Defiance [101]"},
    )
    assert window.scan_state == "READY_FOR_CAPTURE"
    assert window.capture_loop is not None
    assert not window.capture_loop.running
    assert window.overlay_window.recording_prepared is True
    assert "on_start_recording" in window.overlay_window.handlers

    window._begin_capture()
    assert window.capture_loop.running
    assert window.scan_state == "LIVE"

    window._stop_live_scan()
    assert window.current_screen == "Review"
    assert any(message.event_type == UIEvent.REVIEW_SESSION_READY for message in window.event_bus.history())
    window._on_close()


def test_main_window_top_and_lower_start_scan_converge_on_same_recording_overlay(monkeypatch, tmp_path: Path) -> None:
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
    monkeypatch.setattr("ocring.ui.scan_setup.list_available_windows", lambda: [live_game])
    try:
        window = MainWindow(
            event_bus=EventBus(),
            settings_path=tmp_path / "settings.json",
            sessions_root=tmp_path / "sessions",
            overlay_factory=_FakeOverlay,
            hotkey_manager_factory=_FakeHotkeyManager,
            capture_loop_factory=_FakeCaptureLoop,
        )
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable for canonical Start Scan check: {error}")
    window.withdraw()
    scan = window.screens["Scan"]
    scan.window_var.set("Defiance [101]")
    overlay = window.overlay_window

    scan.header_start_button.invoke()
    first_handlers = dict(overlay.handlers)
    first_overlay_id = id(overlay)

    scan.start_button.invoke()

    assert id(window.overlay_window) == first_overlay_id
    assert overlay.prepare_calls == [101, 101]
    assert overlay.target_window_handle == 101
    assert set(first_handlers) == {"on_start_recording", "on_stop_recording", "on_extract_recording"}
    assert set(overlay.handlers) == set(first_handlers)
    assert overlay.handlers["on_start_recording"] == first_handlers["on_start_recording"]
    assert overlay.handlers["on_stop_recording"] == first_handlers["on_stop_recording"]
    assert overlay.handlers["on_extract_recording"] == first_handlers["on_extract_recording"]
    assert window.scan_state == "READY_FOR_CAPTURE"

    window._on_close()


def test_main_window_recorded_review_ready_event_opens_review(tmp_path: Path) -> None:
    try:
        window = MainWindow(
            event_bus=EventBus(),
            settings_path=tmp_path / "settings.json",
            sessions_root=tmp_path / "sessions",
            overlay_factory=_FakeOverlay,
            hotkey_manager_factory=_FakeHotkeyManager,
            capture_loop_factory=_FakeCaptureLoop,
        )
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable for recorded review handoff check: {error}")
    window.withdraw()

    window.event_bus.publish(
        UIEvent.REVIEW_SESSION_READY,
        {
            "session_id": "recording-1",
            "recorded_capture_mode": True,
            "review_summary": {
                "automatically_stored": 1,
                "needs_manual_review": 2,
                "hold_unknown": 1,
            },
        },
    )

    assert window.current_screen == "Review"
    assert "REVIEW READY" in window.status_var.get()
    window._on_close()


def test_main_window_no_longer_injects_placeholder_review_record(tmp_path: Path) -> None:
    try:
        window = MainWindow(
            event_bus=EventBus(),
            settings_path=tmp_path / "settings.json",
            sessions_root=tmp_path / "sessions",
            overlay_factory=_FakeOverlay,
            hotkey_manager_factory=_FakeHotkeyManager,
        )
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable for placeholder review check: {error}")
    window.withdraw()
    window.active_scan_session_id = "session-empty"

    review_session = window._build_completed_review_session()

    assert review_session.session_id == "session-empty"
    assert review_session.records == []

    window._on_close()


def test_main_window_restores_and_persists_geometry_and_workspace(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    output_root = tmp_path / "output"
    settings_path.write_text(
        json.dumps(
            {
                "window_geometry": "1200x800+20+30",
                "output_root": str(output_root),
            }
        ),
        encoding="utf-8",
    )
    try:
        window = MainWindow(
            event_bus=EventBus(),
            settings_path=settings_path,
            overlay_factory=_FakeOverlay,
            hotkey_manager_factory=_FakeHotkeyManager,
        )
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable for geometry persistence check: {error}")
    window.update_idletasks()
    window.withdraw()

    assert window.runtime_settings.window_geometry == "1200x800+20+30"
    assert window.sessions_root == output_root / "sessions"

    window.geometry("1280x820+40+50")
    window._on_close()

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    saved_geometry = str(payload["window_geometry"])
    dimensions = saved_geometry.split("+", 1)[0]
    width_text, height_text = dimensions.split("x", 1)
    assert int(width_text) >= 640
    assert int(height_text) >= 480
    assert "+40+50" in saved_geometry
    assert payload["output_root"] == str(output_root)


def test_main_window_content_reflows_when_shell_resizes(tmp_path: Path) -> None:
    screen_factories = {name: _screen_factory(name) for name in MainWindow.NAV_ITEMS}
    try:
        window = MainWindow(
            event_bus=EventBus(),
            settings_path=tmp_path / "settings.json",
            sessions_root=tmp_path / "sessions",
            overlay_factory=_FakeOverlay,
            hotkey_manager_factory=_FakeHotkeyManager,
            screen_factories=screen_factories,
        )
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable for resize reflow check: {error}")

    window.update_idletasks()

    host_pack = window.content_host.pack_info()
    screen_grid = window.screens["Scan"].grid_info()

    assert str(host_pack["expand"]) == "1"
    assert str(host_pack["fill"]) == "both"
    assert "".join(sorted(screen_grid["sticky"])) == "ensw"
    assert int(window.content_host.grid_columnconfigure(0)["weight"]) == 1
    assert int(window.content_host.grid_rowconfigure(0)["weight"]) == 1

    window._on_close()


def test_scan_action_controls_are_hit_testable_after_vertical_scroll(tmp_path: Path) -> None:
    try:
        window = MainWindow(
            event_bus=EventBus(),
            settings_path=tmp_path / "settings.json",
            sessions_root=tmp_path / "sessions",
            overlay_factory=_FakeOverlay,
            hotkey_manager_factory=_FakeHotkeyManager,
        )
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable for scan action hit-test check: {error}")
    window.geometry("760x520+20+20")
    window.attributes("-topmost", True)
    window.update()
    scan = window.screens["Scan"]
    scan._window_descriptors = {
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
    scan.window_var.set("Defiance [101]")
    scan._refresh_ready_state()
    window.content_canvas.yview_moveto(1.0)
    window.update()

    for button_name in ("start_button", "record_button", "stop_recording_button", "extract_recording_button"):
        button = getattr(scan, button_name)
        center_x = button.winfo_rootx() + button.winfo_width() // 2
        center_y = button.winfo_rooty() + button.winfo_height() // 2
        owner = window.winfo_containing(center_x, center_y, displayof=window)
        assert owner == button

    assert str(scan.start_button.cget("state")) == "normal"
    assert str(scan.record_button.cget("state")) == "normal"
    window.attributes("-topmost", False)
    window._on_close()


def test_run_ocring_launches_main_window_without_cli_inputs(monkeypatch) -> None:
    called: list[str] = []

    monkeypatch.setattr(run_ocring, "launch_main_window", lambda: called.append("main") or 0)

    result = run_ocring.entrypoint([])

    assert result == 0
    assert called == ["main"]


def test_run_ocring_uses_cli_when_input_is_present(monkeypatch) -> None:
    called: list[str] = []

    monkeypatch.setattr(run_ocring, "cli_main", lambda: called.append("cli") or 0)

    result = run_ocring.entrypoint(["--input", "frame.png"])

    assert result == 0
    assert called == ["cli"]
