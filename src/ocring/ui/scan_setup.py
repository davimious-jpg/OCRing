from __future__ import annotations

import inspect
import logging
import threading
import tkinter as tk
import time
from datetime import datetime, timezone
from pathlib import Path
from tkinter import ttk
from typing import Callable
from uuid import uuid4

from ocring.ocr.capture_backend import (
    CaptureBackend,
    CaptureFrame,
    RegionScreenshotFallback,
    WindowDescriptor,
    get_foreground_window_handle,
    list_available_windows,
)
from ocring.ocr.event_bus import EventBus, UIEvent
from ocring.ocr.pipeline import extract_from_recorded_frames
from ocring.ocr.profile import DEFAULT_PROFILES_ROOT, create_default_template, load_profile, save_profile
from ocring.ocr.recorded_frame_source import (
    FrameSpoolRecorder,
    finalize_recording,
    is_recording_finalized,
    recover_recording_summary_from_spool,
)
from ocring.ocr.settings import DEFAULT_SETTINGS_PATH, ensure_output_workspace
from ocring.ui.theme import ACCENT, APP_BG, BORDER, SURFACE_ALT_BG, SURFACE_BG, TEXT, TEXT_MUTED, TITLE_FONT

LOGGER = logging.getLogger(__name__)


class ROISelectorWindow:
    def __init__(
        self,
        *,
        master: tk.Misc,
        initial_roi: dict[str, int],
        on_apply: Callable[[dict[str, int]], None],
    ) -> None:
        self.on_apply = on_apply
        self.root = tk.Toplevel(master)
        self.root.title("OCRing ROI Calibration")
        if hasattr(self.root, "geometry"):
            self.root.geometry("520x360")
        try:
            self.root.configure(bg=APP_BG)
        except Exception:
            pass

        ttk.Label(self.root, text="Drag the ROI box, then click Apply.", style="Section.TLabel").pack(anchor="w", padx=16, pady=(16, 8))
        self.canvas = tk.Canvas(self.root, width=460, height=240, bg="#081018", highlightthickness=1, highlightbackground=BORDER)
        self.canvas.pack(fill="both", expand=True, padx=16)
        self.canvas.create_text(230, 18, text="Calibration Preview", fill=TEXT)

        self._drag_anchor: tuple[int, int] | None = None
        self.roi = {
            "x1": int(initial_roi.get("x1", 40)),
            "y1": int(initial_roi.get("y1", 40)),
            "x2": int(initial_roi.get("x2", 280)),
            "y2": int(initial_roi.get("y2", 180)),
        }
        self.rect_id = self.canvas.create_rectangle(
            self.roi["x1"],
            self.roi["y1"],
            self.roi["x2"],
            self.roi["y2"],
            outline=ACCENT,
            width=2,
        )
        self.canvas.bind("<ButtonPress-1>", self._begin_drag)
        self.canvas.bind("<B1-Motion>", self._drag)

        button_frame = ttk.Frame(self.root, padding=(16, 12, 16, 16), style="Surface.TFrame")
        button_frame.pack(fill="x")
        ttk.Button(button_frame, text="Apply", command=self._apply, style="Accent.TButton").pack(side="right", padx=4)
        ttk.Button(button_frame, text="Cancel", command=self.root.destroy).pack(side="right", padx=4)

    def _begin_drag(self, event: tk.Event) -> None:
        self._drag_anchor = (event.x, event.y)

    def _drag(self, event: tk.Event) -> None:
        if self._drag_anchor is None:
            return
        start_x, start_y = self._drag_anchor
        self.roi = {
            "x1": min(start_x, event.x),
            "y1": min(start_y, event.y),
            "x2": max(start_x, event.x),
            "y2": max(start_y, event.y),
        }
        self.canvas.coords(self.rect_id, self.roi["x1"], self.roi["y1"], self.roi["x2"], self.roi["y2"])

    def _apply(self) -> None:
        self.on_apply(dict(self.roi))
        self.root.destroy()


