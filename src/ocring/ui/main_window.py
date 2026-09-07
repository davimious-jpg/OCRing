from __future__ import annotations

import ctypes
import tkinter as tk
import re
from pathlib import Path
from tkinter import ttk
from typing import Callable
from uuid import uuid4

from ocring.ocr.event_bus import EventBus, UIEvent
from ocring.ocr.capture_backend import CaptureTargetIdentity
from ocring.ocr.pipeline import CaptureLoop
from ocring.ocr.profile import DEFAULT_PROFILES_ROOT, list_profiles
from ocring.ocr.review import ReviewSession, load_review_session_from_store
from ocring.ocr.settings import DEFAULT_SETTINGS_PATH, ensure_output_workspace, load_settings, load_settings_payload, save_settings_payload
from ocring.ui.backup_ui import BackupUI
from ocring.ui.hotkey import HotkeyManager
from ocring.ui.overlay import OverlaySnapshot, OverlayWindow
from ocring.ui.profile_manager import ProfileManager
from ocring.ui.recovery_center import RecoveryCenter
from ocring.ui.review_window import ReviewWindow
from ocring.ui.scan_setup import ScanSetup
from ocring.ui.search_panel import SearchPanel
from ocring.ui.settings_window import SettingsWindow
from ocring.ui.theme import (
    ACCENT,
    APP_BG,
    SURFACE_BG,
    TEXT,
    TEXT_MUTED,
    TITLE_FONT,
    apply_modern_theme,
    apply_window_icon,
    hide_ttk_monitor_windows,
    load_logo_image,
)


class _PlaceholderFrame(ttk.Frame):
    def __init__(self, master: tk.Misc, *, title: str, message: str, action: Callable[[], None] | None = None, action_label: str = "Open") -> None:
        super().__init__(master, padding=18, style="Surface.TFrame")
        self.columnconfigure(0, weight=1)
        header = ttk.Label(self, text=title, style="Section.TLabel")
        header.grid(row=0, column=0, sticky="w")
        body = ttk.Label(self, text=message, wraplength=620, justify="left", style="Muted.TLabel")
        body.grid(row=1, column=0, sticky="w", pady=(8, 14))
        if action is not None:
            ttk.Button(self, text=action_label, command=action, style="Accent.TButton").grid(row=2, column=0, sticky="w")


