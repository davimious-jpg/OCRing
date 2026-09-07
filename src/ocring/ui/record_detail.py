from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class RecordDetail(ttk.Frame):
    def __init__(self, master: tk.Misc | None = None) -> None:
        super().__init__(master, padding=8)
        ttk.Label(self, text="Record Detail").grid(row=0, column=0, sticky="w")
        self.summary = tk.Text(self, width=70, height=12)
        self.summary.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        button_frame = ttk.Frame(self)
        button_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        for index, label in enumerate(("VIEW EVIDENCE", "EDIT", "HISTORY")):
            ttk.Button(button_frame, text=label).grid(row=0, column=index, padx=4)

    def set_record(self, payload: dict[str, object]) -> None:
        self.summary.delete("1.0", tk.END)
        lines = [
            f"Name: {payload.get('item_name', '-')}",
            f"Type: {payload.get('item_type', '-')}",
            f"Rarity: {payload.get('item_rarity', '-')}",
            f"Tier: {payload.get('tier', payload.get('item_rarity', '-'))}",
            f"Count: {payload.get('item_count', '-')}",
            f"Verified: {payload.get('verified_status', '-')}",
            f"Source: {payload.get('source', '-')}",
            "",
            "Correctness Breakdown:",
            f"OCR: {payload.get('ocr_score', '-')}",
            f"Dictionary: {payload.get('dictionary_score', '-')}",
            f"Temporal: {payload.get('temporal_score', '-')}",
            f"Profile: {payload.get('profile_score', '-')}",
            f"Contradictions: {payload.get('contradictions', '-')}",
        ]
        self.summary.insert("1.0", "\n".join(lines))

