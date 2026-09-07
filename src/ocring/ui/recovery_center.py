from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from ocring.ocr.settings import DEFAULT_SETTINGS_PATH, ensure_output_workspace, open_in_file_manager
from ocring.ui.theme import ACCENT, APP_BG, BORDER, SURFACE_BG, TEXT, TEXT_MUTED


class RecoveryCenter(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc | None = None,
        *,
        sessions_root: Path | None = None,
        settings_path: Path = DEFAULT_SETTINGS_PATH,
    ) -> None:
        super().__init__(master, padding=18, style="Surface.TFrame")
        self.settings_path = settings_path
        self.sessions_root = sessions_root or ensure_output_workspace(path=self.settings_path).sessions_dir
        self._sessions: list[dict[str, object]] = []
        self.columnconfigure(0, weight=1)
        ttk.Label(self, text="Recovery Center", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(self, text="Resume, review, or discard interrupted sessions.", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 12))
        self.listbox = tk.Listbox(
            self,
            exportselection=False,
            width=100,
            height=12,
            bg=SURFACE_BG,
            fg=TEXT,
            selectbackground=ACCENT,
            selectforeground=APP_BG,
            highlightthickness=1,
            highlightbackground=BORDER,
            relief="flat",
            font=("Segoe UI", 11),
        )
        self.listbox.grid(row=2, column=0, sticky="nsew")
        button_frame = ttk.Frame(self, padding=(0, 12, 0, 0), style="Surface.TFrame")
        button_frame.grid(row=3, column=0, sticky="ew")
        for index, label in enumerate(("Resume", "Review Current Results", "Discard")):
            ttk.Button(button_frame, text=label, style="Accent.TButton" if label == "Resume" else "TButton").grid(row=0, column=index, padx=4, sticky="w")
        ttk.Button(button_frame, text="Show In Folder", command=self._show_selected_session_folder).grid(row=0, column=3, padx=4, sticky="w")

    def set_sessions(self, sessions: list[dict[str, object]]) -> None:
        self._sessions = list(sessions)
        self.listbox.delete(0, tk.END)
        for index, session in enumerate(sessions):
            self.listbox.insert(
                tk.END,
                f"{session.get('session_id', '-')}  •  captured={session.get('captured', 0)}  •  resolved={session.get('resolved', 0)}  •  pending={session.get('pending', 0)}  •  anchor={session.get('last_anchor', '-')}",
            )
            if hasattr(self.listbox, "itemconfig"):
                self.listbox.itemconfig(index, {"bg": SURFACE_BG, "fg": TEXT_MUTED})

    def _show_selected_session_folder(self) -> None:
        selection = self.listbox.curselection()
        if not selection:
            open_in_file_manager(self.sessions_root)
            return
        session = self._sessions[int(selection[0])]
        session_id = str(session.get("session_id") or "")
        if not session_id:
            open_in_file_manager(self.sessions_root)
            return
        session_dir = self.sessions_root / session_id
        open_in_file_manager(session_dir if session_dir.exists() else self.sessions_root)
