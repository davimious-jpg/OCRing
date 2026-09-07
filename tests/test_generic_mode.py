from __future__ import annotations

from pathlib import Path

from ocring.ocr.generic_profile import create_generic_profile, load_generic_profile, save_generic_profile
from ocring.ocr.profile import is_generic, resolve_profile_runtime
from ocring.ui.generic_region_selector import GenericRegionSelectorWindow


def test_generic_profile_creation_and_save_load(tmp_path: Path) -> None:
    profile = create_generic_profile(
        "My Generic Game",
        (10, 20, 300, 400),
        [
            {"field_name": "name", "field_type": "text", "field_source": "row 1"},
            {"field_name": "count", "field_type": "number", "field_source": "crop 2"},
        ],
    )

    save_generic_profile(profile, profiles_root=tmp_path)
    loaded = load_generic_profile(profile.profile_id, profiles_root=tmp_path)

    assert loaded.profile_name == "My Generic Game"
    assert loaded.region_roi["x2"] == 300
    assert loaded.custom_fields[0]["field_name"] == "name"


def test_generic_profile_runtime_resolves_to_generic_mode(tmp_path: Path) -> None:
    profile = create_generic_profile(
        "Fallback Test",
        (1, 2, 30, 40),
        [{"field_name": "flag", "field_type": "boolean", "field_source": "crop 1"}],
    )
    save_generic_profile(profile, profiles_root=tmp_path)

    runtime = resolve_profile_runtime(profile.profile_id, profiles_root=tmp_path)

    assert is_generic(profile.profile_id, profiles_root=tmp_path) is True
    assert runtime["mode"] == "generic"
    assert runtime["apply_defiance_policy"] is False
    assert runtime["field_rules"][0]["field_name"] == "flag"


def test_generic_region_selector_ui_and_save_without_crashing(tmp_path: Path) -> None:
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

        def insert(self, *args) -> None:
            if len(args) >= 2:
                self._text = str(args[1])

        def delete(self, *args, **kwargs) -> None:
            self._text = ""

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

        def destroy(self) -> None:
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

    from ocring.ui import generic_region_selector as generic_region_selector_module

    generic_region_selector_module.tk = FakeTkModule
    generic_region_selector_module.ttk = FakeTtkModule
    generic_region_selector_module.messagebox = type(
        "MB",
        (),
        {
            "showinfo": staticmethod(lambda *args, **kwargs: None),
            "showerror": staticmethod(lambda *args, **kwargs: None),
        },
    )

    window = GenericRegionSelectorWindow(profiles_root=tmp_path, master=FakeWidget())
    window.fields_text.delete("1.0", "end")
    window.fields_text.insert(
        "1.0",
        '[{"field_name":"score","field_type":"number","field_source":"row 2"}]',
    )
    profile = window._save_generic_profile()

    assert profile is not None
    assert profile.profile_id.startswith("generic-")
    assert (tmp_path / profile.profile_id / "profile.json").exists()
