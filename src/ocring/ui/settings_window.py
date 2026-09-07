from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from ocring.ocr.search_definition import SearchDefinition
from ocring.ocr.settings import (
    DEFAULT_SETTINGS_PATH,
    RecognitionSettings,
    ensure_output_workspace,
    load_settings,
    load_settings_payload,
    open_in_file_manager,
    save_settings,
    save_settings_payload,
)
from ocring.ui.hotkey import DEFAULT_SCAN_HOTKEY, event_to_hotkey, normalize_hotkey
from ocring.ui.theme import ACCENT, APP_BG, BORDER, SURFACE_ALT_BG, SURFACE_BG, TEXT, TEXT_MUTED, apply_modern_theme, apply_window_icon, load_logo_image


class SettingsWindow:
    def __init__(
        self,
        *,
        settings_path: Path = DEFAULT_SETTINGS_PATH,
        profile_id: str = "defiance",
        master: tk.Misc | None = None,
    ) -> None:
        self.settings_path = settings_path
        self.profile_id = profile_id
        self.root = master if master is not None else tk.Tk()
        self.root.title("OCRing Settings")
        if hasattr(self.root, "geometry"):
            self.root.geometry("860x560")
        apply_modern_theme(self.root)
        apply_window_icon(self.root)
        self._logo_image = load_logo_image(self.root, base_size=(42, 42))

        current = load_settings(path=self.settings_path)
        payload = self._load_payload()
        self.search_definition = SearchDefinition.load_active_profile(self.profile_id)
        self.recognition_mode_var = tk.StringVar(value=current.recognition_mode)
        self.api_escalation_var = tk.StringVar(value=current.api_escalation)
        self.privacy_var = tk.StringVar(value=current.privacy)
        self.review_mode_var = tk.StringVar(value=current.review_mode)
        self.output_root_var = tk.StringVar(value=current.output_root)
        self.scan_hotkey_var = tk.StringVar(value=str(payload.get("scan_hotkey") or DEFAULT_SCAN_HOTKEY))
        self.storage_note_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Ready.")
        self._capture_hotkey = False

        shell = ttk.Frame(self.root, padding=18, style="Surface.TFrame")
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        if hasattr(shell, "rowconfigure"):
            shell.rowconfigure(1, weight=1)

        header = ttk.Frame(shell, padding=(0, 0, 0, 14), style="Surface.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        if self._logo_image is not None:
            ttk.Label(header, image=self._logo_image, style="TLabel").grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 12))
        ttk.Label(header, text="Settings", style="Header.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(header, text="Recognition, privacy, search, and hotkey preferences.", style="Muted.TLabel").grid(row=1, column=1, sticky="w", pady=(4, 0))

        notebook = ttk.Notebook(shell)
        notebook.grid(row=1, column=0, sticky="nsew")

        frame = ttk.Frame(notebook, padding=18, style="Surface.TFrame")
        frame.columnconfigure(1, weight=1)
        if hasattr(notebook, "add"):
            notebook.add(frame, text="Recognition")

        ttk.Label(frame, text="Recognition Mode", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Combobox(
            frame,
            textvariable=self.recognition_mode_var,
            values=("Fast", "Balanced", "Accurate", "Offline", "Custom"),
            state="readonly",
        ).grid(row=0, column=1, sticky="ew", pady=6)

        ttk.Label(frame, text="API Escalation", style="Section.TLabel").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Combobox(
            frame,
            textvariable=self.api_escalation_var,
            values=("Never", "Ask me", "Automatically below confidence threshold"),
            state="readonly",
        ).grid(row=1, column=1, sticky="ew", pady=6)

        ttk.Label(frame, text="Privacy", style="Section.TLabel").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Combobox(
            frame,
            textvariable=self.privacy_var,
            values=("Send cropped regions only", "Never send full screen to API"),
            state="readonly",
        ).grid(row=2, column=1, sticky="ew", pady=6)

        ttk.Label(frame, text="Review Mode", style="Section.TLabel").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Combobox(
            frame,
            textvariable=self.review_mode_var,
            values=("Strict Manual Review", "Auto Store Verified/Stable"),
            state="readonly",
        ).grid(row=3, column=1, sticky="ew", pady=6)

        button_frame = ttk.Frame(frame, padding=(0, 12, 0, 0), style="Surface.TFrame")
        button_frame.grid(row=4, column=0, columnspan=2, sticky="ew")
        ttk.Button(button_frame, text="Save", command=self._save, style="Accent.TButton").pack(side="left", padx=4)
        ttk.Button(button_frame, text="Reload", command=self._reload).pack(side="left", padx=4)
        ttk.Label(frame, textvariable=self.status_var, style="Muted.TLabel").grid(row=5, column=0, columnspan=2, sticky="w", pady=(12, 0))

        search_frame = ttk.Frame(notebook, padding=18, style="Surface.TFrame")
        search_frame.columnconfigure(1, weight=1)
        if hasattr(notebook, "add"):
            notebook.add(search_frame, text="Search")
        ttk.Label(search_frame, text="Active Search Definition", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.search_text = tk.Text(
            search_frame,
            height=16,
            width=72,
            bg=SURFACE_BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            font=("Consolas", 10),
        )
        self.search_text.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(10, 0))

        hotkey_frame = ttk.Frame(notebook, padding=18, style="Surface.TFrame")
        hotkey_frame.columnconfigure(1, weight=1)
        if hasattr(notebook, "add"):
            notebook.add(hotkey_frame, text="Hotkeys")
        ttk.Label(hotkey_frame, text="Scan Toggle Hotkey", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=6)
        entry_class = getattr(ttk, "Entry", ttk.Combobox)
        self.hotkey_entry = entry_class(hotkey_frame, textvariable=self.scan_hotkey_var)
        self.hotkey_entry.grid(row=0, column=1, sticky="ew", pady=6)
        if hasattr(self.hotkey_entry, "bind"):
            self.hotkey_entry.bind("<FocusIn>", self._begin_hotkey_capture)
            self.hotkey_entry.bind("<KeyPress>", self._record_hotkey)
        ttk.Button(hotkey_frame, text="Use Default", command=self._reset_hotkey).grid(row=1, column=1, sticky="w", pady=(6, 0))
        ttk.Label(hotkey_frame, text="Click the field and press a key combination to rebind.", style="Muted.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 0))

        storage_frame = ttk.Frame(notebook, padding=18, style="Surface.TFrame")
        storage_frame.columnconfigure(1, weight=1)
        if hasattr(notebook, "add"):
            notebook.add(storage_frame, text="Storage")
        ttk.Label(storage_frame, text="Output Root", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=6)
        storage_entry_class = getattr(ttk, "Entry", ttk.Combobox)
        self.output_root_entry = storage_entry_class(storage_frame, textvariable=self.output_root_var)
        self.output_root_entry.grid(row=0, column=1, sticky="ew", pady=6)
        ttk.Button(storage_frame, text="Open Output Folder", command=self._open_output_folder, style="Accent.TButton").grid(row=1, column=1, sticky="w", pady=(6, 0))
        ttk.Label(
            storage_frame,
            text="Files are saved under export/, sessions/, and evidence/ inside the configured output root.",
            style="Muted.TLabel",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Label(storage_frame, textvariable=self.storage_note_var, style="Muted.TLabel").grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))

        self._refresh_storage_note()
        self._render_search_definition()

    def run(self) -> None:
        if hasattr(self.root, "mainloop"):
            self.root.mainloop()

    def _reload(self) -> None:
        current = load_settings(path=self.settings_path)
        payload = self._load_payload()
        self.search_definition = SearchDefinition.load_active_profile(self.profile_id)
        self.recognition_mode_var.set(current.recognition_mode)
        self.api_escalation_var.set(current.api_escalation)
        self.privacy_var.set(current.privacy)
        self.review_mode_var.set(current.review_mode)
        self.output_root_var.set(current.output_root)
        self.scan_hotkey_var.set(str(payload.get("scan_hotkey") or DEFAULT_SCAN_HOTKEY))
        self._refresh_storage_note()
        self._render_search_definition()
        self.status_var.set("Settings reloaded.")

    def _save(self) -> None:
        payload = self._load_payload()
        settings = RecognitionSettings(
            recognition_mode=self.recognition_mode_var.get(),
            api_escalation=self.api_escalation_var.get(),
            privacy=self.privacy_var.get(),
            review_mode=self.review_mode_var.get(),
            output_root=self.output_root_var.get(),
            window_geometry=str(payload.get("window_geometry") or load_settings(path=self.settings_path).window_geometry),
        )
        save_settings(settings, path=self.settings_path)
        payload["scan_hotkey"] = normalize_hotkey(self.scan_hotkey_var.get())
        save_settings_payload(payload, path=self.settings_path)
        self._refresh_storage_note()
        self.status_var.set(f"Saved settings to {self.settings_path}")
        if hasattr(messagebox, "showinfo"):
            messagebox.showinfo("OCRing Settings", f"Saved settings to {self.settings_path}")

    def _render_search_definition(self) -> None:
        self.search_text.delete("1.0", tk.END)
        lines = [
            f"searchable_fields: {list(self.search_definition.searchable_fields)}",
            f"quick_tabs: {list(self.search_definition.quick_tabs)}",
            f"filterable_fields: {list(self.search_definition.filterable_fields)}",
            f"sortable_fields: {list(self.search_definition.sortable_fields)}",
        ]
        for key, values in self.search_definition.suggestions.items():
            lines.append(f"{key}: {list(values)}")
        self.search_text.insert("1.0", "\n".join(lines))

    def _load_payload(self) -> dict[str, object]:
        return load_settings_payload(path=self.settings_path)

    def _begin_hotkey_capture(self, _event: object | None = None) -> None:
        self._capture_hotkey = True
        self.status_var.set("Press a key combination for the scan hotkey.")

    def _record_hotkey(self, event: object) -> str:
        if not self._capture_hotkey:
            return ""
        self.scan_hotkey_var.set(normalize_hotkey(event_to_hotkey(event)))
        self._capture_hotkey = False
        self.status_var.set(f"Captured hotkey {self.scan_hotkey_var.get()}.")
        return "break"

    def _reset_hotkey(self) -> None:
        self.scan_hotkey_var.set(DEFAULT_SCAN_HOTKEY)
        self.status_var.set("Scan hotkey reset to default.")

    def _open_output_folder(self) -> None:
        workspace = ensure_output_workspace(output_root=self.output_root_var.get(), path=self.settings_path)
        open_in_file_manager(workspace.root)
        self.status_var.set(f"Opened {workspace.root}")

    def _refresh_storage_note(self) -> None:
        workspace = ensure_output_workspace(output_root=self.output_root_var.get(), path=self.settings_path)
        self.storage_note_var.set(
            f"Storage: {workspace.root} | export: {workspace.export_dir.name} | sessions: {workspace.sessions_dir.name} | evidence: {workspace.evidence_dir.name}"
        )
