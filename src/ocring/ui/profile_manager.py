from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ocring.ocr.profile import Profile
from ocring.ocr.profile_capabilities import ProfileCapabilities
from ocring.ui.theme import ACCENT, APP_BG, BORDER, SUCCESS, SURFACE_BG, TEXT, TEXT_MUTED


class ProfileManager(ttk.Frame):
    def __init__(self, master: tk.Misc | None = None) -> None:
        super().__init__(master, padding=18, style="Surface.TFrame")
        self.columnconfigure(0, weight=1)
        ttk.Label(self, text="Profile Manager", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(self, text="Manage local game profiles and capability coverage.", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 12))
        self.listbox = tk.Listbox(
            self,
            exportselection=False,
            width=90,
            height=14,
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
        for index, label in enumerate(("Add Profile", "Duplicate", "Edit", "Test", "Export")):
            ttk.Button(button_frame, text=label, style="Accent.TButton" if label == "Add Profile" else "TButton").grid(row=0, column=index, padx=4, sticky="w")

    def set_profiles(self, profiles: list[Profile]) -> None:
        self.listbox.delete(0, tk.END)
        for index, profile in enumerate(profiles):
            capabilities = ProfileCapabilities.for_profile(profile.profile_id)
            self.listbox.insert(
                tk.END,
                f"{profile.profile_name} ({profile.profile_id})  •  inventory={capabilities.inventory_scan.value}  •  full={capabilities.full_inventory_completeness.value}",
            )
            if hasattr(self.listbox, "itemconfig"):
                self.listbox.itemconfig(index, {"bg": SURFACE_BG, "fg": SUCCESS if capabilities.inventory_scan.value else TEXT_MUTED})
