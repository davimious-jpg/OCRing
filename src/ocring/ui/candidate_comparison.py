from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class CandidateComparison(ttk.Frame):
    def __init__(self, master: tk.Misc | None = None) -> None:
        super().__init__(master, padding=8)
        ttk.Label(self, text="Candidate Comparison").pack(anchor="w")
        self.listbox = tk.Listbox(self, exportselection=False, width=80, height=10)
        self.listbox.pack(fill="both", expand=True, pady=(8, 0))
        button_frame = ttk.Frame(self)
        button_frame.pack(fill="x", pady=(8, 0))
        for label in ("Select Candidate", "Enter Manually", "Unknown"):
            ttk.Button(button_frame, text=label).pack(side="left", padx=4)

    def set_candidates(self, candidates: list[dict[str, object]]) -> None:
        self.listbox.delete(0, tk.END)
        for candidate in candidates:
            self.listbox.insert(
                tk.END,
                f"{candidate.get('value', '-') } | score={candidate.get('score', '-') } | evidence={candidate.get('evidence', '-')}",
            )

