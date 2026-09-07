from __future__ import annotations

import tkinter as tk
from types import SimpleNamespace
import os

import pytest

from ocring.ui.event_bus import EventBus, UIEvent
from ocring.ui.overlay import OverlaySnapshot, OverlayStatusController, OverlayWindow, map_live_status, render_corner_overlay


def test_overlay_status_controller_reacts_to_capture_events() -> None:
    bus = EventBus()
    controller = OverlayStatusController(bus)

    bus.publish(UIEvent.CAPTURE_LOST, {"reason": "WINDOW_LOST"})
    assert controller.status_text == "PAUSED"

    bus.publish(UIEvent.CAPTURE_RECOVERED, {"reason": "WINDOW_BACK"})
    assert controller.status_text == "LIVE"

    bus.publish(UIEvent.SCAN_STOPPED, {"session_id": "s1"})
    assert controller.status_text == "READY"

    controller.close()


def test_render_corner_overlay_includes_status_text() -> None:
    rendered = render_corner_overlay(
        OverlaySnapshot(
            capture_fps=60,
            useful_fps=10,
            extraction_rate=5,
            verified_rate=2,
            queue_depth=1,
            continuity_status="OK",
            status_text="PAUSED",
        )
    )

    assert "Status:     PAUSED" in rendered


def test_live_status_mapping_keeps_capture_and_recognition_separate() -> None:
    assert map_live_status(capture_status="LIVE", screen_class="inventory", recognition_hold=False) == "INV"
    assert map_live_status(capture_status="LIVE", screen_class="inventory", recognition_hold=True) == "HOLD"
    assert map_live_status(capture_status="LIVE", screen_class="unknown", recognition_hold=False) == "NOT INVENTORY"
    assert map_live_status(capture_status="READY", screen_class="inventory", recognition_hold=True) == "READY"


def test_frame_analysis_does_not_change_capture_liveness() -> None:
    bus = EventBus()
    controller = OverlayStatusController(bus)
    bus.publish(UIEvent.SCAN_STARTED, {})
    assert controller.status_text == "LIVE"
    assert map_live_status(capture_status=controller.status_text, screen_class="inventory", recognition_hold=True) == "HOLD"
    assert controller.status_text == "LIVE"
    controller.close()


def test_overlay_window_sets_topmost_before_showing() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable for overlay topmost check: {error}")
    root.withdraw()

    overlay = OverlayWindow(root, EventBus())
    overlay.show()
    root.update_idletasks()

    assert int(overlay.window.attributes("-topmost")) == 1
    assert overlay.window.overrideredirect() is True
    assert overlay._overlay_width >= OverlayWindow.MIN_WIDTH
    assert overlay._overlay_height >= OverlayWindow.MIN_HEIGHT

    overlay.close()
    root.destroy()


def test_overlay_control_surface_transitions_ready_recording_and_stop() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable for overlay control check: {error}")
    root.withdraw()
    bus = EventBus()
    started: list[bool] = []
    stopped: list[bool] = []
    overlay = OverlayWindow(root, bus)
    overlay.set_control_handlers(on_start_capture=lambda: started.append(True), on_stop_capture=lambda: stopped.append(True))
    overlay.prepare_capture(target_window_handle=None)
    root.update()

    assert overlay.status_var.get() == "OCRing | READY"
    assert overlay.control_button.cget("text") == "Start Capture"
    overlay.control_button.invoke()
    assert started == [True]

    bus.publish(UIEvent.SCAN_STARTED, {})
    root.update()
    assert "REC" in overlay.status_var.get()
    assert overlay.control_button.cget("text") == "Stop"

    bus.publish(UIEvent.FRAME_CAPTURED, {"capture_timestamp": 1.0, "buffer_bytes": 0})
    root.update()
    assert "F:1" in overlay.status_var.get()
    overlay.control_button.invoke()
    assert stopped == [True]

    bus.publish(UIEvent.SCAN_STOPPED, {})
    root.update()
    assert not overlay.window.winfo_viewable()
    overlay.close()
    root.destroy()


def test_overlay_recording_controls_show_record_stop_extract_states() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable for overlay recording check: {error}")
    root.withdraw()
    started: list[bool] = []
    stopped: list[bool] = []
    extracted: list[bool] = []
    bus = EventBus()
    overlay = OverlayWindow(root, bus)
    overlay.set_recording_handlers(
        on_start_recording=lambda: started.append(True),
        on_stop_recording=lambda: stopped.append(True),
        on_extract_recording=lambda: extracted.append(True),
    )
    overlay.prepare_recording(target_window_handle=None)
    root.update()

    assert overlay.status_var.get() == "OCRing | READY"
    assert overlay.control_button.cget("text") == "Record"
    assert overlay._click_through_enabled is False

    overlay.control_button.invoke()
    assert started == [True]
    assert bus.history()[-2].event_type == UIEvent.OVERLAY_RECORD_CLICK_RECEIVED
    assert bus.history()[-1].event_type == UIEvent.OVERLAY_RECORD_CALLBACK_ENTERED

    overlay.mark_recording_active()
    root.update()
    assert overlay.status_var.get().startswith("OCRing ● REC")
    assert overlay.control_button.cget("text") == "Stop"

    overlay.mark_recorded_ready()
    root.update()
    assert overlay.status_var.get() == "OCRing | RECORDED ✓"
    assert overlay.control_button.cget("text") == "Extract"

    overlay.control_button.invoke()
    assert extracted == [True]
    assert any(message.event_type == UIEvent.OVERLAY_EXTRACT_CLICK_RECEIVED for message in bus.history())

    overlay.close()
    root.destroy()


