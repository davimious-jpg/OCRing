from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from ocring.ocr.export import Exporter, build_export_metadata, default_export_path
from ocring.ocr.inventory import InventoryStore
from ocring.ocr.search_engine import SearchEngine
from ocring.ocr.settings import DEFAULT_SETTINGS_PATH, ensure_output_workspace, open_in_file_manager
from .evidence_viewer import EvidenceViewer


class SearchPanel(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc | None = None,
        *,
        inventory_store: InventoryStore | None = None,
        settings_path: Path = DEFAULT_SETTINGS_PATH,
    ) -> None:
        super().__init__(master, padding=8)
        self.settings_path = settings_path
        self.workspace = ensure_output_workspace(path=self.settings_path)
        self.inventory_store = inventory_store or InventoryStore(self.workspace.inventory_db)
        self.search_engine = SearchEngine(self.inventory_store)
        self.exporter = Exporter()
        self.query_var = tk.StringVar(value="")
        self.autocomplete_var = tk.StringVar(value="")
        self.sort_var = tk.StringVar(value="")
        self.last_export_path: Path | None = None
        self.results = []
        self.quick_buttons: list[object] = []
        self.filter_vars: dict[str, tk.StringVar] = {}

        self.columnconfigure(1, weight=1)
        self.rowconfigure(4, weight=1)

        quick_frame = ttk.Frame(self)
        quick_frame.grid(row=0, column=0, columnspan=3, sticky="ew")
        for index, tab in enumerate(self.search_engine.search_definition.quick_tabs):
            button = ttk.Button(quick_frame, text=tab, command=lambda name=tab: self.run_quick_tab(name))
            button.grid(row=0, column=index, padx=2, pady=2)
            self.quick_buttons.append(button)

        ttk.Label(self, text="Search").grid(row=1, column=0, sticky="w")
        ttk.Entry(self, textvariable=self.query_var).grid(row=1, column=1, sticky="ew", padx=(4, 4))
        ttk.Button(self, text="Run", command=self.run_search).grid(row=1, column=2, sticky="ew")
        ttk.Label(self, textvariable=self.autocomplete_var).grid(row=2, column=1, sticky="w")

        self.smart_search_var = tk.StringVar(value="Needs Review")
        ttk.Label(self, text="Saved").grid(row=3, column=0, sticky="w")
        self.saved_combo = ttk.Combobox(
            self,
            textvariable=self.smart_search_var,
            values=[item.name for item in self.search_engine.list_saved_searches()],
            state="readonly",
        )
        self.saved_combo.grid(row=3, column=1, sticky="ew", padx=(4, 4))
        ttk.Button(self, text="Load", command=self.load_saved_search).grid(row=3, column=2, sticky="ew")

        filter_frame = ttk.Frame(self)
        filter_frame.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        for index, field_name in enumerate(self.search_engine.search_definition.filterable_fields):
            label = field_name.replace("item_", "").replace("_", " ").title()
            ttk.Label(filter_frame, text=label).grid(row=0, column=index * 2, sticky="w")
            var = tk.StringVar(value="")
            values = self.search_engine.search_definition.suggestions.get(field_name, ())
            ttk.Combobox(filter_frame, textvariable=var, values=list(values), state="readonly").grid(row=0, column=index * 2 + 1, sticky="ew", padx=2)
            self.filter_vars[field_name] = var
        ttk.Label(filter_frame, text="Sort").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(
            filter_frame,
            textvariable=self.sort_var,
            values=list(self.search_engine.search_definition.sortable_fields),
            state="readonly",
        ).grid(row=1, column=1, sticky="ew", padx=2, pady=(6, 0))

        self.result_list = tk.Listbox(self, exportselection=False)
        self.result_list.grid(row=5, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        self.result_list.bind("<<ListboxSelect>>", self._on_select)

        action_frame = ttk.Frame(self)
        action_frame.grid(row=5, column=2, sticky="ns", padx=(8, 0))
        ttk.Button(action_frame, text="Export CSV", command=self.export_csv).pack(fill="x", pady=2)
        ttk.Button(action_frame, text="Export JSON", command=self.export_json).pack(fill="x", pady=2)
        ttk.Button(action_frame, text="Show In Folder", command=self.show_last_export_in_folder).pack(fill="x", pady=2)

        self.evidence_viewer = EvidenceViewer(self)
        self.evidence_viewer.grid(row=6, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        if hasattr(self.query_var, "trace_add"):
            self.query_var.trace_add("write", self._update_autocomplete)

    def run_search(self) -> None:
        filters = {key: variable.get() for key, variable in self.filter_vars.items() if variable.get()}
        self.results = self.search_engine.search(self.query_var.get(), filters)
        if self.sort_var.get():
            sort_key = self.sort_var.get()
            reverse = sort_key == "recently_added"
            self.results = sorted(
                self.results,
                key=lambda record: record.added_order if sort_key == "recently_added" else record.fields.get(sort_key, ""),
                reverse=reverse,
            )
        self.result_list.delete(0, tk.END)
        for record in self.results:
            self.result_list.insert(tk.END, f"{record.fields.get('item_name', '')} | {record.fields.get('item_rarity', '')}")

    def load_saved_search(self) -> None:
        search = self.search_engine.load_search(self.smart_search_var.get())
        self.query_var.set(search.query)
        self.results = self.search_engine.search(search.query, search.filters)
        self.result_list.delete(0, tk.END)
        for record in self.results:
            self.result_list.insert(tk.END, f"{record.fields.get('item_name', '')} | {record.fields.get('item_rarity', '')}")

    def run_quick_tab(self, tab_name: str) -> None:
        query = self.search_engine.quick_tab_query(tab_name)
        self.query_var.set(query.query)
        for key, variable in self.filter_vars.items():
            variable.set(str(query.filters.get(key) or ""))
        self.run_search()

    def export_csv(self) -> None:
        if not self.results:
            return
        suggested = default_export_path("csv", session_id=self.results[0].session_id if self.results else "search", settings_path=self.settings_path)
        output = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialdir=str(self.workspace.export_dir),
            initialfile=suggested.name,
        )
        if not output:
            return
        metadata = build_export_metadata(session_id=self.results[0].session_id if self.results else "search")
        self.last_export_path = self.exporter.export_csv(self.results, Path(output), metadata=metadata)

    def export_json(self) -> None:
        if not self.results:
            return
        suggested = default_export_path("json", session_id=self.results[0].session_id if self.results else "search", settings_path=self.settings_path)
        output = filedialog.asksaveasfilename(
            defaultextension=".json",
            initialdir=str(self.workspace.export_dir),
            initialfile=suggested.name,
        )
        if not output:
            return
        metadata = build_export_metadata(session_id=self.results[0].session_id if self.results else "search")
        self.last_export_path = self.exporter.export_json(self.results, Path(output), metadata=metadata)

    def show_last_export_in_folder(self) -> None:
        target = self.last_export_path.parent if self.last_export_path is not None else self.workspace.export_dir
        open_in_file_manager(target)

    def _on_select(self, event: object | None = None) -> None:
        del event
        selection = self.result_list.curselection()
        if not selection:
            return
        record = self.results[int(selection[0])]
        support_summary = {
            key: {"source_crop_ids": []}
            for key in record.fields
        }
        fake_record = type(
            "SearchRecord",
            (),
            {
                "source_frame_ids": [record.session_id],
                "source_row_ids": [record.record_id],
                "overlap_provenance": {},
                "support_summary": support_summary,
            },
        )()
        self.evidence_viewer.set_record(fake_record, session_dir=None)

    def _update_autocomplete(self, *args: object) -> None:
        del args
        suggestions = self.search_engine.suggest(self.query_var.get())
        self.autocomplete_var.set(", ".join(suggestions[:5]))
