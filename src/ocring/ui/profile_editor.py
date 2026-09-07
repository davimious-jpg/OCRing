from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ocring.ocr.generic_profile import GenericProfile
from ocring.ocr.profile_package import ProfilePackage
from ocring.ocr.profile import (
    DEFAULT_PROFILES_ROOT,
    Profile,
    create_default_template,
    delete_profile,
    list_profiles,
    save_profile,
)
from ocring.ocr.profile_validator import validate_profile
from .generic_region_selector import GenericRegionSelectorWindow


class ProfileEditorWindow:
    def __init__(self, *, profiles_root: Path = DEFAULT_PROFILES_ROOT, master: tk.Misc | None = None) -> None:
        self.profiles_root = profiles_root
        self.root = master if master is not None else tk.Tk()
        self.root.title("OCRing Profile Editor — Profiles")
        if hasattr(self.root, "geometry"):
            self.root.geometry("1100x720")

        self.profiles_root.mkdir(parents=True, exist_ok=True)
        self.selected_profile_id: str | None = None
        self.validation_cache: dict[str, list[str]] = {}

        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=3)
        self.root.rowconfigure(0, weight=1)

        left_frame = ttk.Frame(self.root, padding=8)
        left_frame.grid(row=0, column=0, sticky="nsew")
        left_frame.rowconfigure(1, weight=1)
        left_frame.columnconfigure(0, weight=1)

        ttk.Label(left_frame, text="Profiles").grid(row=0, column=0, sticky="w")
        self.profile_list = tk.Listbox(left_frame, exportselection=False)
        self.profile_list.grid(row=1, column=0, sticky="nsew")
        self.profile_list.bind("<<ListboxSelect>>", self._on_select)

        right_frame = ttk.Frame(self.root, padding=8)
        right_frame.grid(row=0, column=1, sticky="nsew")
        right_frame.columnconfigure(1, weight=1)

        self.profile_id_var = tk.StringVar(value="")
        self.profile_name_var = tk.StringVar(value="")
        self.version_var = tk.StringVar(value="")

        ttk.Label(right_frame, text="Profile ID").grid(row=0, column=0, sticky="w")
        ttk.Entry(right_frame, textvariable=self.profile_id_var, state="readonly").grid(row=0, column=1, sticky="ew", pady=2)

        ttk.Label(right_frame, text="Profile Name").grid(row=1, column=0, sticky="w")
        ttk.Entry(right_frame, textvariable=self.profile_name_var).grid(row=1, column=1, sticky="ew", pady=2)

        ttk.Label(right_frame, text="Version").grid(row=2, column=0, sticky="w")
        ttk.Entry(right_frame, textvariable=self.version_var).grid(row=2, column=1, sticky="ew", pady=2)

        self.inventory_text = self._build_text_field(right_frame, 3, "Inventory Definitions")
        self.screens_text = self._build_text_field(right_frame, 4, "Screens")
        self.parsing_rules_text = self._build_text_field(right_frame, 5, "Parsing Rules")
        self.rarity_rules_text = self._build_text_field(right_frame, 6, "Rarity Rules")
        self.compatibility_rules_text = self._build_text_field(right_frame, 7, "Compatibility Rules")

        button_frame = ttk.Frame(right_frame)
        button_frame.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(button_frame, text="Import Profile", command=self._import_profile).pack(side="left", padx=4)
        ttk.Button(button_frame, text="New Profile", command=self._new_profile).pack(side="left", padx=4)
        ttk.Button(button_frame, text="Create Generic Profile", command=self._open_generic_profile_selector).pack(side="left", padx=4)
        ttk.Button(button_frame, text="Save", command=self._save_selected).pack(side="left", padx=4)
        ttk.Button(button_frame, text="Export Profile", command=self._export_selected).pack(side="left", padx=4)
        ttk.Button(button_frame, text="Validate", command=self._validate_selected).pack(side="left", padx=4)
        ttk.Button(button_frame, text="Delete", command=self._delete_selected).pack(side="left", padx=4)

        self.status_var = tk.StringVar(value="No profile selected.")
        ttk.Label(right_frame, textvariable=self.status_var).grid(row=9, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self._reload_profiles(select_first=True)

    def run(self) -> None:
        if hasattr(self.root, "mainloop"):
            self.root.mainloop()

    def _build_text_field(self, parent: object, row: int, label: str) -> tk.Text:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="nw", pady=(8, 0))
        widget = tk.Text(parent, height=6, width=60)
        widget.grid(row=row, column=1, sticky="nsew", pady=(8, 0))
        return widget

    def _reload_profiles(self, *, select_first: bool = False, select_profile_id: str | None = None) -> None:
        profiles = list_profiles(profiles_root=self.profiles_root)
        if not profiles:
            template = create_default_template()
            save_profile(template, profiles_root=self.profiles_root)
            profiles = [template]
        self.validation_cache = {profile.profile_id: [issue.severity for issue in validate_profile(profile)] for profile in profiles}
        self.profile_list.delete(0, tk.END)
        self._profiles = profiles
        for profile in profiles:
            status_icon = self._status_icon(self.validation_cache.get(profile.profile_id, []))
            generic_badge = " (GENERIC)" if isinstance(profile, GenericProfile) else ""
            self.profile_list.insert(tk.END, f"{status_icon} {profile.profile_name}{generic_badge} ({profile.profile_id})")
        target_index = None
        if select_profile_id is not None:
            for index, profile in enumerate(profiles):
                if profile.profile_id == select_profile_id:
                    target_index = index
                    break
        if target_index is None and select_first and profiles:
            target_index = 0
        if target_index is not None:
            self.profile_list.selection_set(target_index)
            self._load_profile(profiles[target_index])

    def _status_icon(self, severities: list[str]) -> str:
        if "ERROR" in severities:
            return "[X]"
        if "WARNING" in severities:
            return "[!]"
        return "[OK]"

    def _on_select(self, event: object | None = None) -> None:
        del event
        selection = self.profile_list.curselection()
        if not selection:
            return
        self._load_profile(self._profiles[int(selection[0])])

    def _load_profile(self, profile: Profile) -> None:
        self.selected_profile_id = profile.profile_id
        self.profile_id_var.set(profile.profile_id)
        self.profile_name_var.set(profile.profile_name)
        self.version_var.set(profile.version)
        if isinstance(profile, GenericProfile):
            self._set_json(self.inventory_text, profile.custom_fields)
            self._set_json(
                self.screens_text,
                [{"region_roi": profile.region_roi, "scan_scope": profile.scan_scope}],
            )
            self._set_json(self.parsing_rules_text, {})
            self._set_json(self.rarity_rules_text, [])
            self._set_json(self.compatibility_rules_text, {"generic_session_id": profile.generic_session_id})
        else:
            self._set_json(self.inventory_text, profile.inventory_definitions)
            self._set_json(self.screens_text, profile.screens)
            self._set_json(self.parsing_rules_text, profile.parsing_rules)
            self._set_json(self.rarity_rules_text, profile.rarity_rules)
            self._set_json(self.compatibility_rules_text, profile.compatibility_rules)
        self.root.title(f"OCRing Profile Editor — {profile.profile_name}")
        self.status_var.set(f"Loaded profile {profile.profile_id}")

    def _new_profile(self) -> None:
        profile = create_default_template()
        save_profile(profile, profiles_root=self.profiles_root)
        self._reload_profiles(select_profile_id=profile.profile_id)
        self.status_var.set(f"Created new profile {profile.profile_id}")

    def _open_generic_profile_selector(self) -> None:
        GenericRegionSelectorWindow(
            profiles_root=self.profiles_root,
            on_save=lambda profile: self._reload_profiles(select_profile_id=profile.profile_id),
        ).run()

    def _save_selected(self) -> None:
        profile = self._profile_from_form()
        if profile is None:
            return
        save_profile(profile, profiles_root=self.profiles_root)
        self._reload_profiles(select_profile_id=profile.profile_id)
        self.status_var.set(f"Saved profile {profile.profile_id}")

    def _export_selected(self) -> None:
        if self.selected_profile_id is None:
            return
        export_path = filedialog.asksaveasfilename(
            title="Export OCRing Profile",
            defaultextension=".ocring-profile",
            filetypes=[("OCRing Profile", "*.ocring-profile"), ("All Files", "*.*")],
        )
        if not export_path:
            return
        package_manager = ProfilePackage(profiles_root=self.profiles_root)
        package_path = package_manager.export_profile(self.selected_profile_id, export_path)
        self.status_var.set(f"Exported profile to {package_path}")
        messagebox.showinfo("OCRing Profile Export", f"Exported profile to {package_path}")

    def _import_profile(self) -> None:
        package_path = filedialog.askopenfilename(
            title="Import OCRing Profile",
            filetypes=[("OCRing Profile", "*.ocring-profile"), ("All Files", "*.*")],
        )
        if not package_path:
            return
        overwrite = False
        if hasattr(messagebox, "askyesno"):
            overwrite = bool(messagebox.askyesno("Import Profile", "Overwrite if the profile id already exists?"))
        package_manager = ProfilePackage(profiles_root=self.profiles_root)
        profile_id = package_manager.import_profile(package_path, overwrite=overwrite)
        self._reload_profiles(select_profile_id=profile_id)
        self.status_var.set(f"Imported profile {profile_id}")
        messagebox.showinfo("OCRing Profile Import", f"Imported profile {profile_id}")

    def _validate_selected(self) -> None:
        profile = self._profile_from_form()
        if profile is None:
            return
        issues = validate_profile(profile)
        self.validation_cache[profile.profile_id] = [issue.severity for issue in issues]
        self._reload_profiles(select_profile_id=profile.profile_id)
        summary = "\n".join(f"{issue.severity}: {issue.message}" for issue in issues)
        messagebox.showinfo("OCRing Profile Validation", summary)
        self.status_var.set(f"Validated profile {profile.profile_id}")

    def _delete_selected(self) -> None:
        if self.selected_profile_id is None:
            return
        confirmed = True
        if hasattr(messagebox, "askyesno"):
            confirmed = bool(messagebox.askyesno("Delete Profile", f"Delete profile {self.selected_profile_id}?"))
        if not confirmed:
            return
        deleted = delete_profile(self.selected_profile_id, profiles_root=self.profiles_root)
        if deleted:
            self.selected_profile_id = None
            self._reload_profiles(select_first=True)
            self.status_var.set("Profile deleted.")

    def _profile_from_form(self) -> Profile | None:
        try:
            inventory_definitions = self._parse_json(self.inventory_text, "inventory_definitions")
            screens = self._parse_json(self.screens_text, "screens")
            parsing_rules = self._parse_json(self.parsing_rules_text, "parsing_rules")
            rarity_rules = self._parse_json(self.rarity_rules_text, "rarity_rules")
            compatibility_rules = self._parse_json(self.compatibility_rules_text, "compatibility_rules")
        except ValueError as error:
            messagebox.showerror("OCRing Profile Editor", str(error))
            self.status_var.set("Profile form contains invalid JSON.")
            return None
        profile_id = self.profile_id_var.get().strip() or create_default_template().profile_id
        current_profile = next((item for item in getattr(self, "_profiles", []) if item.profile_id == profile_id), None)
        if isinstance(current_profile, GenericProfile):
            region_payload = screens[0].get("region_roi", {}) if screens else {}
            compatibility_payload = parsing_rules if isinstance(parsing_rules, dict) else {}
            if isinstance(compatibility_rules, dict):
                compatibility_payload = compatibility_rules
            return GenericProfile(
                profile_id=profile_id,
                profile_name=self.profile_name_var.get().strip() or profile_id,
                version=self.version_var.get().strip() or "1",
                custom_fields=list(inventory_definitions) if isinstance(inventory_definitions, list) else [],
                region_roi={
                    "x1": int(region_payload.get("x1", 0)),
                    "y1": int(region_payload.get("y1", 0)),
                    "x2": int(region_payload.get("x2", 0)),
                    "y2": int(region_payload.get("y2", 0)),
                },
                scan_scope=str(screens[0].get("scan_scope") or "FULL_INVENTORY") if screens else "FULL_INVENTORY",
                generic_session_id=str(compatibility_payload.get("generic_session_id") or ""),
            )
        return Profile(
            profile_id=profile_id,
            profile_name=self.profile_name_var.get().strip() or profile_id,
            version=self.version_var.get().strip() or "1",
            inventory_definitions=list(inventory_definitions) if isinstance(inventory_definitions, list) else [],
            screens=list(screens) if isinstance(screens, list) else [],
            parsing_rules=dict(parsing_rules) if isinstance(parsing_rules, dict) else {},
            rarity_rules=list(rarity_rules) if isinstance(rarity_rules, list) else [],
            compatibility_rules=list(compatibility_rules) if isinstance(compatibility_rules, list) else [],
        )

    def _parse_json(self, widget: tk.Text, field_name: str) -> object:
        raw = widget.get("1.0", tk.END).strip()
        if not raw:
            if field_name == "parsing_rules":
                return {}
            return []
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(f"{field_name} contains invalid JSON: {error.msg}") from error

    def _set_json(self, widget: tk.Text, value: object) -> None:
        widget.delete("1.0", tk.END)
        widget.insert("1.0", json.dumps(value, indent=2, sort_keys=True))
