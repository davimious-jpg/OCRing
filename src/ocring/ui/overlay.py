from __future__ import annotations

import ctypes
import os
import time
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from ocring.ocr.event_bus import EventBus, UIEvent
from ocring.ocr.settings import DEFAULT_SETTINGS_PATH, load_settings_payload, save_settings_payload
from ocring.ui.theme import ACCENT, APP_BG, DANGER, SUCCESS, apply_modern_theme, apply_window_icon


@dataclass(frozen=True)
class OverlaySnapshot:
    capture_fps: float
    useful_fps: float
    extraction_rate: float
    verified_rate: float
    queue_depth: int
    continuity_status: str
    status_text: str = "READY"
    retained_fps: float = 0.0
    buffer_gb: float = 0.0
    buffer_limit_gb: float = 3.0
    screen_state: str = "ready"
    frame_count: int = 0


OverlayCorner = Literal["top_left", "top_right", "bottom_left", "bottom_right"]


def map_live_status(*, capture_status: str, screen_class: str, recognition_hold: bool) -> str:
    """Map real capture and analysis state without treating HOLD as a capture stop."""
    if capture_status != "LIVE":
        return capture_status
    if screen_class != "inventory":
        return "NOT INVENTORY"
    return "HOLD" if recognition_hold else "INV"


class OverlayStatusController:
    def __init__(self, event_bus: EventBus) -> None:
        self.status_text = "READY"
        self._unsubscribe_capture_lost = event_bus.subscribe(UIEvent.CAPTURE_LOST, self._on_capture_lost)
        self._unsubscribe_capture_recovered = event_bus.subscribe(UIEvent.CAPTURE_RECOVERED, self._on_capture_recovered)
        self._unsubscribe_scan_started = event_bus.subscribe(UIEvent.SCAN_STARTED, self._on_scan_started)
        self._unsubscribe_scan_stopped = event_bus.subscribe(UIEvent.SCAN_STOPPED, self._on_scan_stopped)

    def close(self) -> None:
        self._unsubscribe_capture_lost()
        self._unsubscribe_capture_recovered()
        self._unsubscribe_scan_started()
        self._unsubscribe_scan_stopped()

    def _on_capture_lost(self, _message: object) -> None:
        self.status_text = "PAUSED"

    def _on_capture_recovered(self, _message: object) -> None:
        self.status_text = "LIVE"

    def _on_scan_started(self, _message: object) -> None:
        self.status_text = "LIVE"

    def _on_scan_stopped(self, _message: object) -> None:
        self.status_text = "READY"