class MainWindow(tk.Tk):
    NAV_ITEMS = ("Scan", "Inventory", "Review", "Profiles", "Settings", "Recovery", "Backup")

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        settings_path: Path | None = None,
        sessions_root: Path | None = None,
        profiles_root: Path = DEFAULT_PROFILES_ROOT,
        overlay_factory: Callable[[tk.Misc, EventBus], OverlayWindow] = OverlayWindow,
        hotkey_manager_factory: Callable[..., HotkeyManager] = HotkeyManager,
        capture_loop_factory: Callable[..., CaptureLoop] = CaptureLoop,
        screen_factories: dict[str, Callable[[tk.Misc], tk.Widget]] | None = None,
    ) -> None:
        super().__init__()
        self.settings_path = settings_path or DEFAULT_SETTINGS_PATH
        self.runtime_settings = load_settings(path=self.settings_path)
        self.output_workspace = ensure_output_workspace(path=self.settings_path)
        self.title("OCRing")
        self.geometry(self.runtime_settings.window_geometry or "1024x768")
        self.resizable(True, True)
        self.minsize(640, 480)
        apply_modern_theme(self)
        apply_window_icon(self)
        self._logo_image = load_logo_image(self, base_size=(52, 52))
        self.event_bus = event_bus or EventBus()
        self.sessions_root = sessions_root or self.output_workspace.sessions_dir
        self.profiles_root = profiles_root
        self.overlay_window = overlay_factory(self, self.event_bus)
        self.overlay_window.hide()
        if hasattr(self.overlay_window, "set_settings_path"):
            self.overlay_window.set_settings_path(self.settings_path)
        if hasattr(self.overlay_window, "set_control_handlers"):
            self.overlay_window.set_control_handlers(
                on_start_capture=self._begin_capture,
                on_stop_capture=self._stop_live_scan,
            )
        self._closing = False
        self.scan_state = "READY"
        self.active_scan_session_id: str | None = None
        self.active_scan_payload: dict[str, object] = {}
        self.latest_test_capture_payload: dict[str, object] = {}
        self.capture_loop_factory = capture_loop_factory
        self.capture_loop: CaptureLoop | None = None
        self.screen_factories = screen_factories or {}
        self.hotkey_manager = hotkey_manager_factory(event_bus=self.event_bus, root=self, settings_path=self.settings_path)
        self.hotkey_backend_name = self.hotkey_manager.register()

        self.configure(bg=APP_BG)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        self.header_frame = ttk.Frame(self, padding=(18, 16, 18, 12))
        self.header_frame.grid(row=0, column=0, sticky="ew")
        self.header_frame.columnconfigure(1, weight=1)

        if self._logo_image is not None:
            self.logo_label = ttk.Label(self.header_frame, image=self._logo_image, style="TLabel")
            self.logo_label.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 14))
        else:
            self.logo_label = ttk.Label(self.header_frame, text="OCR", style="Section.TLabel")
            self.logo_label.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 14))

        self.title_label = ttk.Label(self.header_frame, text="OCRing", style="Header.TLabel")
        self.title_label.grid(row=0, column=1, sticky="w")
        self.subtitle_label = ttk.Label(
            self.header_frame,
            text="External inventory OCR companion with review-first verification.",
            style="Muted.TLabel",
        )
        self.subtitle_label.grid(row=1, column=1, sticky="w", pady=(4, 0))

        self.status_var = tk.StringVar(value=f"Hotkey {self.hotkey_manager.backend_status_label}")
        self.status_chip = tk.Label(
            self.header_frame,
            textvariable=self.status_var,
            bg=SURFACE_BG,
            fg=ACCENT,
            padx=12,
            pady=8,
            font=TITLE_FONT,
        )
        self.status_chip.grid(row=0, column=2, rowspan=2, sticky="e")

        self.nav_frame = ttk.Frame(self, padding=(18, 0, 18, 12))
        self.nav_frame.grid(row=1, column=0, sticky="ew")
        self.content = ttk.Frame(self, padding=(18, 0, 18, 18))
        self.content.grid(row=2, column=0, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)
        self.content_host = ttk.Frame(self.content, style="Surface.TFrame")
        self.content_host.pack(expand=True, fill=tk.BOTH)
        self.content_host.columnconfigure(0, weight=1)
        self.content_host.rowconfigure(0, weight=1)
        self.content_canvas = tk.Canvas(
            self.content_host,
            bg=APP_BG,
            highlightthickness=0,
            borderwidth=0,
            xscrollincrement=16,
            yscrollincrement=16,
        )
        self.content_canvas.grid(row=0, column=0, sticky="nsew")
        self.content_vscroll = ttk.Scrollbar(self.content_host, orient="vertical", command=self.content_canvas.yview)
        self.content_hscroll = ttk.Scrollbar(self.content_host, orient="horizontal", command=self.content_canvas.xview)
        self.content_canvas.configure(
            yscrollcommand=self._on_vertical_scroll,
            xscrollcommand=self._on_horizontal_scroll,
        )
        self.content_inner = ttk.Frame(self.content_canvas, style="Surface.TFrame")
        self.content_inner.columnconfigure(0, weight=1)
        self.content_inner.rowconfigure(0, weight=1)
        self._content_window = self.content_canvas.create_window((0, 0), window=self.content_inner, anchor="nw")
        self._scrollbar_state = {"vertical": False, "horizontal": False}
        self.content_inner.bind("<Configure>", self._on_content_inner_configure)
        self.content_canvas.bind("<Configure>", self._on_content_canvas_configure)
        self.content_canvas.bind("<Enter>", self._bind_content_mousewheel)
        self.content_canvas.bind("<Leave>", self._unbind_content_mousewheel)
        self.content_inner.bind("<Enter>", self._bind_content_mousewheel)
        self.content_inner.bind("<Leave>", self._unbind_content_mousewheel)

        self.current_screen = ""
        self.screens: dict[str, tk.Widget] = {}
        self.nav_buttons: dict[str, ttk.Button] = {}
        for index, name in enumerate(self.NAV_ITEMS):
            button = ttk.Button(
                self.nav_frame,
                text=name,
                command=lambda target=name: self.show_screen(target),
                style="Accent.TButton" if name == "Scan" else "TButton",
            )
            button.grid(row=0, column=index, padx=4, pady=4, sticky="w")
            self.nav_buttons[name] = button

        self._subscribe_events()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.show_screen("Scan")
        self.after(0, hide_ttk_monitor_windows)
        self.after(250, hide_ttk_monitor_windows)

    def run(self) -> None:
        self.mainloop()

    def show_screen(self, name: str) -> None:
        if name not in self.screens:
            self.screens[name] = self._build_screen(name)
        for screen_name, widget in self.screens.items():
            if hasattr(widget, "grid_remove"):
                widget.grid_remove()
            if screen_name in self.nav_buttons and hasattr(self.nav_buttons[screen_name], "configure"):
                self.nav_buttons[screen_name].configure(style="Accent.TButton" if screen_name == name else "TButton")
        screen = self.screens[name]
        screen.grid(row=0, column=0, sticky="nsew")
        self.current_screen = name
        if hasattr(self, "content_canvas"):
            self.content_canvas.xview_moveto(0)
            self.content_canvas.yview_moveto(0)
            self.after(0, self._refresh_content_scroll_state)

    def _build_screen(self, name: str) -> tk.Widget:
        if name in self.screen_factories:
            return self.screen_factories[name](self.content_inner)
        if name == "Scan":
            return ScanSetup(self.content_inner, event_bus=self.event_bus, profiles_root=self.profiles_root)
        if name == "Inventory":
            return SearchPanel(self.content_inner, settings_path=self.settings_path)
        if name == "Review":
            return _PlaceholderFrame(
                self.content_inner,
                title="Review Queue",
                message="Recent scan candidates will appear here once a scan is completed and handed off to review.",
            )
        if name == "Profiles":
            widget = ProfileManager(self.content_inner)
            widget.set_profiles(list_profiles(profiles_root=self.profiles_root))
            return widget
        if name == "Settings":
            return _PlaceholderFrame(
                self.content_inner,
                title="Settings",
                message="Open the OCRing settings window to edit recognition, privacy, search, and hotkey preferences.",
                action=self._open_settings_window,
                action_label="Open Settings Window",
            )
        if name == "Recovery":
            widget = RecoveryCenter(self.content_inner, sessions_root=self.sessions_root)
            widget.set_sessions(self._recovery_sessions())
            return widget
        if name == "Backup":
            return BackupUI(self.content_inner)
        return _PlaceholderFrame(self.content_inner, title=name, message=f"No content registered for {name}.")

    def _on_content_inner_configure(self, _event: tk.Event | None = None) -> None:
        self._refresh_content_scroll_state()

    def _on_content_canvas_configure(self, _event: tk.Event | None = None) -> None:
        self._refresh_content_scroll_state()

    def _refresh_content_scroll_state(self) -> None:
        self.update_idletasks()
        requested_width = max(1, self.content_inner.winfo_reqwidth())
        requested_height = max(1, self.content_inner.winfo_reqheight())
        canvas_width = max(1, self.content_canvas.winfo_width())
        canvas_height = max(1, self.content_canvas.winfo_height())
        needs_horizontal = requested_width > canvas_width
        needs_vertical = requested_height > canvas_height

        self.content_canvas.itemconfigure(self._content_window, width=requested_width if needs_horizontal else canvas_width)
        self.content_canvas.itemconfigure(self._content_window, height=requested_height if needs_vertical else canvas_height)
        self.content_canvas.configure(scrollregion=(0, 0, requested_width, requested_height))

        self._set_scrollbar_visible(self.content_vscroll, "vertical", needs_vertical, row=0, column=1, sticky="ns")
        self._set_scrollbar_visible(self.content_hscroll, "horizontal", needs_horizontal, row=1, column=0, sticky="ew")

    def _set_scrollbar_visible(
        self,
        scrollbar: ttk.Scrollbar,
        axis: str,
        visible: bool,
        *,
        row: int,
        column: int,
        sticky: str,
    ) -> None:
        if visible and not self._scrollbar_state[axis]:
            scrollbar.grid(row=row, column=column, sticky=sticky)
            self._scrollbar_state[axis] = True
        elif not visible and self._scrollbar_state[axis]:
            scrollbar.grid_remove()
            self._scrollbar_state[axis] = False

    def _on_vertical_scroll(self, first: str, last: str) -> None:
        self.content_vscroll.set(first, last)
        self._set_scrollbar_visible(self.content_vscroll, "vertical", not (float(first) <= 0.0 and float(last) >= 1.0), row=0, column=1, sticky="ns")

    def _on_horizontal_scroll(self, first: str, last: str) -> None:
        self.content_hscroll.set(first, last)
        self._set_scrollbar_visible(self.content_hscroll, "horizontal", not (float(first) <= 0.0 and float(last) >= 1.0), row=1, column=0, sticky="ew")

    def _bind_content_mousewheel(self, _event: tk.Event | None = None) -> None:
        self.content_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.content_canvas.bind_all("<Shift-MouseWheel>", self._on_shift_mousewheel)
        self.content_canvas.bind_all("<Button-4>", self._on_linux_scroll_up)
        self.content_canvas.bind_all("<Button-5>", self._on_linux_scroll_down)

    def _unbind_content_mousewheel(self, _event: tk.Event | None = None) -> None:
        self.content_canvas.unbind_all("<MouseWheel>")
        self.content_canvas.unbind_all("<Shift-MouseWheel>")
        self.content_canvas.unbind_all("<Button-4>")
        self.content_canvas.unbind_all("<Button-5>")

    def _on_mousewheel(self, event: tk.Event) -> str:
        delta = int(-1 * (event.delta / 120)) if getattr(event, "delta", 0) else 0
        if delta:
            self.content_canvas.yview_scroll(delta, "units")
        return "break"

    def _on_shift_mousewheel(self, event: tk.Event) -> str:
        delta = int(-1 * (event.delta / 120)) if getattr(event, "delta", 0) else 0
        if delta:
            self.content_canvas.xview_scroll(delta, "units")
        return "break"

    def _on_linux_scroll_up(self, _event: tk.Event) -> str:
        self.content_canvas.yview_scroll(-1, "units")
        return "break"

    def _on_linux_scroll_down(self, _event: tk.Event) -> str:
        self.content_canvas.yview_scroll(1, "units")
        return "break"

    def _subscribe_events(self) -> None:
        self._unsubscribe_scan_start = self.event_bus.subscribe(UIEvent.SCAN_START_REQUESTED, self._on_scan_requested)
        self._unsubscribe_scan_started = self.event_bus.subscribe(UIEvent.SCAN_STARTED, self._on_scan_started)
        self._unsubscribe_scan_stop = self.event_bus.subscribe(UIEvent.SCAN_STOP_REQUESTED, self._on_scan_stopped)
        self._unsubscribe_scan_stopped = self.event_bus.subscribe(UIEvent.SCAN_STOPPED, self._on_scan_fully_stopped)
        self._unsubscribe_review_session_ready = self.event_bus.subscribe(UIEvent.REVIEW_SESSION_READY, self._on_review_session_ready)
        self._unsubscribe_hotkey = self.event_bus.subscribe(UIEvent.HOTKEY_REBOUND, self._on_hotkey_rebound)
        self._unsubscribe_test_capture = self.event_bus.subscribe(UIEvent.TEST_CAPTURE_COMPLETE, self._on_test_capture_complete)

    def _on_scan_requested(self, message: object) -> None:
        payload = self._normalize_scan_payload(getattr(message, "payload", {}))
        self.active_scan_payload = dict(payload)
        self.active_scan_session_id = str(payload.get("session_id") or f"session-{uuid4().hex[:8]}")
        self._prepare_live_scan(self.active_scan_payload)

    def _on_scan_started(self, _message: object) -> None:
        self.scan_state = "LIVE"
        self.status_var.set(f"CAPTURE ACTIVE  •  Hotkey {self.hotkey_manager.backend_status_label}")
        self.status_chip.configure(fg=APP_BG, bg=ACCENT)
        self.overlay_window.show()
        self.overlay_window.apply_snapshot(
            OverlaySnapshot(
                capture_fps=0,
                retained_fps=0,
                useful_fps=0,
                extraction_rate=0,
                verified_rate=0,
                queue_depth=0,
                continuity_status="OK",
                status_text="LIVE",
                buffer_gb=0.0,
            )
        )

    def _on_scan_stopped(self, _message: object) -> None:
        self._stop_live_scan()

    def _on_scan_fully_stopped(self, _message: object) -> None:
        self.scan_state = "READY"
        self.status_var.set(f"READY  •  Hotkey {self.hotkey_manager.backend_status_label}")
        self.status_chip.configure(fg=ACCENT, bg=SURFACE_BG)
        self.overlay_window.apply_snapshot(
            OverlaySnapshot(
                capture_fps=0,
                retained_fps=0,
                useful_fps=0,
                extraction_rate=0,
                verified_rate=0,
                queue_depth=0,
                continuity_status="IDLE",
                status_text="READY",
                buffer_gb=0.0,
            )
        )
        if self._closing:
            return
        review_session = self._build_completed_review_session()
        self._apply_review_policy(review_session)
        self.event_bus.publish(
            UIEvent.REVIEW_SESSION_READY,
            {
                "session_id": review_session.session_id,
                "record_count": len(review_session.records),
                "review_summary": review_session.get_review_summary(),
            },
        )
        self._show_review_session(review_session)

    def _on_hotkey_rebound(self, message: object) -> None:
        payload = getattr(message, "payload", {})
        self.status_var.set(
            f"{self.scan_state}  •  Hotkey {payload.get('scan_hotkey', self.hotkey_manager.hotkey)} ({self.hotkey_manager.backend_scope_label})"
        )

    def _on_test_capture_complete(self, message: object) -> None:
        payload = getattr(message, "payload", {})
        self.latest_test_capture_payload = dict(payload)
        self.overlay_window.apply_snapshot(
            OverlaySnapshot(
                capture_fps=1,
                retained_fps=1,
                useful_fps=1,
                extraction_rate=0,
                verified_rate=0,
                queue_depth=0,
                continuity_status="READY",
                status_text=getattr(getattr(self.overlay_window, "status_controller", None), "status_text", "READY"),
                buffer_gb=0.1,
            )
        )
        self.status_var.set(f"Preview ready from {payload.get('source', 'unknown')}")

    def _on_review_session_ready(self, message: object) -> None:
        payload = getattr(message, "payload", {})
        if not payload.get("recorded_capture_mode"):
            return
        session_id = str(payload.get("session_id") or "")
        if not session_id:
            return
        try:
            review_session = load_review_session_from_store(session_id, sessions_root=self.sessions_root)
        except FileNotFoundError:
            review_session = ReviewSession(session_id=session_id, records=[])
        self._show_review_session(review_session)
        summary = dict(payload.get("review_summary", {}))
        self.status_var.set(
            "REVIEW READY  •  "
            f"Auto saved {summary.get('automatically_stored', 0)} / "
            f"Needs review {summary.get('needs_manual_review', 0)} / "
            f"Held {summary.get('hold_unknown', 0)}"
        )

    def _build_completed_review_session(self) -> ReviewSession:
        session_id = self.active_scan_session_id or f"session-{uuid4().hex[:8]}"
        try:
            return load_review_session_from_store(session_id, sessions_root=self.sessions_root)
        except FileNotFoundError:
            return ReviewSession(session_id=session_id, records=[])

    def _show_review_session(self, review_session: ReviewSession) -> None:
        existing = self.screens.pop("Review", None)
        if existing is not None and hasattr(existing, "destroy"):
            existing.destroy()
        frame = ttk.Frame(self.content_inner, padding=0, style="Surface.TFrame")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        ReviewWindow(review_session, sessions_root=self.sessions_root, master=frame)
        self.screens["Review"] = frame
        self.show_screen("Review")

    def _apply_review_policy(self, review_session: ReviewSession) -> None:
        settings = load_settings(path=self.settings_path)
        summary = review_session.apply_auto_store_policy(settings.review_mode)
        if summary.get("automatically_stored", 0) > 0:
            sqlite_path = self.sessions_root / "review_inventory.db"
            review_session.commit_to_sqlite(sqlite_path)

    def _open_settings_window(self) -> None:
        SettingsWindow(settings_path=self.settings_path, master=tk.Toplevel(self)).run()

    def _start_live_scan(self, payload: dict[str, object]) -> None:
        if self.capture_loop is not None and self.capture_loop.running:
            return
        scan_screen = self.screens.get("Scan")
        capture_backend = getattr(scan_screen, "capture_backend", None)
        window_handle = self._extract_window_handle(payload)
        self.capture_loop = self.capture_loop_factory(
            event_bus=self.event_bus,
            capture_backend=capture_backend,
            session_id=self.active_scan_session_id or str(payload.get("session_id") or f"session-{uuid4().hex[:8]}"),
            target_window_handle=window_handle,
            target_window_label=str(payload.get("window_id") or ""),
            target_window_identity=self._extract_window_identity(payload, window_handle),
            profile_id=str(payload.get("profile_id") or "defiance"),
            scan_scope=str(payload.get("scan_scope") or "Full"),
            persist_dir=self.sessions_root,
        )
        self.scan_state = "READY_FOR_CAPTURE"
        self.status_var.set("READY FOR RECORDING  •  Use the foreground overlay Record button")
        if scan_screen is not None and hasattr(scan_screen, "bind_recording_overlay"):
            scan_screen.bind_recording_overlay(self.overlay_window, target_window_handle=window_handle)
        elif hasattr(self.overlay_window, "prepare_capture"):
            self.overlay_window.prepare_capture(target_window_handle=window_handle)
        else:
            self.overlay_window.show()

    def _prepare_live_scan(self, payload: dict[str, object]) -> None:
        if self.capture_loop is not None and self.capture_loop.running:
            return
        self._start_live_scan(payload)

    def _begin_capture(self) -> None:
        if self.capture_loop is None:
            return
        if not self.capture_loop.running:
            self.capture_loop.start_capture_loop()
        self._pump_capture_loop_events()
        window_handle = self.capture_loop.target_window_handle
        if window_handle:
            self.after(75, lambda target=window_handle: self._yield_focus_to_target_window(target))

    def _stop_live_scan(self) -> None:
        if self.capture_loop is None:
            self.event_bus.publish(
                UIEvent.SCAN_STOPPED,
                {
                    "session_id": self.active_scan_session_id or "",
                    "window_id": str(self.active_scan_payload.get("window_id") or ""),
                    "buffer_items": 0,
                    "buffer_bytes": 0,
                },
            )
            return
        self.capture_loop.stop_capture_loop()

    def _extract_window_handle(self, payload: dict[str, object]) -> int | None:
        candidate = payload.get("window_handle")
        if candidate not in {None, ""}:
            try:
                return int(candidate)
            except (TypeError, ValueError):
                pass
        candidate = self.latest_test_capture_payload.get("window_handle")
        if candidate not in {None, ""}:
            try:
                return int(candidate)
            except (TypeError, ValueError):
                pass
        window_label = str(payload.get("window_id") or "")
        match = re.search(r"\[(\d+)\]", window_label)
        if match:
            return int(match.group(1))
        return None

    def _extract_window_identity(self, payload: dict[str, object], window_handle: int | None) -> CaptureTargetIdentity | None:
        resolved_handle = int(window_handle or 0)
        if resolved_handle <= 0:
            return None
        title = str(payload.get("window_title") or self.latest_test_capture_payload.get("window_title") or "")
        class_name = str(payload.get("window_class") or self.latest_test_capture_payload.get("window_class") or "")
        candidate_pid = payload.get("window_pid", self.latest_test_capture_payload.get("window_pid"))
        try:
            pid = int(candidate_pid or 0)
        except (TypeError, ValueError):
            pid = 0
        return CaptureTargetIdentity(
            selected_handle=resolved_handle,
            title=title,
            class_name=class_name,
            pid=pid,
        )

    def _normalize_scan_payload(self, payload: dict[str, object]) -> dict[str, object]:
        normalized = dict(payload)
        scan_screen = self.screens.get("Scan")
        if scan_screen is not None:
            normalized.setdefault("profile_id", getattr(getattr(scan_screen, "profile_var", None), "get", lambda: "defiance")())
            normalized.setdefault("window_id", getattr(getattr(scan_screen, "window_var", None), "get", lambda: "")())
            normalized.setdefault("scan_scope", getattr(getattr(scan_screen, "scope_var", None), "get", lambda: "Full")())
            normalized.setdefault("recognition_mode", getattr(getattr(scan_screen, "mode_var", None), "get", lambda: "Balanced")())
            normalized.setdefault("memory_limit", getattr(getattr(scan_screen, "memory_limit_var", None), "get", lambda: "3 GB")())
        if self.latest_test_capture_payload:
            normalized.setdefault("window_handle", self.latest_test_capture_payload.get("window_handle"))
            normalized.setdefault("window_title", self.latest_test_capture_payload.get("window_title"))
            normalized.setdefault("window_class", self.latest_test_capture_payload.get("window_class"))
            normalized.setdefault("window_pid", self.latest_test_capture_payload.get("window_pid"))
        normalized.setdefault("session_id", f"session-{uuid4().hex[:8]}")
        return normalized

    def _yield_focus_to_target_window(self, window_handle: int) -> None:
        try:
            ctypes.windll.user32.SetForegroundWindow(int(window_handle))
        except Exception:
            return

    def _pump_capture_loop_events(self) -> None:
        if self.capture_loop is None:
            return
        self.capture_loop.flush_pending_events()
        if self.capture_loop.running and not self._closing:
            self.after(50, self._pump_capture_loop_events)

    def _recovery_sessions(self) -> list[dict[str, object]]:
        sessions: list[dict[str, object]] = []
        if self.sessions_root.exists():
            for session_dir in sorted(path for path in self.sessions_root.iterdir() if path.is_dir())[:10]:
                sessions.append(
                    {
                        "session_id": session_dir.name,
                        "captured": 0,
                        "resolved": 0,
                        "pending": 0,
                        "last_anchor": "-",
                    }
                )
        if not sessions:
            sessions.append({"session_id": "session-demo", "captured": 0, "resolved": 0, "pending": 0, "last_anchor": "-"})
        return sessions

    def _on_close(self) -> None:
        self._closing = True
        payload = load_settings_payload(path=self.settings_path)
        payload["window_geometry"] = self.geometry()
        if not payload.get("output_root"):
            payload["output_root"] = str(self.output_workspace.root)
        save_settings_payload(payload, path=self.settings_path)
        self.hotkey_manager.close()
        self.overlay_window.close()
        self._unsubscribe_scan_start()
        self._unsubscribe_scan_started()
        self._unsubscribe_scan_stop()
        self._unsubscribe_scan_stopped()
        self._unsubscribe_review_session_ready()
        self._unsubscribe_hotkey()
        self._unsubscribe_test_capture()
        if self.capture_loop is not None and self.capture_loop.running:
            self.capture_loop.stop_capture_loop()
        try:
            self.update_idletasks()
            self.quit()
        except Exception:
            pass
        self.destroy()
