from __future__ import annotations

from pathlib import Path

from ocring.ocr.profile import create_default_template, load_profile, save_profile
from ocring.ocr.profile_validator import validate_profile
from ocring.ui.profile_editor import ProfileEditorWindow


def test_profile_load_and_save_round_trip(tmp_path: Path) -> None:
    profile = create_default_template()
    profile.profile_name = "Test Profile"

    path = save_profile(profile, profiles_root=tmp_path)
    loaded = load_profile(profile.profile_id, profiles_root=tmp_path)

    assert path == tmp_path / profile.profile_id / "profile.json"
    assert loaded.profile_name == "Test Profile"
    assert loaded.inventory_definitions[0]["canonical_id"] == "item_name"


def test_validate_profile_reports_duplicate_ids_and_missing_sources() -> None:
    profile = create_default_template()
    profile.inventory_definitions.append(
        {
            "canonical_id": "item_name",
            "label": "Duplicate Name",
            "required": True,
            "extraction_source": "",
        }
    )
    profile.rarity_rules.append({"tier": "Tier VI", "color": "", "name": "Mythic"})

    issues = validate_profile(profile)

    assert any(issue.severity == "ERROR" and "Duplicate canonical_id 'item_name'" in issue.message for issue in issues)
    assert any(issue.severity == "ERROR" and "missing a color mapping" in issue.message for issue in issues)


def test_profile_editor_ui_loads_without_crashing(tmp_path: Path) -> None:
    class FakeVar:
        def __init__(self, value: str = "") -> None:
            self.value = value

        def set(self, value: str) -> None:
            self.value = value

        def get(self) -> str:
            return self.value

    class FakeWidget:
        def __init__(self, *args, **kwargs) -> None:
            self._selection: tuple[int, ...] = ()
            self._text = ""
            self._title = ""

        def grid(self, *args, **kwargs) -> None:
            return None

        def pack(self, *args, **kwargs) -> None:
            return None

        def bind(self, *args, **kwargs) -> None:
            return None

        def delete(self, *args, **kwargs) -> None:
            self._text = ""

        def insert(self, *args) -> None:
            if len(args) >= 2:
                self._text = str(args[1])

        def get(self, *args, **kwargs) -> str:
            return self._text

        def selection_set(self, index: int) -> None:
            self._selection = (index,)

        def curselection(self) -> tuple[int, ...]:
            return self._selection

        def columnconfigure(self, *args, **kwargs) -> None:
            return None

        def rowconfigure(self, *args, **kwargs) -> None:
            return None

        def title(self, value: str) -> None:
            self._title = value

        def geometry(self, *args, **kwargs) -> None:
            return None

        def mainloop(self) -> None:
            return None

    class FakeTkModule:
        END = "end"
        Misc = object
        Tk = FakeWidget
        Text = FakeWidget
        Listbox = FakeWidget
        StringVar = lambda *args, value="", **kwargs: FakeVar(value=value)

    class FakeTtkModule:
        Frame = FakeWidget
        Label = FakeWidget
        Button = FakeWidget
        Entry = FakeWidget

    from ocring.ui import profile_editor as profile_editor_module

    profile_editor_module.tk = FakeTkModule
    profile_editor_module.ttk = FakeTtkModule
    profile_editor_module.messagebox = type(
        "MB",
        (),
        {
            "showinfo": staticmethod(lambda *args, **kwargs: None),
            "showerror": staticmethod(lambda *args, **kwargs: None),
            "askyesno": staticmethod(lambda *args, **kwargs: True),
        },
    )

    save_profile(create_default_template(), profiles_root=tmp_path)
    window = ProfileEditorWindow(profiles_root=tmp_path, master=FakeWidget())

    assert window.profile_id_var.get() != ""
    assert window.root._title.startswith("OCRing Profile Editor")