class ScanSetup(ttk.Frame):
    EXTRACTION_STALL_SECONDS = 30.0

    def __init__(
        self,
        master: tk.Misc | None = None,
        *,
        event_bus: EventBus | None = None,
        capture_backend: CaptureBackend | None = None,
        profiles_root: Path = DEFAULT_PROFILES_ROOT,
        roi_selector_factory: Callable[..., ROISelectorWindow] | None = None,
        recorder_factory: Callable[..., FrameSpoolRecorder] = FrameSpoolRecorder,
        extract_recording_func: Callable[..., dict[str, object]] = extract_from_recorded_frames,
        output_workspace_factory: Callable[[], object] | None = None,
    ) -> None:
        super().__init__(master, padding=18, style="Surface.TFrame")
        self.event_bus = event_bus or EventBus()
        self.capture_backend = capture_backend or RegionScreenshotFallback()
        self.profiles_root = profiles_root
        self.roi_selector_factory = roi_selector_factory or ROISelectorWindow
        self.recorder_factory = recorder_factory
        self.extract_recording_func = extract_recording_func
        self.output_workspace_factory = output_workspace_factory or (lambda: ensure_output_workspace(path=DEFAULT_SETTINGS_PATH))
        self.profile_var = tk.StringVar(value="defiance")
        self.window_var = tk.StringVar(value="")
        self.scope_var = tk.StringVar(value="Full")
        self.mode_var = tk.StringVar(value="Balanced")
        self.memory_limit_var = tk.StringVar(value="3 GB")
        self.status_var = tk.StringVar(value="Ready.")
        self.target_status_var = tk.StringVar(value="Target: checking windows...")
        self.next_action_var = tk.StringVar(value="Next: select a live Defiance window.")
        self.current_roi = self._load_profile_roi(self.profile_var.get())
        self.preview_image: tk.PhotoImage | None = None
        self._window_descriptors: dict[str, WindowDescriptor] = {}
        self._frame_spool_recorder: FrameSpoolRecorder | None = None
        self._last_recording_dir: Path | None = None
        self._last_recording_session_id = ""
        self._recording_overlay = None
        self._recording_active = False
        self._has_recording = False
        self._recording_finalizing = False
        self._recording_verified = False
        self._extraction_active = False
        self._extraction_thread: threading.Thread | None = None

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, padding=(0, 0, 0, 14), style="Surface.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)
        ttk.Label(header, text="Scan Setup", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.target_status_var, style="Section.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(header, textvariable=self.next_action_var, style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(3, 0))
        self.header_start_button = ttk.Button(header, text="Start Scan", command=self._start_scan, style="Accent.TButton")
        self.header_start_button.grid(row=0, column=1, rowspan=3, sticky="e", padx=(16, 0))

        controls = ttk.Frame(self, padding=0, style="Surface.TFrame")
        controls.grid(row=1, column=0, sticky="nsew", padx=(0, 18))
        controls.columnconfigure(0, weight=1)

        profile_group = ttk.LabelFrame(controls, text="Game / Profile", padding=12)
        profile_group.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        profile_group.columnconfigure(1, weight=1)
        self._add_combo(profile_group, 0, "Game Profile", self.profile_var, ("defiance", "generic"))
        self.window_combo = self._add_combo(profile_group, 1, "Window", self.window_var, ())
        if hasattr(self.window_combo, "bind"):
            self.window_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_ready_state())
        ttk.Button(profile_group, text="Refresh Windows", command=self._refresh_window_choices).grid(row=2, column=1, sticky="w", pady=(6, 0))

        mode_group = ttk.LabelFrame(controls, text="Scan Parameters", padding=12)
        mode_group.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        mode_group.columnconfigure(1, weight=1)
        self._add_combo(mode_group, 0, "Scan Scope", self.scope_var, ("Full", "Weapons", "Mods"))
        self._add_combo(mode_group, 1, "Recognition Mode", self.mode_var, ("Fast", "Balanced", "Accurate"))
        self._add_combo(mode_group, 2, "Memory Limit", self.memory_limit_var, ("1 GB", "2 GB", "3 GB"))

        actions_group = ttk.LabelFrame(controls, text="Actions", padding=12)
        actions_group.grid(row=2, column=0, sticky="ew")
        actions_group.columnconfigure(0, weight=1)
        actions_group.columnconfigure(1, weight=1)
        actions_group.columnconfigure(2, weight=1)
        ttk.Button(actions_group, text="Test Capture", command=self._test_capture).grid(row=0, column=0, padx=(0, 8), pady=4, sticky="ew")
        ttk.Button(actions_group, text="Calibrate Region", command=self._calibrate_region).grid(row=0, column=1, padx=(0, 8), pady=4, sticky="ew")
        self.start_button = ttk.Button(actions_group, text="Start Scan", command=self._start_scan, style="Accent.TButton")
        self.start_button.grid(row=0, column=2, pady=4, sticky="ew")
        self.record_button = ttk.Button(actions_group, text="Start Recording", command=self._start_recording)
        self.record_button.grid(row=1, column=0, padx=(0, 8), pady=4, sticky="ew")
        self.stop_recording_button = ttk.Button(actions_group, text="Stop Recording", command=self._stop_recording)
        self.stop_recording_button.grid(row=1, column=1, padx=(0, 8), pady=4, sticky="ew")
        self.extract_recording_button = ttk.Button(actions_group, text="Extract From Recording", command=self._extract_recording, style="Accent.TButton")
        self.extract_recording_button.grid(row=1, column=2, pady=4, sticky="ew")
        self._bind_action_diagnostics(self.header_start_button, "START_SCAN")
        self._bind_action_diagnostics(self.start_button, "START_SCAN")
        self._bind_action_diagnostics(self.record_button, "START_RECORDING")
        self._bind_action_diagnostics(self.stop_recording_button, "STOP_RECORDING")
        self._bind_action_diagnostics(self.extract_recording_button, "EXTRACT_RECORDING")

        preview_panel = ttk.Frame(self, padding=14, style="AltSurface.TFrame")
        preview_panel.grid(row=1, column=1, sticky="nsew")
        preview_panel.columnconfigure(0, weight=1)
        preview_panel.rowconfigure(1, weight=1)
        ttk.Label(preview_panel, text="Window / Region Preview", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.preview = tk.Canvas(preview_panel, height=340, width=560, bg="#081018", highlightthickness=1, highlightbackground=BORDER)
        self.preview.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self._render_placeholder()

        self.status_label = tk.Label(
            self,
            textvariable=self.status_var,
            bg=APP_BG,
            fg=TEXT_MUTED,
            font=TITLE_FONT,
            anchor="w",
        )
        self.status_label.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        self._refresh_window_choices()
        self._refresh_ready_state()
        self._set_recording_state(recording=False, has_recording=False)

    def _add_combo(self, parent: object, row: int, label: str, variable: tk.StringVar, values: tuple[str, ...]):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=6, padx=(0, 8))
        combo = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly")
        combo.grid(row=row, column=1, sticky="ew", pady=6)
        return combo

    def _start_scan(self) -> None:
        self._publish_action_event("START_SCAN_CALLBACK_ENTERED", getattr(self, "start_button", None))
        self.prepare_scan_session()

    def prepare_scan_session(self) -> None:
        self._refresh_selected_window_descriptor()
        window = self._selected_window()
        if window is None:
            self.status_var.set("Select a game window before preparing capture.")
            return
        payload = {
            "session_id": f"session-{uuid4().hex[:8]}",
            "profile_id": self.profile_var.get(),
            "window_id": self.window_var.get(),
            "window_handle": window.handle if window is not None else 0,
            "window_title": window.title if window is not None else "",
            "window_class": window.class_name if window is not None else "",
            "window_pid": window.pid if window is not None else 0,
            "scan_scope": self.scope_var.get(),
            "recognition_mode": self.mode_var.get(),
            "memory_limit": self.memory_limit_var.get(),
        }
        self.event_bus.publish(UIEvent.SCAN_START_REQUESTED, payload)
        if hasattr(self, "status_var"):
            self.status_var.set("Session ready. Use Record in the foreground overlay.")

    def _test_capture(self) -> None:
        self._perform_test_capture()

    def _start_recording(self) -> None:
        self._publish_action_event("START_RECORDING_CALLBACK_ENTERED", getattr(self, "record_button", None))
        event_bus = getattr(self, "event_bus", None)
        self._refresh_selected_window_descriptor()
        window = self._selected_window()
        if window is None:
            self.status_var.set("Recording unavailable: select a target window first.")
            if event_bus is not None:
                event_bus.publish(UIEvent.RECORDER_START_FAILED, {"reason": "WINDOW_NOT_SELECTED"})
            recording_overlay = getattr(self, "_recording_overlay", None)
            if recording_overlay is not None and hasattr(recording_overlay, "mark_recording_failed"):
                recording_overlay.mark_recording_failed("no target")
            return
        if not self._is_capture_ready_window(window):
            self.status_var.set("Waiting for target: restore the selected game window, then click Record again.")
            if event_bus is not None:
                event_bus.publish(UIEvent.RECORDER_START_FAILED, {"reason": "WINDOW_NOT_CAPTURE_READY"})
            recording_overlay = getattr(self, "_recording_overlay", None)
            if recording_overlay is not None and hasattr(recording_overlay, "mark_recording_waiting"):
                recording_overlay.mark_recording_waiting("target")
            return
        workspace = self.output_workspace_factory()
        recordings_root = Path(getattr(workspace, "root", Path("E:/Ocring/output"))) / "recordings"
        session_id = f"recording-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:6]}"
        recording_dir = recordings_root / session_id
        if event_bus is not None:
            event_bus.publish(
                UIEvent.RECORDER_START_REQUESTED,
                {
                    "session_id": session_id,
                    "window_handle": window.handle,
                    "window_title": window.title,
                    "recording_dir": str(recording_dir),
                },
            )
        try:
            self._frame_spool_recorder = self.recorder_factory(
                capture_backend=self.capture_backend,
                recording_dir=recording_dir,
                session_id=session_id,
                target_window_handle=window.handle,
                target_visible=window.is_visible,
                requested_fps=12.0,
                event_bus=event_bus,
            )
            started = bool(self._frame_spool_recorder.start())
        except Exception as error:
            self._frame_spool_recorder = None
            reason = f"{type(error).__name__}: {error}"
            if event_bus is not None:
                event_bus.publish(UIEvent.RECORDER_START_FAILED, {"session_id": session_id, "reason": reason})
            recording_overlay = getattr(self, "_recording_overlay", None)
            if recording_overlay is not None and hasattr(recording_overlay, "mark_recording_failed"):
                recording_overlay.mark_recording_failed("start failed")
            self.status_var.set(f"Recording failed: {reason}")
            return
        if not started:
            self._frame_spool_recorder = None
            if event_bus is not None:
                event_bus.publish(UIEvent.RECORDER_START_FAILED, {"session_id": session_id, "reason": "RECORDER_NOT_STARTED"})
            recording_overlay = getattr(self, "_recording_overlay", None)
            if recording_overlay is not None and hasattr(recording_overlay, "mark_recording_failed"):
                recording_overlay.mark_recording_failed("not started")
            self.status_var.set("Recording failed: recorder did not enter running state.")
            return
        self._last_recording_dir = recording_dir
        self._last_recording_session_id = session_id
        self._recording_finalizing = False
        self._recording_verified = False
        self._set_recording_state(recording=True, has_recording=False)
        if event_bus is not None:
            event_bus.publish(
                UIEvent.RECORDER_STARTED,
                {
                    "session_id": session_id,
                    "window_handle": window.handle,
                    "recording_dir": str(recording_dir),
                },
            )
        recording_overlay = getattr(self, "_recording_overlay", None)
        if recording_overlay is not None and hasattr(recording_overlay, "mark_recording_active"):
            recording_overlay.mark_recording_active()
        self.status_var.set(f"Recording pixels only to {recording_dir}. OCR will run after Stop.")

    def _stop_recording(self) -> None:
        self._publish_action_event("STOP_RECORDING_CALLBACK_ENTERED", getattr(self, "stop_recording_button", None))
        if self._frame_spool_recorder is None:
            self.status_var.set("No recording is active.")
            return
        self._recording_finalizing = True
        self._sync_recording_controls()
        recording_overlay = getattr(self, "_recording_overlay", None)
        if recording_overlay is not None and hasattr(recording_overlay, "mark_recording_finalizing"):
            recording_overlay.mark_recording_finalizing()
        self.status_var.set("Finalizing recording: stopping recorder and verifying frame spool...")
        self.event_bus.publish(
            UIEvent.RECORDING_FINALIZING,
            {
                "session_id": self._last_recording_session_id,
                "recording_dir": str(self._last_recording_dir or ""),
            },
        )
        if hasattr(self, "tk"):
            try:
                self.update_idletasks()
            except tk.TclError:
                LOGGER.exception("Failed to repaint recording finalizing state")
        try:
            summary = self._frame_spool_recorder.stop()
            self._frame_spool_recorder = None
            manifest = finalize_recording(summary.recording_dir, summary)
        except Exception as error:
            reason = f"{type(error).__name__}: {error}"
            recovered = self._recover_recording_from_stop_failure(reason)
            if recovered:
                return
            self._frame_spool_recorder = None
            self._recording_finalizing = False
            self._recording_verified = False
            self._set_recording_state(recording=False, has_recording=False)
            self.event_bus.publish(
                UIEvent.RECORDING_FINALIZE_FAILED,
                {
                    "session_id": self._last_recording_session_id,
                    "recording_dir": str(self._last_recording_dir or ""),
                    "reason": reason,
                },
            )
            if recording_overlay is not None and hasattr(recording_overlay, "mark_recording_failed"):
                recording_overlay.mark_recording_failed("finalize failed")
            self.status_var.set(f"Recording finalization failed: {reason}. Spool preserved.")
            return
        self._finish_recording_finalized(summary, manifest, recovered_from_spool=False)

    def _finish_recording_finalized(self, summary: object, manifest: dict[str, object], *, recovered_from_spool: bool) -> None:
        self._recording_finalizing = False
        self._recording_verified = True
        self._set_recording_state(recording=False, has_recording=int(getattr(summary, "source_frames", 0)) > 0)
        self.event_bus.publish(
            UIEvent.RECORDING_FINALIZED,
            {
                "session_id": summary.session_id,
                "recording_dir": str(summary.recording_dir),
                "frame_count": summary.source_frames,
                "first_sequence_id": summary.first_sequence_id,
                "last_sequence_id": summary.last_sequence_id,
                "total_bytes": summary.bytes_written,
                "manifest_status": manifest.get("status"),
                "recovered_from_spool": recovered_from_spool,
            },
        )
        recording_overlay = getattr(self, "_recording_overlay", None)
        if recording_overlay is not None and hasattr(recording_overlay, "mark_recorded_ready"):
            recording_overlay.mark_recorded_ready()
        prefix = "Recording recovered and verified" if recovered_from_spool else "Recording verified"
        self.status_var.set(
            f"{prefix}: {summary.source_frames} frames, {summary.achieved_fps:.1f} FPS, {summary.disk_write_mbps:.2f} MB/s."
        )

    def _recover_recording_from_stop_failure(self, reason: str) -> bool:
        recording_dir = self._last_recording_dir
        if recording_dir is None:
            return False
        try:
            summary = recover_recording_summary_from_spool(
                recording_dir,
                session_id=self._last_recording_session_id or recording_dir.name,
                requested_fps=12.0,
            )
            if summary.source_frames <= 0:
                return False
            manifest = finalize_recording(recording_dir, summary)
        except Exception:
            LOGGER.exception("Stop/finalize recovery from preserved spool failed")
            return False
        self._frame_spool_recorder = None
        self.event_bus.publish(
            UIEvent.RECORDING_FINALIZE_FAILED,
            {
                "session_id": self._last_recording_session_id,
                "recording_dir": str(recording_dir),
                "reason": reason,
                "recovered_from_spool": True,
            },
        )
        self._finish_recording_finalized(summary, manifest, recovered_from_spool=True)
        return True

    def _extract_recording(self) -> dict[str, object] | None:
        self._publish_action_event("EXTRACT_RECORDING_CALLBACK_ENTERED", getattr(self, "extract_recording_button", None))
        if self._last_recording_dir is None:
            self.status_var.set("No recorded frame spool is available to extract.")
            return None
        if self._recording_active or getattr(self, "_frame_spool_recorder", None) is not None:
            self.status_var.set("Cannot extract while recording is active.")
            return None
        if self._recording_finalizing:
            self.status_var.set("Cannot extract while recording is finalizing.")
            return None
        if not self._recording_verified or not is_recording_finalized(self._last_recording_dir):
            if not self._recover_recording_manifest_if_possible(self._last_recording_dir):
                self.status_var.set("Cannot extract until the recording is RECORDED_VERIFIED.")
                return None
        if not is_recording_finalized(self._last_recording_dir):
            self.status_var.set("Cannot extract until the recording is RECORDED_VERIFIED.")
            return None
        if self._extraction_active and self._extraction_thread is not None and self._extraction_thread.is_alive():
            self.status_var.set("Recording extraction is already processing.")
            return None
        recording_overlay = getattr(self, "_recording_overlay", None)
        if recording_overlay is not None and hasattr(recording_overlay, "mark_recording_processing"):
            recording_overlay.mark_recording_processing()
        workspace = self.output_workspace_factory()
        recording_dir = self._last_recording_dir
        profile_id = self.profile_var.get()
        session_id = self._last_recording_session_id or None
        persist_dir = Path(getattr(workspace, "sessions_dir", Path("E:/Ocring/output/sessions")))
        total_frames = self._count_recorded_frames(recording_dir)
        self._extraction_active = True
        self._sync_recording_controls()
        self.status_var.set(f"Processing recording: 0 / {total_frames} frames.")
        self.event_bus.publish(
            UIEvent.EXTRACTION_WORKER_START_REQUESTED,
            {
                "session_id": session_id,
                "recording_dir": str(recording_dir),
                "total_frames": total_frames,
                "thread_name": threading.current_thread().name,
                "thread_id": threading.get_ident(),
            },
        )
        self._extraction_thread = threading.Thread(
            target=self._run_recorded_extraction_worker,
            args=(recording_dir, profile_id, session_id, persist_dir, total_frames),
            name=f"ocring-extract-{session_id or 'recording'}",
            daemon=True,
        )
        self._extraction_thread.start()
        return None

    def _run_recorded_extraction_worker(
        self,
        recording_dir: Path,
        profile_id: str,
        session_id: str | None,
        persist_dir: Path,
        total_frames: int,
    ) -> None:
        worker_payload = {
            "session_id": session_id,
            "recording_dir": str(recording_dir),
            "total_frames": total_frames,
            "thread_name": threading.current_thread().name,
            "thread_id": threading.get_ident(),
        }
        self.event_bus.publish(UIEvent.EXTRACTION_WORKER_STARTED, worker_payload)
        self.event_bus.publish(UIEvent.RECORDED_EXTRACTION_STARTED, worker_payload)
        progress_lock = threading.Lock()
        progress_state = {
            "last_progress_at": time.monotonic(),
            "stage": "Loading recording",
            "current_index": 0,
            "total_count": total_frames,
            "stalled_reported": False,
        }
        watchdog_stop = threading.Event()

        def publish_progress(payload: dict[str, object]) -> None:
            stage = str(payload.get("stage") or "Processing")
            current_index = int(payload.get("current_index", payload.get("processed_frames", 0)) or 0)
            total_count = int(payload.get("total_count", total_frames) or total_frames)
            progress_payload = {
                **worker_payload,
                **payload,
                "processed_frames": current_index,
                "total_frames": total_count,
            }
            with progress_lock:
                progress_state["last_progress_at"] = time.monotonic()
                progress_state["stage"] = stage
                progress_state["current_index"] = current_index
                progress_state["total_count"] = total_count
                progress_state["stalled_reported"] = False
            self.event_bus.publish(UIEvent.RECORDED_EXTRACTION_PROGRESS, progress_payload)
            self._dispatch_ui_update(lambda: self._apply_recorded_extraction_progress(progress_payload))

        def watchdog() -> None:
            while not watchdog_stop.wait(1.0):
                with progress_lock:
                    inactive_for = time.monotonic() - float(progress_state["last_progress_at"])
                    already_reported = bool(progress_state["stalled_reported"])
                    if inactive_for < self.EXTRACTION_STALL_SECONDS or already_reported:
                        continue
                    progress_state["stalled_reported"] = True
                    stalled_payload = {
                        **worker_payload,
                        "stage": progress_state["stage"],
                        "current_index": progress_state["current_index"],
                        "total_count": progress_state["total_count"],
                        "inactive_seconds": round(inactive_for, 3),
                    }
                self.event_bus.publish(UIEvent.RECORDED_EXTRACTION_STALLED, stalled_payload)
                self._dispatch_ui_update(lambda: self._apply_recorded_extraction_stalled(stalled_payload))

        watchdog_thread = threading.Thread(
            target=watchdog,
            name=f"ocring-extract-watchdog-{session_id or 'recording'}",
            daemon=True,
        )
        watchdog_thread.start()
        publish_progress({"stage": "Loading recording", "current_index": 0, "total_count": total_frames})
        try:
            kwargs = {
                "profile_id": profile_id,
                "session_id": session_id,
                "persist_dir": persist_dir,
            }
            accepts_progress_callback = False
            try:
                signature = inspect.signature(self.extract_recording_func)
                accepts_progress_callback = "progress_callback" in signature.parameters or any(
                    parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
                )
            except (TypeError, ValueError):
                accepts_progress_callback = False
            if accepts_progress_callback:
                kwargs["progress_callback"] = publish_progress
            report = self.extract_recording_func(recording_dir, **kwargs)
        except Exception as error:  # pragma: no cover - exercised by focused UI tests.
            LOGGER.exception("Recorded extraction failed")
            watchdog_stop.set()
            reason = f"{type(error).__name__}: {error}"
            self.event_bus.publish(UIEvent.RECORDED_EXTRACTION_FAILED, {**worker_payload, "reason": reason})
            self._dispatch_ui_update(lambda: self._finish_recorded_extraction_failure(reason))
            return
        watchdog_stop.set()
        publish_progress({"stage": "Finalizing Review", "current_index": total_frames, "total_count": total_frames})
        self.event_bus.publish(UIEvent.RECORDED_EXTRACTION_COMPLETED, worker_payload)
        self._dispatch_ui_update(lambda: self._finish_recorded_extraction_success(report))

    def _apply_recorded_extraction_progress(self, payload: dict[str, object]) -> None:
        stage = str(payload.get("stage") or "Processing")
        current_index = int(payload.get("current_index", payload.get("processed_frames", 0)) or 0)
        total_count = int(payload.get("total_count", payload.get("total_frames", 0)) or 0)
        if total_count > 0:
            self.status_var.set(f"{stage}: {current_index} / {total_count}.")
        else:
            self.status_var.set(f"{stage}.")

    def _apply_recorded_extraction_stalled(self, payload: dict[str, object]) -> None:
        stage = str(payload.get("stage") or "unknown")
        inactive_seconds = float(payload.get("inactive_seconds", 0.0) or 0.0)
        self.status_var.set(f"Recorded extraction stalled at {stage} after {inactive_seconds:.0f}s without progress.")

    def _finish_recorded_extraction_success(self, report: dict[str, object]) -> None:
        self._extraction_active = False
        self._extraction_thread = None
        self._set_recording_state(recording=False, has_recording=True)
        summary = dict(report.get("coverage_summary", {}))
        review_summary = dict(report.get("review_summary", {}))
        self.status_var.set(
            "Extracted recording: "
            f"Entries observed {summary.get('unique_entries_observed', 0)}, "
            f"Stable {summary.get('stable_identities', 0)}, "
            f"Auto saved {review_summary.get('automatically_stored', 0)}, "
            f"Needs review {review_summary.get('needs_manual_review', 0)}, "
            f"Unknown {review_summary.get('hold_unknown', 0)}, "
            f"Coverage gaps {summary.get('coverage_gaps', 0)}."
        )
        self.event_bus.publish(
            UIEvent.REVIEW_SESSION_READY,
            {
                "session_id": self._last_recording_session_id,
                "record_count": len(report.get("assembled_records", [])),
                "review_summary": review_summary,
                "recorded_capture_mode": True,
            },
        )
        self.event_bus.publish(
            UIEvent.REVIEW_SESSION_READY_PUBLISHED,
            {
                "session_id": self._last_recording_session_id,
                "record_count": len(report.get("assembled_records", [])),
                "recorded_capture_mode": True,
            },
        )
        recording_overlay = getattr(self, "_recording_overlay", None)
        if recording_overlay is not None and hasattr(recording_overlay, "hide"):
            recording_overlay.hide()

    def _finish_recorded_extraction_failure(self, reason: str) -> None:
        self._extraction_active = False
        self._extraction_thread = None
        self._set_recording_state(recording=False, has_recording=self._last_recording_dir is not None)
        self.status_var.set(f"Recorded extraction failed: {reason}. Recording preserved for retry.")
        recording_overlay = getattr(self, "_recording_overlay", None)
        if recording_overlay is not None and hasattr(recording_overlay, "mark_recording_failed"):
            recording_overlay.mark_recording_failed("extract failed")

    def _recover_recording_manifest_if_possible(self, recording_dir: Path) -> bool:
        try:
            summary = recover_recording_summary_from_spool(
                recording_dir,
                session_id=self._last_recording_session_id or Path(recording_dir).name,
                requested_fps=12.0,
            )
            if summary.source_frames <= 0:
                return False
            manifest = finalize_recording(recording_dir, summary)
        except Exception as error:
            LOGGER.exception("Recorded spool recovery failed")
            self.status_var.set(f"Recording recovery failed: {type(error).__name__}: {error}")
            return False
        self._recording_verified = True
        self._set_recording_state(recording=False, has_recording=True)
        self.event_bus.publish(
            UIEvent.RECORDING_FINALIZED,
            {
                "session_id": summary.session_id,
                "recording_dir": str(recording_dir),
                "frame_count": summary.source_frames,
                "first_sequence_id": summary.first_sequence_id,
                "last_sequence_id": summary.last_sequence_id,
                "total_bytes": summary.bytes_written,
                "manifest_status": manifest.get("status"),
                "recovered_from_spool": True,
            },
        )
        return True

    def _dispatch_ui_update(self, callback: Callable[[], None]) -> None:
        if not hasattr(self, "tk"):
            callback()
            return
        after = getattr(self, "after", None)
        if callable(after):
            try:
                after(0, callback)
                return
            except (tk.TclError, RuntimeError):
                LOGGER.exception("Failed to dispatch recorded extraction update to Tk thread")
        callback()

    @staticmethod
    def _count_recorded_frames(recording_dir: Path) -> int:
        try:
            return sum(1 for path in recording_dir.iterdir() if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg"})
        except OSError:
            return 0

    def bind_recording_overlay(self, overlay: object, *, target_window_handle: int | None = None) -> None:
        self._recording_overlay = overlay
        if hasattr(overlay, "set_recording_handlers"):
            overlay.set_recording_handlers(
                on_start_recording=self._start_recording,
                on_stop_recording=self._stop_recording,
                on_extract_recording=self._extract_recording,
            )
        if hasattr(overlay, "prepare_recording"):
            overlay.prepare_recording(target_window_handle=target_window_handle)
        elif hasattr(overlay, "show"):
            overlay.show()

    def _perform_test_capture(self) -> dict[str, object]:
        window = self._selected_window()
        if window is None:
            self._render_placeholder(overlay_text="No live window selected. Refresh windows and choose the game window.")
            payload = {
                "success": False,
                "backend": getattr(getattr(self.capture_backend, "kind", None), "value", str(getattr(self.capture_backend, "kind", "unknown"))),
                "width": 0,
                "height": 0,
                "source": "",
                "status": "CAPTURE_PAUSED",
                "roi": dict(self.current_roi),
                "error_message": "WINDOW_NOT_SELECTED",
            }
            self.event_bus.publish(UIEvent.CAPTURE_LOST, {"reason": "WINDOW_NOT_SELECTED"})
            self.event_bus.publish(UIEvent.TEST_CAPTURE_COMPLETE, payload)
            self.status_var.set("Test capture failed: select a live window.")
            return payload

        frame = self.capture_backend.capture(
            target_window_handle=window.handle,
            foreground_window_handle=get_foreground_window_handle(),
            target_visible=window.is_visible,
        )
        payload = {
            "success": frame.status.value == "CAPTURE_ACTIVE",
            "backend": str(frame.backend.value if hasattr(frame.backend, "value") else frame.backend),
            "width": frame.width,
            "height": frame.height,
            "source": frame.source,
            "status": str(frame.status.value if hasattr(frame.status, "value") else frame.status),
            "roi": dict(self.current_roi),
            "window_id": self.window_var.get(),
            "window_handle": window.handle,
            "window_title": window.title,
            "window_class": window.class_name,
            "window_pid": window.pid,
            "image_path": frame.image_path,
            "error_message": frame.reason,
        }
        if frame.status.value == "CAPTURE_ACTIVE":
            self._render_capture_preview(frame)
            self.event_bus.publish(UIEvent.CAPTURE_RECOVERED, {"window_id": self.window_var.get()})
            self.status_var.set("Test capture complete.")
        else:
            self._render_placeholder(overlay_text=f"Capture paused: {frame.reason}")
            self.event_bus.publish(UIEvent.CAPTURE_LOST, {"window_id": self.window_var.get(), "reason": frame.reason})
            self.status_var.set(f"Test capture failed: {frame.reason}")
        self.event_bus.publish(UIEvent.TEST_CAPTURE_COMPLETE, payload)
        return payload

    def _bind_action_diagnostics(self, button: object, action_name: str) -> None:
        if not hasattr(button, "bind"):
            return
        button.bind("<Enter>", lambda _event, name=action_name, widget=button: self._publish_action_event(f"{name}_MOUSE_ENTER", widget), add="+")
        button.bind("<Button-1>", lambda _event, name=action_name, widget=button: self._publish_action_event(f"{name}_CLICK", widget), add="+")

    def _publish_action_event(self, event_name: str, widget: object | None = None) -> None:
        event_type = getattr(UIEvent, event_name, None)
        if event_type is None:
            return
        payload = {
            "event": event_name,
            "widget": str(widget) if widget is not None else "",
            "state": self._widget_state(widget),
            "target_status": self.target_status_var.get() if hasattr(self, "target_status_var") else "",
            "next_action": self.next_action_var.get() if hasattr(self, "next_action_var") else "",
            "window_id": self.window_var.get() if hasattr(self, "window_var") else "",
        }
        self.event_bus.publish(event_type, payload)

    @staticmethod
    def _widget_state(widget: object | None) -> str:
        if widget is None or not hasattr(widget, "cget"):
            return ""
        try:
            return str(widget.cget("state"))
        except Exception:
            return ""

    def _calibrate_region(self) -> None:
        selector = self.roi_selector_factory(
            master=self.winfo_toplevel(),
            initial_roi=dict(self.current_roi),
            on_apply=self._apply_calibrated_roi,
        )
        if hasattr(selector, "root") and hasattr(selector.root, "transient"):
            selector.root.transient(self.winfo_toplevel())

    def _apply_calibrated_roi(self, roi: dict[str, int]) -> None:
        self.current_roi = dict(roi)
        self._save_profile_roi(self.profile_var.get(), self.current_roi)
        self._render_placeholder(overlay_text=f"ROI: {self.current_roi}")
        self.event_bus.publish(
            UIEvent.PROFILE_CHANGED,
            {"profile_id": self.profile_var.get(), "roi": dict(self.current_roi)},
        )
        self.status_var.set("Calibration saved.")

    def _render_placeholder(self, *, overlay_text: str = "Region preview pending. Use Test Capture.") -> None:
        self.preview.delete("all")
        self.preview.create_rectangle(0, 0, 560, 340, fill="#081018", outline="")
        self.preview.create_text(280, 112, text="OCRing Scan Preview", fill=TEXT, font=("Segoe UI Semibold", 14))
        self.preview.create_text(280, 158, text=overlay_text, fill=TEXT_MUTED, width=420, font=("Segoe UI", 12))
        self.preview.create_rectangle(
            self.current_roi["x1"] // 4,
            self.current_roi["y1"] // 4,
            max(self.current_roi["x2"] // 4, self.current_roi["x1"] // 4 + 24),
            max(self.current_roi["y2"] // 4, self.current_roi["y1"] // 4 + 24),
            outline=ACCENT,
            width=2,
        )

    def _render_capture_preview(self, frame: CaptureFrame) -> None:
        width = 560
        height = 340
        self.preview.delete("all")
        rendered_real_image = False
        if frame.image_path:
            try:
                from PIL import Image, ImageTk

                image = Image.open(frame.image_path).convert("RGB")
                image.thumbnail((width, height))
                self.preview_image = ImageTk.PhotoImage(image)
                x_offset = max(0, (width - image.width) // 2)
                y_offset = max(0, (height - image.height) // 2)
                self.preview.create_rectangle(0, 0, width, height, fill="#081018", outline="")
                self.preview.create_image(x_offset, y_offset, anchor="nw", image=self.preview_image)
                rendered_real_image = True
            except Exception:
                rendered_real_image = False
        if not rendered_real_image:
            self.preview_image = tk.PhotoImage(width=width, height=height)
            self.preview_image.put("#0b1723", to=(0, 0, width, height))
            self.preview_image.put(SURFACE_ALT_BG, to=(20, 20, width - 20, height - 20))
            self.preview.create_image(0, 0, anchor="nw", image=self.preview_image)
        self.preview.create_rectangle(
            max(self.current_roi["x1"] // 4, 20),
            max(self.current_roi["y1"] // 4, 20),
            min(max(self.current_roi["x2"] // 4, 92), width - 20),
            min(max(self.current_roi["y2"] // 4, 92), height - 20),
            outline=ACCENT,
            width=3,
        )
        self.preview.create_text(
            width // 2,
            34,
            text=f"{frame.source.upper()} CAPTURE",
            fill=TEXT,
            font=("Segoe UI Semibold", 13),
        )
        self.preview.create_text(
            width // 2,
            height - 36,
            text=f"{frame.width}x{frame.height} | {frame.status.value} | {frame.window_title or self.window_var.get()}",
            fill=TEXT_MUTED,
            font=("Segoe UI", 12),
        )

    def _selected_window_handle(self) -> int:
        window = self._selected_window()
        return 0 if window is None else window.handle

    def _selected_window(self) -> WindowDescriptor | None:
        selected = self.window_var.get().strip()
        if not selected:
            return None
        return self._window_descriptors.get(selected)

    def _refresh_window_choices(self) -> None:
        windows = sorted(list_available_windows(), key=self._window_sort_key, reverse=True)
        self._window_descriptors = {self._format_window_label(window): window for window in windows}
        values = tuple(self._window_descriptors.keys())
        if hasattr(self.window_combo, "configure"):
            self.window_combo.configure(values=values)
        current = self.window_var.get().strip()
        current_window = self._window_descriptors.get(current)
        preferred = self._preferred_window_label(values)
        if (
            current not in self._window_descriptors
            or not self._is_capture_ready_window(current_window)
            or (preferred and current != preferred and not self._is_defiance_game_window(current_window))
        ):
            self.window_var.set(preferred)
        if values:
            self.status_var.set(f"Detected {len(values)} live windows.")
        else:
            self.status_var.set("No visible windows detected.")
        self._refresh_ready_state()

    def _refresh_ready_state(self) -> bool:
        window = self._selected_window()
        if window is None:
            self.target_status_var.set("Target: no game window selected")
            self.next_action_var.set("Next: refresh windows and choose Defiance.")
            self._set_start_enabled(False)
            self._sync_recording_controls()
            return False
        if not window.is_visible or window.is_iconic:
            self.target_status_var.set(f"Target: {window.title} is not capture-ready")
            self.next_action_var.set("Next: Start Scan can arm the overlay; Record waits until the target is restored.")
            self._set_start_enabled(True)
            self._sync_recording_controls()
            return False
        self.target_status_var.set(f"Target: {window.title} [{window.handle}] • {window.width}x{window.height}")
        self.next_action_var.set(f"Next: Start Scan opens the READY overlay. Scope: {self.scope_var.get()} • Mode: {self.mode_var.get()}")
        self._set_start_enabled(True)
        self._sync_recording_controls()
        return True

    def _set_start_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button_name in ("start_button", "header_start_button"):
            button = getattr(self, button_name, None)
            if button is not None and hasattr(button, "configure"):
                button.configure(state=state)

    def _set_recording_state(self, *, recording: bool, has_recording: bool) -> None:
        self._recording_active = recording
        self._has_recording = has_recording
        self._sync_recording_controls()

    def _sync_recording_controls(self) -> None:
        target_selected = self._selected_window() is not None
        recording_active = bool(getattr(self, "_recording_active", False))
        has_recording = bool(getattr(self, "_has_recording", False))
        extraction_active = bool(getattr(self, "_extraction_active", False))
        recording_finalizing = bool(getattr(self, "_recording_finalizing", False))
        recording_verified = bool(getattr(self, "_recording_verified", False))
        states = {
            "record_button": "disabled" if recording_active or recording_finalizing or extraction_active or not target_selected else "normal",
            "stop_recording_button": "normal" if recording_active and not recording_finalizing else "disabled",
            "extract_recording_button": "normal" if has_recording and recording_verified and not recording_active and not recording_finalizing and not extraction_active else "disabled",
        }
        for button_name, state in states.items():
            button = getattr(self, button_name, None)
            if button is not None and hasattr(button, "configure"):
                button.configure(state=state)

    def _format_window_label(self, window: WindowDescriptor) -> str:
        return f"{window.title} [{window.handle}]"

    def _preferred_window_label(self, values: tuple[str, ...]) -> str:
        for label in values:
            window = self._window_descriptors[label]
            if self._is_defiance_game_window(window) and self._is_capture_ready_window(window):
                return label
        for label in values:
            window = self._window_descriptors[label]
            if self._is_defiance_game_window(window):
                return label
        for label in values:
            window = self._window_descriptors[label]
            if self._is_capture_ready_window(window) and self._is_capture_candidate_window(window):
                return label
        return values[0] if values else ""

    def _refresh_selected_window_descriptor(self) -> None:
        selected = self.window_var.get().strip()
        if not selected:
            return
        if not hasattr(self, "window_combo"):
            self._refresh_ready_state()
            return
        current = self._window_descriptors.get(selected)
        try:
            windows = list_available_windows()
        except Exception:
            self._refresh_ready_state()
            return
        self._window_descriptors = {self._format_window_label(window): window for window in windows}
        values = tuple(self._window_descriptors.keys())
        if hasattr(self.window_combo, "configure"):
            self.window_combo.configure(values=values)
        refreshed_label = ""
        if current is not None:
            for label, window in self._window_descriptors.items():
                if window.handle == current.handle:
                    refreshed_label = label
                    break
        if not refreshed_label and current is not None and self._is_defiance_game_window(current):
            preferred = self._preferred_window_label(values)
            if preferred and self._is_defiance_game_window(self._window_descriptors[preferred]):
                refreshed_label = preferred
        if refreshed_label:
            self.window_var.set(refreshed_label)
        elif selected not in self._window_descriptors:
            self.window_var.set(self._preferred_window_label(values))
        self._refresh_ready_state()

    def _window_sort_key(self, window: WindowDescriptor) -> tuple[int, int, int]:
        return (
            1 if self._is_defiance_game_window(window) else 0,
            1 if self._is_capture_ready_window(window) else 0,
            window.width * window.height,
        )

    def _is_capture_ready_window(self, window: WindowDescriptor | None) -> bool:
        return bool(window is not None and window.is_visible and not window.is_iconic and window.width >= 640 and window.height >= 480)

    def _is_capture_candidate_window(self, window: WindowDescriptor) -> bool:
        title = window.title.lower()
        class_name = window.class_name.lower()
        blocked_tokens = ("nvidia geforce overlay", "ocring", "program manager")
        if any(token in title for token in blocked_tokens):
            return False
        blocked_classes = ("cef-osc-widget", "tktopLevel".lower())
        return not any(token in class_name for token in blocked_classes)

    def _is_defiance_game_window(self, window: WindowDescriptor) -> bool:
        title = window.title.lower()
        class_name = window.class_name.lower()
        if title.strip() == "defiance":
            return True
        if "defiance" not in title:
            return False
        editor_or_browser_tokens = ("visual studio code", "chrome", "edge", "firefox", ".md", ".txt")
        if any(token in title for token in editor_or_browser_tokens):
            return False
        game_class_tokens = ("unreal", "twnapp", "defiance")
        return any(token in class_name for token in game_class_tokens) or window.width >= 900

    def _load_profile_roi(self, profile_id: str) -> dict[str, int]:
        try:
            profile = load_profile(profile_id, profiles_root=self.profiles_root)
        except (FileNotFoundError, OSError, ValueError):
            return {"x1": 40, "y1": 40, "x2": 280, "y2": 180}
        if profile.screens:
            roi = profile.screens[0].get("roi", {})
            if isinstance(roi, dict):
                return {
                    "x1": int(roi.get("x1", 40)),
                    "y1": int(roi.get("y1", 40)),
                    "x2": int(roi.get("x2", 280)),
                    "y2": int(roi.get("y2", 180)),
                }
        return {"x1": 40, "y1": 40, "x2": 280, "y2": 180}

    def _save_profile_roi(self, profile_id: str, roi: dict[str, int]) -> None:
        try:
            profile = load_profile(profile_id, profiles_root=self.profiles_root)
        except (FileNotFoundError, OSError, ValueError):
            profile = create_default_template()
            profile.profile_id = profile_id
            profile.profile_name = profile_id.title()
        if profile.screens:
            profile.screens[0]["roi"] = dict(roi)
        else:
            profile.screens = [{"screen_class": "inventory", "roi": dict(roi), "rows": 8}]
        save_profile(profile, profiles_root=self.profiles_root)
