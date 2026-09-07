from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ScanHistory(ttk.Frame):
    def __init__(self, master: tk.Misc | None = None) -> None:
        super().__init__(master, padding=8)
        ttk.Label(self, text="Scan History").pack(anchor="w")
        self.listbox = tk.Listbox(self, exportselection=False, width=90, height=12)
        self.listbox.pack(fill="both", expand=True, pady=(8, 0))

    def set_scans(self, scans: list[dict[str, object]]) -> None:
        self.listbox.delete(0, tk.END)
        for scan in scans:
            self.listbox.insert(
                tk.END,
                f"{scan.get('date', '-') } | {scan.get('profile', '-') } | {scan.get('scope', '-') } | "
                f"obs={scan.get('observed', 0)} acc={scan.get('accepted', 0)} rev={scan.get('reviewed', 0)} "
                f"conf={scan.get('conflicted', 0)} continuity={scan.get('continuity_percentage', 0)}%",
            )

