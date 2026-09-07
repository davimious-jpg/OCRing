from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ocring.ocr.review import ReviewRecord, ReviewStatus


RARITY_COLORS = {
    "Tier I": "#7f8c8d",
    "Tier II": "#27ae60",
    "Tier III": "#2980b9",
    "Tier IV": "#c0392b",
}

STATUS_COLORS = {
    ReviewStatus.PENDING: "#d4ac0d",
    ReviewStatus.ACCEPTED: "#1e8449",
    ReviewStatus.REJECTED: "#b03a2e",
    ReviewStatus.CORRECTED: "#2471a3",
    ReviewStatus.AUTO_SAVED: "#16a085",
}


def review_item_display_name(record: ReviewRecord) -> str:
    """Show unresolved identity as an exception state, not as an item named UNKNOWN."""
    item_name = str(record.fields.get("item_name", "")).strip()
    if not item_name or item_name.upper() == "UNKNOWN":
        return "Unresolved item"
    return item_name


class RecordCard(ttk.Frame):
    def __init__(self, master: tk.Misc | None = None, *, record: ReviewRecord | None = None) -> None:
        super().__init__(master, padding=8)
        self.columnconfigure(1, weight=1)
        self.item_name_var = tk.StringVar(value="")
        self.rarity_var = tk.StringVar(value="")
        self.type_var = tk.StringVar(value="")
        self.count_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="")

        ttk.Label(self, text="Item").grid(row=0, column=0, sticky="w")
        self.item_name_label = ttk.Label(self, textvariable=self.item_name_var)
        self.item_name_label.grid(row=0, column=1, sticky="w")

        ttk.Label(self, text="Rarity").grid(row=1, column=0, sticky="w")
        self.rarity_label = tk.Label(self, textvariable=self.rarity_var, padx=6, pady=2)
        self.rarity_label.grid(row=1, column=1, sticky="w")

        ttk.Label(self, text="Type").grid(row=2, column=0, sticky="w")
        ttk.Label(self, textvariable=self.type_var).grid(row=2, column=1, sticky="w")

        ttk.Label(self, text="Count").grid(row=3, column=0, sticky="w")
        ttk.Label(self, textvariable=self.count_var).grid(row=3, column=1, sticky="w")

        ttk.Label(self, text="Status").grid(row=4, column=0, sticky="w")
        self.status_label = tk.Label(self, textvariable=self.status_var, padx=6, pady=2)
        self.status_label.grid(row=4, column=1, sticky="w")

        if record is not None:
            self.set_record(record)

    def set_record(self, record: ReviewRecord) -> None:
        self.item_name_var.set(review_item_display_name(record))
        self.rarity_var.set(record.fields.get("item_rarity", ""))
        self.type_var.set(record.fields.get("item_type", ""))
        self.count_var.set(record.fields.get("item_count", ""))
        self.status_var.set(record.review_status)
        self.rarity_label.configure(bg=RARITY_COLORS.get(record.fields.get("item_rarity", ""), "#bdc3c7"))
        self.status_label.configure(bg=STATUS_COLORS.get(record.review_status, "#bdc3c7"))
