from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from ocring.ocr.review import ReviewRecord


class EvidenceViewer(ttk.Frame):
    def __init__(self, master: tk.Misc | None = None) -> None:
        super().__init__(master, padding=8)
        ttk.Label(self, text="Evidence").pack(anchor="w")
        self.text = tk.Text(self, width=60, height=14)
        self.text.pack(fill="both", expand=True)
        self.thumbnail_frame = ttk.Frame(self)
        self.thumbnail_frame.pack(fill="x", expand=False)
        self._images: list[tk.PhotoImage] = []

    def set_record(self, record: ReviewRecord, *, session_dir: Path | None = None) -> None:
        self.text.delete("1.0", tk.END)
        fields = getattr(record, "fields", {})
        reasons = getattr(record, "reasons", [])
        lines = [
            f"Best Crop: {self._best_crop(record) or '-'}",
            f"Raw OCR: {self._raw_ocr(record) or '-'}",
            f"Resolved Value: {self._resolved_value(fields) or '-'}",
            f"Frames: {', '.join(record.source_frame_ids) or '-'}",
            f"Rows: {', '.join(record.source_row_ids) or '-'}",
            f"Overlap: {record.overlap_provenance or {}}",
            f"Supporting Observations: {self._supporting_observations(record)}",
            f"Why Accepted/Reviewed: {', '.join(str(reason) for reason in reasons) or '-'}",
        ]
        crop_ids: list[str] = []
        for summary in record.support_summary.values():
            crop_ids.extend(str(value) for value in summary.get("source_crop_ids", []))
        unique_crop_ids = list(dict.fromkeys(crop_ids))
        lines.append(f"Crop IDs: {', '.join(unique_crop_ids) or '-'}")
        self.text.insert("1.0", "\n".join(lines))
        self._render_thumbnails(unique_crop_ids, session_dir=session_dir)

    def _render_thumbnails(self, crop_ids: list[str], *, session_dir: Path | None) -> None:
        for child in self.thumbnail_frame.winfo_children():
            child.destroy()
        self._images.clear()
        if session_dir is None:
            return
        for crop_id in crop_ids[:4]:
            image_path = session_dir / f"{crop_id}.png"
            if not image_path.exists():
                continue
            try:
                image = tk.PhotoImage(file=str(image_path))
            except tk.TclError:
                continue
            self._images.append(image)
            ttk.Label(self.thumbnail_frame, image=image, text=crop_id, compound="top").pack(side="left", padx=4)

    def _best_crop(self, record: ReviewRecord) -> str:
        for summary in record.support_summary.values():
            crop_ids = [str(value) for value in summary.get("source_crop_ids", []) if str(value).strip()]
            if crop_ids:
                return crop_ids[0]
        return ""

    def _raw_ocr(self, record: ReviewRecord) -> str:
        overlap = getattr(record, "overlap_provenance", {})
        reconstruction = overlap.get("reconstruction_provenance", {}) if isinstance(overlap, dict) else {}
        fragments = reconstruction.get("repaired_fragments", [])
        if fragments:
            return " ".join(str(item) for item in fragments)
        return ""

    def _resolved_value(self, fields: dict[str, str]) -> str:
        if not isinstance(fields, dict):
            return ""
        return ", ".join(f"{key}={value}" for key, value in fields.items() if str(value).strip())

    def _supporting_observations(self, record: ReviewRecord) -> str:
        total = 0
        for summary in record.support_summary.values():
            total += int(summary.get("support_count", 0))
        return str(total)
