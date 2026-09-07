from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class DiffView(ttk.Frame):
    def __init__(self, master: tk.Misc | None = None) -> None:
        super().__init__(master, padding=8)
        ttk.Label(self, text="Inventory Diff").pack(anchor="w")
        self.text = tk.Text(self, width=80, height=16)
        self.text.pack(fill="both", expand=True, pady=(8, 0))

    def set_diff(self, diff: dict[str, list[str]]) -> None:
        self.text.delete("1.0", tk.END)
        lines = []
        for symbol, title in (("+", "New"), ("-", "Missing"), ("~", "Changed"), ("?", "Unresolved")):
            lines.append(f"{symbol} {title}")
            lines.extend(f"  {item}" for item in diff.get(symbol, []))
        self.text.insert("1.0", "\n".join(lines))

