from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class BackupUI(ttk.Frame):
    COMPONENTS = (
        "Inventory",
        "Profiles",
        "Correction Rules",
        "Saved Searches",
        "Settings",
        "Evidence Images",
        "Scan History",
    )

    def __init__(self, master: tk.Misc | None = None) -> None:
        super().__init__(master, padding=18, style="Surface.TFrame")
        ttk.Label(self, text="Backup / Restore", style="Header.TLabel").pack(anchor="w")
        ttk.Label(self, text="Choose which local OCRing artifacts should be included in a backup set.", style="Muted.TLabel").pack(anchor="w", pady=(4, 12))
        checklist = ttk.Frame(self, padding=12, style="AltSurface.TFrame")
        checklist.pack(fill="both", expand=True)
        self.vars = {name: tk.BooleanVar(value=True) for name in self.COMPONENTS}
        for name, variable in self.vars.items():
            ttk.Checkbutton(checklist, text=name, variable=variable).pack(anchor="w", pady=3)
        button_frame = ttk.Frame(self, padding=(0, 12, 0, 0), style="Surface.TFrame")
        button_frame.pack(fill="x")
        ttk.Button(button_frame, text="Create Backup", style="Accent.TButton").pack(side="left", padx=4)
        ttk.Button(button_frame, text="Import Backup (with diff preview)").pack(side="left", padx=4)
