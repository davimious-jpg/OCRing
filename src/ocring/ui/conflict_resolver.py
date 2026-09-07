from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ConflictResolver(ttk.Frame):
    def __init__(self, master: tk.Misc | None = None) -> None:
        super().__init__(master, padding=8)
        ttk.Label(self, text="Conflict Resolver").pack(anchor="w")
        self.conflict_text = tk.Text(self, width=80, height=8)
        self.conflict_text.pack(fill="both", expand=True, pady=(8, 0))
        button_frame = ttk.Frame(self)
        button_frame.pack(fill="x", pady=(8, 0))
        for label in ("Trust Text", "Trust Color", "Edit", "Leave Unresolved"):
            ttk.Button(button_frame, text=label).pack(side="left", padx=4)

    def set_conflict(self, description: str) -> None:
        self.conflict_text.delete("1.0", tk.END)
        self.conflict_text.insert("1.0", description)