class OverlayWindow:
    """Compact external status surface using Windows no-activate/click-through styles."""

    MIN_WIDTH = 320
    MIN_HEIGHT = 52
    MAX_STATUS_TEXT = "OCRing ● LIVE | NOT INVENTORY | F:9999"
    PLACEMENT_SETTINGS_KEY = "overlay_position"
    TARGET_MARGIN = 18

    def __init__(
        self,
        master: tk.Misc,
        event_bus: EventBus,
        *,
        corner: OverlayCorner = "top_right",
        settings_path: Path | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.corner = corner
        self._settings_path = settings_path or DEFAULT_SETTINGS_PATH
        self._target_window_handle: int | None = None
        self._user_position: tuple[int, int] | None = None
        self._drag_offset: tuple[int, int] | None = None
        self._on_start_capture = None
        self._on_stop_capture = None
        self._on_extract_recording = None
        self._control_mode = "ready"
        self._recording_control_mode = False
        self._click_through_enabled: bool | None = None
        self._click_poll_scheduled = False
        self._topmost_poll_scheduled = False
        self.snapshot = OverlaySnapshot(0, 0, 0, 0, 0, "OK")
        self.status_controller = OverlayStatusController(event_bus)
        self._capture_timestamps: list[float] = []
        self.window = tk.Toplevel(master)
        self.window.withdraw()
        self.window.title("OCRing Status")
        # A native caption consumes most of a 44px window at high DPI.
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.wm_attributes("-alpha", 1.0)
        self.window.configure(bg=APP_BG)
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self.hide)
        self.window.bind("<Map>", self._on_map)
        apply_modern_theme(self.window)
        apply_window_icon(self.window)

        self.container = tk.Frame(self.window, bg=APP_BG, bd=1, highlightthickness=1, highlightbackground=ACCENT)
        self.container.pack(fill="both", expand=True, padx=1, pady=1)
        self._status_font = tkfont.Font(family="Segoe UI Semibold", size=11, weight="bold")
        self._overlay_width, self._overlay_height = self._fit_dimensions()
        self._user_position = self._load_saved_position()
        self.window.geometry(f"{self._overlay_width}x{self._overlay_height}+20+20")
        self.status_var = tk.StringVar(value="OCRing ✓ READY")
        self.status_label = tk.Label(
            self.container,
            textvariable=self.status_var,
            bg=APP_BG,
            fg=ACCENT,
            font=self._status_font,
            anchor="w",
        )
        self.status_label.pack(side="left", fill="both", expand=True, padx=(10, 4), pady=5)
        # The label is intentionally the only drag surface. The button remains a control.
        self.status_label.bind("<ButtonPress-1>", self._start_drag)
        self.status_label.bind("<B1-Motion>", self._drag_to)
        self.status_label.bind("<ButtonRelease-1>", self._finish_drag)
        self.control_button = tk.Button(
            self.container,
            text="Start Capture",
            command=self._request_capture_action,
            bg="#22b8cf",
            fg=APP_BG,
            activebackground=ACCENT,
            activeforeground=APP_BG,
            font=("Segoe UI Semibold", 9),
            relief="flat",
            padx=8,
            pady=2,
            takefocus=False,
        )
        self.control_button.pack(side="right", padx=(2, 6), pady=7)
        self.control_button.bind("<Enter>", self._enter_control_area)
        self.control_button.bind("<Leave>", self._leave_control_area)
        self.status_label.bind("<Enter>", self._enter_control_area)
        self.status_label.bind("<Leave>", self._leave_control_area)

        self._unsubscribe_buffer = event_bus.subscribe(UIEvent.BUFFER_PRESSURE_CHANGED, self._on_buffer_pressure_changed)
        self._unsubscribe_frame_captured = event_bus.subscribe(UIEvent.FRAME_CAPTURED, self._on_frame_captured)
        self._unsubscribe_frame_analyzed = event_bus.subscribe(UIEvent.FRAME_ANALYZED, self._on_frame_analyzed)
        self._unsubscribe_continuity = event_bus.subscribe(UIEvent.CONTINUITY_CHANGED, self._on_continuity_changed)
        self._unsubscribe_capture_lost = event_bus.subscribe(UIEvent.CAPTURE_LOST, self._on_status_event)
        self._unsubscribe_capture_recovered = event_bus.subscribe(UIEvent.CAPTURE_RECOVERED, self._on_status_event)
        self._unsubscribe_scan_started = event_bus.subscribe(UIEvent.SCAN_STARTED, self._on_scan_started)
        self._unsubscribe_scan_stopped = event_bus.subscribe(UIEvent.SCAN_STOPPED, self._on_scan_stopped)
        self._unsubscribe_extraction_progress = event_bus.subscribe(UIEvent.RECORDED_EXTRACTION_PROGRESS, self._on_recorded_extraction_progress)
        self._unsubscribe_extraction_stalled = event_bus.subscribe(UIEvent.RECORDED_EXTRACTION_STALLED, self._on_recorded_extraction_stalled)

    def show(self) -> None:
        # Apply before mapping so Windows does not activate the surface on show.
        self._apply_windows_overlay_styles()
        self.window.deiconify()
        self.window.update_idletasks()
        # Tk applies its final extended style while mapping; reapply after that
        # transition or a foreground game can cover the overlay.
        self._finalize_mapped_window()
        self.window.after(50, self._finalize_mapped_window)
        self.window.after(250, self._finalize_mapped_window)
        self._schedule_foreground_topmost_check()
        self.refresh()

    def prepare_capture(self, *, target_window_handle: int | None) -> None:
        self._target_window_handle = target_window_handle
        self._recording_control_mode = False
        self._control_mode = "ready"
        self.control_button.configure(text="Start Capture", state="normal")
        self.show()

    def prepare_recording(self, *, target_window_handle: int | None) -> None:
        self._target_window_handle = target_window_handle
        self._recording_control_mode = True
        self._control_mode = "ready"
        self._replace_and_refresh(frame_count=0, capture_fps=0.0, retained_fps=0.0)
        self.control_button.configure(text="Record", state="normal")
        self.show()
        self._set_click_through(False)

    def set_settings_path(self, settings_path: Path) -> None:
        """Bind placement persistence to the same settings file as the main window."""
        self._settings_path = settings_path
        self._user_position = self._load_saved_position()

    def set_control_handlers(self, *, on_start_capture, on_stop_capture) -> None:
        self._on_start_capture = on_start_capture
        self._on_stop_capture = on_stop_capture

    def set_recording_handlers(self, *, on_start_recording, on_stop_recording, on_extract_recording) -> None:
        self._recording_control_mode = True
        self._on_start_capture = on_start_recording
        self._on_stop_capture = on_stop_recording
        self._on_extract_recording = on_extract_recording

    def mark_recording_active(self) -> None:
        self._control_mode = "recording"
        self.control_button.configure(text="Stop", state="normal")
        self.refresh()

    def mark_recording_finalizing(self) -> None:
        self._control_mode = "finalizing"
        self.control_button.configure(text="Extract", state="disabled")
        self.status_var.set("OCRing | FINALIZING...")
        self.status_label.configure(fg="#fbbf24")
        self._set_click_through(False)

    def mark_recorded_ready(self) -> None:
        self._control_mode = "recorded"
        self.control_button.configure(text="Extract", state="normal")
        frame_count = max(0, int(getattr(self.snapshot, "frame_count", 0)))
        suffix = f" | F:{frame_count}" if frame_count else ""
        self.status_var.set(f"OCRing | RECORDED ✓{suffix}")
        self.status_label.configure(fg=ACCENT)
        self._set_click_through(False)

    def mark_recording_processing(self) -> None:
        self._control_mode = "processing"
        self.control_button.configure(text="Extract", state="disabled")
        self.refresh()

    def mark_recording_failed(self, reason: str) -> None:
        self._control_mode = "failed"
        self.control_button.configure(text="Record", state="normal")
        self.status_var.set(f"OCRing | ERROR: {reason[:22]}")
        self.status_label.configure(fg=DANGER)
        self._set_click_through(False)

    def mark_recording_waiting(self, reason: str = "target") -> None:
        self._control_mode = "ready"
        self.control_button.configure(text="Record", state="normal")
        self.status_var.set(f"OCRing | WAITING FOR {reason[:16].upper()}")
        self.status_label.configure(fg="#fbbf24")
        self._set_click_through(False)

    def hide(self) -> None:
        self.window.withdraw()

    def close(self) -> None:
        self.status_controller.close()
        self._unsubscribe_buffer()
        self._unsubscribe_frame_captured()
        self._unsubscribe_frame_analyzed()
        self._unsubscribe_continuity()
        self._unsubscribe_capture_lost()
        self._unsubscribe_capture_recovered()
        self._unsubscribe_scan_started()
        self._unsubscribe_scan_stopped()
        self._unsubscribe_extraction_progress()
        self._unsubscribe_extraction_stalled()
        self.window.destroy()

    def apply_snapshot(self, snapshot: OverlaySnapshot) -> None:
        self.snapshot = snapshot
        self.refresh()

    def refresh(self) -> None:
        updated = replace(self.snapshot, status_text=self.status_controller.status_text)
        self.snapshot = updated
        state = map_live_status(
            capture_status=updated.status_text,
            screen_class=updated.screen_state,
            recognition_hold=updated.continuity_status == "HOLD",
        )
        marker = "●" if updated.status_text == "LIVE" else "✓"
        frame_suffix = f" | F:{updated.frame_count}" if updated.frame_count else ""
        if self._control_mode == "ready":
            self.status_var.set("OCRing | READY")
        elif self._control_mode == "finalizing":
            self.status_var.set("OCRing | FINALIZING...")
        elif self._control_mode == "processing":
            self.status_var.set("OCRing | PROCESSING")
        elif self._control_mode == "recorded":
            self.status_var.set(f"OCRing | RECORDED ✓{frame_suffix}")
        elif self._control_mode == "failed":
            pass
        else:
            state_label = "NO INV" if state == "NOT INVENTORY" else state
            if self._recording_control_mode:
                self.status_var.set(f"OCRing ● REC{frame_suffix}")
            else:
                self.status_var.set(f"OCRing {marker} REC | {state_label}{frame_suffix}")
        self.status_label.configure(fg=self._status_color(updated.status_text, state))
        self._schedule_control_hit_test()

    def _on_buffer_pressure_changed(self, message: object) -> None:
        payload = getattr(message, "payload", {})
        self._run_on_ui_thread(
            lambda: self._replace_and_refresh(
                queue_depth=int(payload.get("queue_depth", self.snapshot.queue_depth)),
                buffer_gb=float(payload.get("buffer_gb", self.snapshot.buffer_gb)),
            )
        )

    def _on_frame_captured(self, message: object) -> None:
        payload = getattr(message, "payload", {})

        def apply() -> None:
            now = float(payload.get("capture_timestamp", time.time()))
            self._capture_timestamps.append(now)
            self._capture_timestamps = [timestamp for timestamp in self._capture_timestamps if now - timestamp <= 1.0]
            handle = payload.get("window_handle")
            if handle not in {None, ""}:
                self._target_window_handle = int(handle)
                self._position_for_target()
            self._replace_and_refresh(
                capture_fps=float(len(self._capture_timestamps)),
                retained_fps=float(len(self._capture_timestamps)),
                queue_depth=int(payload.get("queue_depth", self.snapshot.queue_depth)),
                buffer_gb=round(float(payload.get("buffer_bytes", 0)) / (1024 * 1024 * 1024), 3),
                buffer_limit_gb=float(payload.get("buffer_limit_gb", self.snapshot.buffer_limit_gb)),
                frame_count=self.snapshot.frame_count + 1,
            )

        self._run_on_ui_thread(apply)

    def _on_frame_analyzed(self, message: object) -> None:
        payload = getattr(message, "payload", {})
        self._run_on_ui_thread(
            lambda: self._replace_and_refresh(
                screen_state=str(payload.get("screen_class") or "unknown").lower(),
                continuity_status="HOLD" if bool(payload.get("recognition_hold")) else "OK",
            )
        )

    def _on_continuity_changed(self, message: object) -> None:
        payload = getattr(message, "payload", {})
        self._run_on_ui_thread(
            lambda: self._replace_and_refresh(
                continuity_status=str(payload.get("continuity_status", self.snapshot.continuity_status))
            )
        )

    def _on_status_event(self, _message: object) -> None:
        self._run_on_ui_thread(self.refresh)

    def _on_scan_started(self, _message: object) -> None:
        def apply() -> None:
            if self._recording_control_mode:
                return
            self._control_mode = "recording"
            self.control_button.configure(text="Stop", state="normal")
            self.refresh()

        self._run_on_ui_thread(apply)

    def _on_scan_stopped(self, _message: object) -> None:
        def apply() -> None:
            if self._recording_control_mode:
                return
            self._capture_timestamps.clear()
            self._control_mode = "processing"
            self.control_button.configure(state="disabled")
            self._replace_and_refresh(
                capture_fps=0.0,
                retained_fps=0.0,
                queue_depth=0,
                buffer_gb=0.0,
                screen_state="ready",
                continuity_status="OK",
                frame_count=0,
            )
            self.hide()

        self._run_on_ui_thread(apply)

    def _on_recorded_extraction_progress(self, message: object) -> None:
        payload = getattr(message, "payload", {})

        def apply() -> None:
            if self._control_mode != "processing":
                return
            stage = str(payload.get("stage") or "PROCESSING").upper()
            current_index = int(payload.get("current_index", payload.get("processed_frames", 0)) or 0)
            total_count = int(payload.get("total_count", payload.get("total_frames", 0)) or 0)
            if total_count > 0 and current_index > 0:
                self.status_var.set(f"OCRing | {stage[:14]} {current_index}/{total_count}")
            else:
                self.status_var.set(f"OCRing | {stage[:20]}")
            self.status_label.configure(fg="#fbbf24")

        self._run_on_ui_thread(apply)

    def _on_recorded_extraction_stalled(self, message: object) -> None:
        payload = getattr(message, "payload", {})

        def apply() -> None:
            if self._control_mode != "processing":
                return
            stage = str(payload.get("stage") or "unknown").upper()
            self.status_var.set(f"OCRing | STALLED: {stage[:12]}")
            self.status_label.configure(fg=DANGER)

        self._run_on_ui_thread(apply)

    def _replace_and_refresh(self, **changes: object) -> None:
        self.snapshot = replace(self.snapshot, **changes)
        self.refresh()

    @staticmethod
    def _status_color(capture_status: str, display_state: str) -> str:
        if capture_status == "LIVE" and display_state == "HOLD":
            return "#fbbf24"
        if capture_status == "LIVE" and display_state == "NOT INVENTORY":
            return DANGER
        if capture_status == "LIVE":
            return SUCCESS
        if capture_status == "PAUSED":
            return DANGER
        return ACCENT

    def _run_on_ui_thread(self, callback) -> None:
        try:
            self.window.after(0, callback)
        except tk.TclError:
            return

    def _on_map(self, _event: tk.Event | None = None) -> None:
        self.window.after_idle(self._finalize_mapped_window)

    def _finalize_mapped_window(self) -> None:
        if not self.window.winfo_exists():
            return
        self._apply_windows_overlay_styles()
        self._position_for_target()

    def _request_capture_action(self) -> None:
        event_name = "extract" if self._control_mode == "recorded" else "record" if self._control_mode in {"ready", "failed"} else "stop"
        self.event_bus.publish(
            UIEvent.OVERLAY_RECORD_CLICK_RECEIVED,
            {
                "control_mode": self._control_mode,
                "recording_control_mode": self._recording_control_mode,
                "action": event_name,
                "click_through_enabled": self._click_through_enabled,
            },
        )
        if event_name == "extract":
            self.event_bus.publish(
                UIEvent.OVERLAY_EXTRACT_CLICK_RECEIVED,
                {
                    "control_mode": self._control_mode,
                    "recording_control_mode": self._recording_control_mode,
                    "click_through_enabled": self._click_through_enabled,
                },
            )
        if self._control_mode == "recorded":
            callback = self._on_extract_recording
        elif self._control_mode in {"ready", "failed"}:
            callback = self._on_start_capture
        else:
            callback = self._on_stop_capture
        if callback is not None:
            self.event_bus.publish(
                UIEvent.OVERLAY_RECORD_CALLBACK_ENTERED,
                {"control_mode": self._control_mode, "action": event_name},
            )
            callback()

    def _schedule_control_hit_test(self) -> None:
        if self._recording_control_mode:
            self._set_click_through(False)
            return
        if self._click_poll_scheduled or not self.window.winfo_viewable():
            return
        self._click_poll_scheduled = True
        self.window.after(75, self._update_click_through_mode)

    def _schedule_foreground_topmost_check(self) -> None:
        if self._topmost_poll_scheduled or not self.window.winfo_viewable():
            return
        self._topmost_poll_scheduled = True
        self.window.after(250, self._maintain_foreground_topmost)

    def _maintain_foreground_topmost(self) -> None:
        self._topmost_poll_scheduled = False
        if os.name != "nt" or not self.window.winfo_viewable():
            return
        try:
            foreground = self._foreground_window_handle()
            if self._target_window_handle and foreground == self._target_window_handle:
                # Defiance is a borderless full-monitor window. Reassert the external
                # wrapper without activation when the game moves itself above normal HWNDs.
                self._raise_native_topmost()
        except (AttributeError, OSError, tk.TclError):
            return
        self._schedule_foreground_topmost_check()

    @staticmethod
    def _foreground_window_handle() -> int:
        if os.name != "nt":
            return 0
        return int(ctypes.windll.user32.GetForegroundWindow() or 0)

    def _update_click_through_mode(self) -> None:
        self._click_poll_scheduled = False
        if os.name != "nt" or not self.window.winfo_viewable():
            return
        try:
            import ctypes.wintypes

            point = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
            left = self.control_button.winfo_rootx()
            top = self.control_button.winfo_rooty()
            inside_control = left <= point.x < left + self.control_button.winfo_width() and top <= point.y < top + self.control_button.winfo_height()
            drag_left = self.status_label.winfo_rootx()
            drag_top = self.status_label.winfo_rooty()
            inside_drag_region = (
                drag_left <= point.x < drag_left + self.status_label.winfo_width()
                and drag_top <= point.y < drag_top + self.status_label.winfo_height()
            )
            self._set_click_through(not (inside_control or inside_drag_region))
        except (AttributeError, OSError, tk.TclError):
            return
        self._schedule_control_hit_test()

    def _enter_control_area(self, _event: tk.Event | None = None) -> None:
        self._set_click_through(False)

    def _leave_control_area(self, _event: tk.Event | None = None) -> None:
        if self._recording_control_mode:
            self._set_click_through(False)

    def _apply_windows_overlay_styles(self) -> None:
        """Native styles keep the surface topmost without activation or input capture."""
        if os.name != "nt":
            return
        try:
            user32 = ctypes.windll.user32
            user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
            user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
            user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
            user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            user32.SetWindowPos.restype = ctypes.c_bool
            user32.SetLayeredWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_byte, ctypes.c_uint]
            user32.SetLayeredWindowAttributes.restype = ctypes.c_bool
            hwnd = self._native_overlay_hwnd()
            self.window.attributes("-topmost", True)
            extended_style = int(user32.GetWindowLongPtrW(ctypes.c_void_p(hwnd), -20))
            # TOOLWINDOW: omit Alt+Tab. NOACTIVATE: never focus. TRANSPARENT is toggled for the control hit area.
            user32.SetWindowLongPtrW(ctypes.c_void_p(hwnd), -20, extended_style | 0x00000080 | 0x00080000 | 0x08000000)
            self._click_through_enabled = None
            self._set_click_through(False if self._recording_control_mode else True)
            # Tk can leave the wrapper layered with an effective alpha of zero.
            # Set opacity on the wrapper itself, not its internal child HWND.
            user32.SetLayeredWindowAttributes(ctypes.c_void_p(hwnd), 0, 255, 0x00000002)
            self._raise_native_topmost()
        except (AttributeError, OSError, tk.TclError):
            return

    def _raise_native_topmost(self) -> bool:
        if os.name != "nt":
            return False
        try:
            user32 = ctypes.windll.user32
            user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            user32.SetWindowPos.restype = ctypes.c_bool
            return bool(
                user32.SetWindowPos(
                    ctypes.c_void_p(self._native_overlay_hwnd()),
                    ctypes.c_void_p(-1),  # HWND_TOPMOST
                    0,
                    0,
                    0,
                    0,
                    0x0001 | 0x0002 | 0x0010 | 0x0020 | 0x0040,  # no move/size/activate, frame change, show
                )
            )
        except (AttributeError, OSError, tk.TclError):
            return False

    def _set_click_through(self, enabled: bool) -> None:
        if os.name != "nt" or self._click_through_enabled == enabled:
            return
        try:
            user32 = ctypes.windll.user32
            hwnd = self._native_overlay_hwnd()
            extended_style = int(user32.GetWindowLongPtrW(ctypes.c_void_p(hwnd), -20))
            style = extended_style | 0x00000020 if enabled else extended_style & ~0x00000020
            user32.SetWindowLongPtrW(ctypes.c_void_p(hwnd), -20, style)
            self._click_through_enabled = enabled
        except (AttributeError, OSError, tk.TclError):
            return

    def _native_overlay_hwnd(self) -> int:
        """Resolve Tk's internal HWND to the top-level wrapper Windows actually stacks."""
        hwnd = int(self.window.winfo_id())
        if os.name != "nt":
            return hwnd
        user32 = ctypes.windll.user32
        user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.GetAncestor.restype = ctypes.c_void_p
        root = user32.GetAncestor(ctypes.c_void_p(hwnd), 2)  # GA_ROOT
        return int(root or hwnd)

    def _position_for_target(self) -> None:
        if self._user_position is not None:
            self._set_overlay_geometry(*self._user_position)
            return
        if os.name != "nt" or not self._target_window_handle:
            return
        try:
            from ctypes import wintypes

            rect = wintypes.RECT()
            if not ctypes.windll.user32.GetWindowRect(int(self._target_window_handle), ctypes.byref(rect)):
                return
            x = rect.left + self.TARGET_MARGIN if self.corner.endswith("left") else rect.right - self._overlay_width - self.TARGET_MARGIN
            y = rect.top + self.TARGET_MARGIN if self.corner.startswith("top") else rect.bottom - self._overlay_height - self.TARGET_MARGIN
            self._set_overlay_geometry(x, y)
        except (AttributeError, OSError, tk.TclError):
            return

    def _start_drag(self, event: tk.Event) -> str:
        self._drag_offset = (int(event.x_root) - self.window.winfo_rootx(), int(event.y_root) - self.window.winfo_rooty())
        return "break"

    def _drag_to(self, event: tk.Event) -> str:
        if self._drag_offset is None:
            return "break"
        x = int(event.x_root) - self._drag_offset[0]
        y = int(event.y_root) - self._drag_offset[1]
        self._user_position = self._set_overlay_geometry(x, y)
        return "break"

    def _finish_drag(self, _event: tk.Event) -> str:
        self._drag_offset = None
        if self._user_position is not None:
            self._save_position(*self._user_position)
        # Reassert no-activate/topmost after Windows has handled the drag gesture.
        self._apply_windows_overlay_styles()
        return "break"

    def _set_overlay_geometry(self, x: int, y: int) -> tuple[int, int]:
        x, y = self._clamp_position(x, y)
        self.window.geometry(f"{self._overlay_width}x{self._overlay_height}+{x}+{y}")
        return x, y

    def _clamp_position(self, x: int, y: int) -> tuple[int, int]:
        if os.name != "nt":
            return max(0, x), max(0, y)
        try:
            user32 = ctypes.windll.user32
            left = int(user32.GetSystemMetrics(76))  # SM_XVIRTUALSCREEN
            top = int(user32.GetSystemMetrics(77))  # SM_YVIRTUALSCREEN
            width = int(user32.GetSystemMetrics(78))  # SM_CXVIRTUALSCREEN
            height = int(user32.GetSystemMetrics(79))  # SM_CYVIRTUALSCREEN
            right = left + max(width - self._overlay_width, 0)
            bottom = top + max(height - self._overlay_height, 0)
            return min(max(x, left), right), min(max(y, top), bottom)
        except (AttributeError, OSError):
            return max(0, x), max(0, y)

    def _load_saved_position(self) -> tuple[int, int] | None:
        position = load_settings_payload(path=self._settings_path).get(self.PLACEMENT_SETTINGS_KEY)
        if not isinstance(position, dict):
            return None
        try:
            return self._clamp_position(int(position["x"]), int(position["y"]))
        except (KeyError, TypeError, ValueError):
            return None

    def _save_position(self, x: int, y: int) -> None:
        payload = load_settings_payload(path=self._settings_path)
        payload[self.PLACEMENT_SETTINGS_KEY] = {"x": x, "y": y}
        save_settings_payload(payload, path=self._settings_path)

    def _fit_dimensions(self) -> tuple[int, int]:
        """Reserve room for the longest supported status at the active Tk DPI."""
        text_width = self._status_font.measure(self.MAX_STATUS_TEXT)
        line_height = self._status_font.metrics("linespace")
        return max(self.MIN_WIDTH, text_width + 24), max(self.MIN_HEIGHT, line_height + 18)


def render_corner_overlay(snapshot: OverlaySnapshot) -> str:
    return "\n".join(
        (
            f"Capture:    {int(round(snapshot.capture_fps))} FPS",
            f"Retained:   {int(round(snapshot.retained_fps))} FPS",
            f"Useful:     {int(round(snapshot.useful_fps))} FPS",
            f"Extract:    {int(round(snapshot.extraction_rate))}/s",
            f"Verified:   {int(round(snapshot.verified_rate))}/s",
            f"Buffer:     {snapshot.buffer_gb:.1f} / {snapshot.buffer_limit_gb:.0f} GB",
            f"Queue:      {int(snapshot.queue_depth)}",
            f"Continuity: {snapshot.continuity_status}",
            f"Status:     {snapshot.status_text}",
        )
    )
