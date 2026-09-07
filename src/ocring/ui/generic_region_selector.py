from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from ocring.ocr.generic_profile import GenericProfile, create_generic_profile, save_generic_profile
from ocring.ocr.profile import DEFAULT_PROFILES_ROOT


class GenericRegionSelectorWindow:
    def __init__(
        self,
        *,
        profiles_root: Path = DEFAULT_PROFILES_ROOT,
        master: tk.Misc | None = None,
        on_save: callable | None = None,
    ) -> None:
        self.profiles_root = profiles_root
        self.on_save = on_save
        self.root = master if master is not None else tk.Tk()
        self.root.title("OCRing Generic Region Selector")
        if hasattr(self.root, "geometry"):
            self.root.geometry("980x680")

        self.profile_name_var = tk.StringVar(value="Generic Game Profile")
        self.scan_scope_var = tk.StringVar(value="FULL_INVENTORY")
        self.status_var = tk.StringVar(value="Define a region and fields.")
        self.region_vars = {
            "x1": tk.StringVar(value="0"),
            "y1": tk.StringVar(value="0"),
            "x2": tk.StringVar(value="1920"),
            "y2": tk.StringVar(value="1080"),
        }

        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=2)
        self.root.rowconfigure(0, weight=1)

        left = ttk.Frame(self.root, padding=8)
        left.grid(row=0, column=0, sticky="nsew")
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        ttk.Label(left, text="Available Windows").grid(row=0, column=0, sticky="w")
        self.window_list = tk.Listbox(left, exportselection=False)
        self.window_list.grid(row=1, column=0, sticky="nsew")
        for item in self.list_available_windows():
            self.window_list.insert(tk.END, item)
        if hasattr(self.window_list, "selection_set"):
            self.window_list.selection_set(0)

        right = ttk.Frame(self.root, padding=8)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(1, weight=1)

        ttk.Label(right, text="Profile Name").grid(row=0, column=0, sticky="w")
        ttk.Entry(right, textvariable=self.profile_name_var).grid(row=0, column=1, sticky="ew", pady=2)

        ttk.Label(right, text="Scan Scope").grid(row=1, column=0, sticky="w")
        ttk.Entry(right, textvariable=self.scan_scope_var).grid(row=1, column=1, sticky="ew", pady=2)

        ttk.Label(right, text="Region ROI").grid(row=2, column=0, sticky="nw", pady=(8, 0))
        region_frame = ttk.Frame(right)
        region_frame.grid(row=2, column=1, sticky="ew", pady=(8, 0))
        for index, key in enumerate(("x1", "y1", "x2", "y2")):
            ttk.Label(region_frame, text=key.upper()).grid(row=0, column=index * 2, sticky="w")
            ttk.Entry(region_frame, textvariable=self.region_vars[key], width=8).grid(row=0, column=index * 2 + 1, sticky="w", padx=(0, 6))

        ttk.Label(right, text="Field Definitions").grid(row=3, column=0, sticky="nw", pady=(8, 0))
        self.fields_text = tk.Text(right, height=10, width=60)
        self.fields_text.grid(row=3, column=1, sticky="nsew", pady=(8, 0))
        self.fields_text.insert(
            "1.0",
            json.dumps(
                [
                    {"field_name": "name", "field_type": "text", "field_source": "row 1"},
                    {"field_name": "count", "field_type": "number", "field_source": "crop 2"},
                ],
                indent=2,
            ),
        )

        ttk.Label(right, text="Region Preview").grid(row=4, column=0, sticky="nw", pady=(8, 0))
        self.preview_text = tk.Text(right, height=6, width=60)
        self.preview_text.grid(row=4, column=1, sticky="nsew", pady=(8, 0))
        self.preview_text.insert("1.0", "Preview pending. Select a window and define ROI bounds.")

        button_frame = ttk.Frame(right)
        button_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(button_frame, text="Save Generic Profile", command=self._save_generic_profile).pack(side="left", padx=4)
        ttk.Button(button_frame, text="Cancel", command=self._cancel).pack(side="left", padx=4)
        ttk.Button(button_frame, text="Test OCR on Region", command=self._test_ocr_on_region).pack(side="left", padx=4)

        ttk.Label(right, textvariable=self.status_var).grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def run(self) -> None:
        if hasattr(self.root, "mainloop"):
            self.root.mainloop()

    def list_available_windows(self) -> list[str]:
        return ["Desktop Capture", "Game Window", "Preview Surface"]

    def _save_generic_profile(self) -> GenericProfile | None:
        try:
            profile = create_generic_profile(
                self.profile_name_var.get(),
                self._get_region_tuple(),
                self._get_fields(),
                scan_scope=self.scan_scope_var.get().strip() or "FULL_INVENTORY",
            )
        except ValueError as error:
            messagebox.showerror("OCRing Generic Mode", str(error))
            self.status_var.set("Generic profile form is invalid.")
            return None
        save_generic_profile(profile, profiles_root=self.profiles_root)
        self.status_var.set(f"Saved generic profile {profile.profile_id}")
        if callable(self.on_save):
            self.on_save(profile)
        return profile

    def _cancel(self) -> None:
        if hasattr(self.root, "destroy"):
            self.root.destroy()

    def _test_ocr_on_region(self) -> None:
        preview = {
            "window": self._selected_window_name(),
            "region_roi": {
                "x1": self.region_vars["x1"].get(),
                "y1": self.region_vars["y1"].get(),
                "x2": self.region_vars["x2"].get(),
                "y2": self.region_vars["y2"].get(),
            },
            "raw_text": [field["field_name"] for field in self._get_fields()],
        }
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert("1.0", json.dumps(preview, indent=2))
        self.status_var.set("Generic OCR preview updated.")

    def _selected_window_name(self) -> str:
        selection = self.window_list.curselection()
        if not selection:
            return self.list_available_windows()[0]
        index = int(selection[0])
        windows = self.list_available_windows()
        if index >= len(windows):
            return windows[0]
        return windows[index]

    def _get_region_tuple(self) -> tuple[int, int, int, int]:
        try:
            x1 = int(self.region_vars["x1"].get())
            y1 = int(self.region_vars["y1"].get())
            x2 = int(self.region_vars["x2"].get())
            y2 = int(self.region_vars["y2"].get())
        except ValueError as error:
            raise ValueError("Region ROI must contain integer coordinates.") from error
        if x2 <= x1 or y2 <= y1:
            raise ValueError("Region ROI must define a positive area.")
        return (x1, y1, x2, y2)

    def _get_fields(self) -> list[dict[str, str]]:
        raw = self.fields_text.get("1.0", tk.END).strip()
        if not raw:
            return []
        try:
            fields = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(f"Field definitions contain invalid JSON: {error.msg}") from error
        if not isinstance(fields, list):
            raise ValueError("Field definitions must be a JSON list.")
        normalized: list[dict[str, str]] = []
        for item in fields[:5]:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "field_name": str(item.get("field_name") or "").strip(),
                    "field_type": str(item.get("field_type") or "text").strip(),
                    "field_source": str(item.get("field_source") or "").strip(),
                }
            )
        return normalized
