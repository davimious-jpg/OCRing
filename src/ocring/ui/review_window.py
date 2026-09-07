from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from ocring.ocr.review import ReviewSession, load_review_session_from_store
from ocring.ui.theme import ACCENT, APP_BG, BORDER, DANGER, SUCCESS, SURFACE_ALT_BG, SURFACE_BG, TEXT, TEXT_MUTED, WARNING, apply_modern_theme, apply_window_icon
from .evidence_viewer import EvidenceViewer
from .record_card import RecordCard, review_item_display_name


class ReviewWindow:
    @classmethod
    def load_session(
        cls,
        session_id: str,
        *,
        sessions_root: Path,
        master: tk.Misc | None = None,
    ) -> "ReviewWindow":
        review_session = load_review_session_from_store(session_id, sessions_root=sessions_root)
        return cls(review_session, sessions_root=sessions_root, master=master)

    def __init__(
        self,
        review_session: ReviewSession,
        *,
        sessions_root: Path,
        master: tk.Misc | None = None,
    ) -> None:
        self.review_session = review_session
        self.sessions_root = sessions_root
        self.root = master if master is not None else tk.Tk()
        if hasattr(self.root, "title"):
            self.root.title(f"OCRing Review — Session {review_session.session_id}")
        if hasattr(self.root, "geometry"):
            self.root.geometry("1060x700")
        apply_modern_theme(self.root)
        apply_window_icon(self.root)
        try:
            self.root.configure(bg=APP_BG)
        except Exception:
            pass

        self.selected_record_id: str | None = None
        self._selection_guard = False

        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=3)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, padding=(18, 18, 18, 10), style="Surface.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Review Queue", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text=f"Session {review_session.session_id} — exception review with provenance preserved.", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.summary_var = tk.StringVar(value=self._summary_text())
        ttk.Label(header, textvariable=self.summary_var, style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(4, 0))

        left_frame = ttk.Frame(self.root, padding=16, style="Surface.TFrame")
        left_frame.grid(row=1, column=0, sticky="nsew", padx=(18, 10), pady=(0, 18))
        left_frame.rowconfigure(1, weight=1)
        left_frame.columnconfigure(0, weight=1)

        ttk.Label(left_frame, text="Candidate Records", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.record_list = tk.Listbox(
            left_frame,
            exportselection=False,
            bg=SURFACE_BG,
            fg=TEXT,
            selectbackground=ACCENT,
            selectforeground=APP_BG,
            highlightthickness=1,
            highlightbackground=BORDER,
            relief="flat",
            font=("Segoe UI", 11),
        )
        self.record_list.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self.record_list.bind("<<ListboxSelect>>", self._on_select)

        right_frame = ttk.Frame(self.root, padding=16, style="AltSurface.TFrame")
        right_frame.grid(row=1, column=1, sticky="nsew", padx=(0, 18), pady=(0, 18))
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(2, weight=1)

        self.record_card = RecordCard(right_frame)
        self.record_card.grid(row=0, column=0, sticky="ew")

        self.status_badge = tk.Label(
            right_frame,
            text="PENDING",
            bg=SURFACE_ALT_BG,
            fg=WARNING,
            padx=12,
            pady=6,
            font=("Segoe UI Semibold", 11),
        )
        self.status_badge.grid(row=1, column=0, sticky="w", pady=(10, 10))

        self.evidence_viewer = EvidenceViewer(right_frame)
        self.evidence_viewer.grid(row=2, column=0, sticky="nsew")

        button_frame = ttk.Frame(right_frame, padding=(0, 12, 0, 0), style="AltSurface.TFrame")
        button_frame.grid(row=3, column=0, sticky="ew")
        ttk.Button(button_frame, text="Accept", command=self._accept_selected, style="Accent.TButton").pack(side="left", padx=4)
        ttk.Button(button_frame, text="Reject", command=self._reject_selected).pack(side="left", padx=4)
        ttk.Button(button_frame, text="Correct", command=self._correct_selected).pack(side="left", padx=4)
        ttk.Button(button_frame, text="Commit Inventory", command=self._commit_inventory, style="Accent.TButton").pack(side="right", padx=4)

        self._populate_records()

    def run(self) -> None:
        if hasattr(self.root, "mainloop"):
            self.root.mainloop()

    def _populate_records(self) -> None:
        def update() -> None:
            self.record_list.delete(0, tk.END)
            self.summary_var.set(self._summary_text())
            for index, record in enumerate(self.review_session.records):
                label = f"{review_item_display_name(record)}  •  {record.fields.get('item_rarity', '')}  •  {record.review_status}"
                self.record_list.insert(tk.END, label)
                if hasattr(self.record_list, "itemconfig"):
                    self.record_list.itemconfig(index, {"bg": SURFACE_BG, "fg": self._status_fg(record.review_status)})
            if self.review_session.records:
                self.record_list.selection_set(0)
                self._select_record(self.review_session.records[0].record_id)

        self._run_on_ui_thread(update)

    def _on_select(self, event: object | None = None) -> None:
        del event
        if self._selection_guard:
            return
        selection = self.record_list.curselection()
        if not selection:
            return
        record = self.review_session.records[int(selection[0])]
        if record.record_id == self.selected_record_id:
            return
        self._select_record(record.record_id)

    def _select_record(self, record_id: str) -> None:
        def update() -> None:
            self.selected_record_id = record_id
            record = self.review_session.get_record(record_id)
            self.record_card.set_record(record)
            self.status_badge.configure(text=record.review_status, fg=self._status_fg(record.review_status))
            self.evidence_viewer.set_record(record, session_dir=self.sessions_root / self.review_session.session_id)

        self._run_on_ui_thread(update)

    def _accept_selected(self) -> None:
        if self.selected_record_id is None:
            return
        self.review_session.accept_record(self.selected_record_id)
        self._refresh()

    def _reject_selected(self) -> None:
        if self.selected_record_id is None:
            return
        self.review_session.reject_record(self.selected_record_id)
        self._refresh()

    def _correct_selected(self) -> None:
        if self.selected_record_id is None:
            return
        record = self.review_session.get_record(self.selected_record_id)
        field = simpledialog.askstring("Correct Field", "Field to edit (e.g. item_name):", parent=self.root)
        if not field:
            return
        current = record.fields.get(field, "")
        new_value = simpledialog.askstring("Correct Value", f"New value for {field}:", initialvalue=current, parent=self.root)
        if new_value is None:
            return
        self.review_session.correct_field(self.selected_record_id, field, new_value)
        self._refresh()

    def _commit_inventory(self) -> None:
        sqlite_path = self.sessions_root / "review_inventory.db"
        count = self.review_session.commit_to_sqlite(sqlite_path)
        self._run_on_ui_thread(lambda: messagebox.showinfo("OCRing Review", f"Committed {count} records to {sqlite_path}"))

    def _refresh(self) -> None:
        def update() -> None:
            current_id = self.selected_record_id
            self._selection_guard = True
            try:
                self._populate_records()
                if current_id is not None:
                    for index, record in enumerate(self.review_session.records):
                        if record.record_id == current_id:
                            self.record_list.selection_clear(0, tk.END)
                            self.record_list.selection_set(index)
                            self._select_record(current_id)
                            break
            finally:
                self._selection_guard = False

        self._run_on_ui_thread(update)

    def _status_fg(self, status: str) -> str:
        if status == "ACCEPTED":
            return SUCCESS
        if status == "REJECTED":
            return DANGER
        if status == "CORRECTED":
            return ACCENT
        if status == "AUTO_SAVED":
            return SUCCESS
        return WARNING

    def _summary_text(self) -> str:
        summary = self.review_session.get_review_summary()
        return (
            f"Auto saved: {summary.get('automatically_stored', 0)}  •  "
            f"Needs review: {summary.get('needs_manual_review', 0)}  •  "
            f"Held/unknown: {summary.get('hold_unknown', 0)}"
        )

    def _run_on_ui_thread(self, callback) -> None:
        if hasattr(self.root, "after"):
            self.root.after(0, callback)
            return
        callback()