def test_overlay_recording_waiting_state_keeps_record_available() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable for overlay waiting check: {error}")
    root.withdraw()
    overlay = OverlayWindow(root, EventBus())
    overlay.prepare_recording(target_window_handle=None)
    root.update()

    overlay.mark_recording_waiting("target")
    root.update()

    assert overlay.status_var.get() == "OCRing | WAITING FOR TARGET"
    assert overlay.control_button.cget("text") == "Record"
    assert str(overlay.control_button.cget("state")) == "normal"
    overlay.close()
    root.destroy()


def test_overlay_recording_processing_shows_progress_and_stall() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable for overlay progress check: {error}")
    root.withdraw()
    bus = EventBus()
    overlay = OverlayWindow(root, bus)
    overlay.prepare_recording(target_window_handle=None)
    overlay.mark_recording_processing()
    root.update()

    bus.publish(UIEvent.RECORDED_EXTRACTION_PROGRESS, {"stage": "OCR", "current_index": 12, "total_count": 40})
    root.update()
    assert overlay.status_var.get() == "OCRing | OCR 12/40"

    bus.publish(UIEvent.RECORDED_EXTRACTION_STALLED, {"stage": "OCR", "inactive_seconds": 30})
    root.update()
    assert overlay.status_var.get() == "OCRing | STALLED: OCR"

    overlay.close()
    root.destroy()


def test_overlay_recording_control_window_is_not_click_through_on_windows() -> None:
    if os.name != "nt":
        pytest.skip("Native overlay hit-test styles are Windows-specific.")
    try:
        import ctypes

        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable for native overlay style check: {error}")
    root.withdraw()
    overlay = OverlayWindow(root, EventBus())
    overlay.prepare_recording(target_window_handle=None)
    root.update()

    hwnd = overlay._native_overlay_hwnd()
    user32 = ctypes.windll.user32
    user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    extended_style = int(user32.GetWindowLongPtrW(ctypes.c_void_p(hwnd), -20))

    assert hwnd
    assert extended_style & 0x00000080  # WS_EX_TOOLWINDOW
    assert extended_style & 0x08000000  # WS_EX_NOACTIVATE
    assert extended_style & 0x00080000  # WS_EX_LAYERED
    assert not extended_style & 0x00000020  # WS_EX_TRANSPARENT would pass Record clicks through.

    overlay.close()
    root.destroy()


def test_overlay_drag_persists_and_restores_user_placement(tmp_path) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable for overlay drag check: {error}")
    root.withdraw()
    settings_path = tmp_path / "settings.json"
    overlay = OverlayWindow(root, EventBus(), settings_path=settings_path)
    overlay.show()
    root.update()

    start_x = overlay.window.winfo_rootx()
    start_y = overlay.window.winfo_rooty()
    overlay._start_drag(SimpleNamespace(x_root=start_x + 8, y_root=start_y + 8))
    overlay._drag_to(SimpleNamespace(x_root=start_x + 108, y_root=start_y + 58))
    overlay._finish_drag(SimpleNamespace())

    saved = overlay._user_position
    assert saved is not None
    assert settings_path.exists()
    overlay.close()

    restored = OverlayWindow(root, EventBus(), settings_path=settings_path)
    assert restored._user_position == saved
    restored.close()
    root.destroy()


def test_overlay_foreground_maintenance_only_raises_for_selected_target(monkeypatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable for overlay foreground check: {error}")
    root.withdraw()
    overlay = OverlayWindow(root, EventBus())
    overlay.show()
    root.update()
    overlay._target_window_handle = 4242
    raised: list[bool] = []
    monkeypatch.setattr(overlay, "_raise_native_topmost", lambda: raised.append(True) or True)
    monkeypatch.setattr(overlay, "_foreground_window_handle", lambda: 4242)

    overlay._maintain_foreground_topmost()
    assert raised == [True]

    monkeypatch.setattr(overlay, "_foreground_window_handle", lambda: 7)
    overlay._maintain_foreground_topmost()
    assert raised == [True]
    overlay.close()
    root.destroy()
