from __future__ import annotations

from pathlib import Path

from ocring.ocr.profile import Profile, save_profile
from ocring.ocr.search_definition import SearchDefinition
from ocring.ocr.search_engine import SearchEngine
from ocring.ocr.inventory import InventoryStore


def _profile() -> Profile:
    return Profile(
        profile_id="defiance",
        profile_name="Defiance",
        version="1",
        inventory_definitions=[
            {"canonical_id": "item_name", "label": "Item Name", "required": True, "extraction_source": "ocr.item_name"},
            {"canonical_id": "item_rarity", "label": "Rarity", "required": True, "extraction_source": "ocr.item_rarity"},
            {"canonical_id": "item_type", "label": "Weapon Type", "required": True, "extraction_source": "ocr.item_type"},
            {"canonical_id": "item_synergy", "label": "Synergy", "required": False, "extraction_source": "ocr.item_synergy"},
            {"canonical_id": "mod_slot", "label": "Mod Slot", "required": False, "extraction_source": "ocr.mod_slot"},
            {"canonical_id": "tier", "label": "Tier", "required": False, "extraction_source": "ocr.tier"},
        ],
        parsing_rules={
            "known_synergies": ["Epidemic", "Ether Acceleration"],
            "known_weapon_types": ["Rocket Launcher", "SMG"],
            "known_mod_slots": ["Barrel", "Scope"],
        },
        rarity_rules=[
            {"tier": "Tier IV", "color": "#9c27b0", "name": "Epic"},
            {"tier": "Tier V", "color": "#ff9800", "name": "Legendary"},
        ],
    )


def test_search_definition_loads_and_autocompletes(tmp_path: Path) -> None:
    save_profile(_profile(), profiles_root=tmp_path)
    definition = SearchDefinition.load_active_profile("defiance", profiles_root=tmp_path)

    assert "item_name" in definition.searchable_fields
    assert "Rarity" in definition.quick_tabs
    assert "item_rarity" in definition.filterable_fields
    assert "item_name" in definition.sortable_fields
    assert definition.suggest("Epi") == ["Epidemic"]


def test_search_definition_validates_fields_and_quick_tabs(tmp_path: Path) -> None:
    save_profile(_profile(), profiles_root=tmp_path)
    definition = SearchDefinition.load_active_profile("defiance", profiles_root=tmp_path)

    assert definition.validate_field("rarity") is True
    assert definition.validate_field("unknown_field") is False
    query, filters = definition.quick_tab_query("Weapon Type")
    assert query == ""
    assert "item_type" in filters


def test_search_engine_uses_profile_definition_for_suggestions(tmp_path: Path) -> None:
    save_profile(_profile(), profiles_root=tmp_path)
    inventory = InventoryStore(tmp_path / "inventory.db")
    engine = SearchEngine(inventory, saved_search_path=tmp_path / "saved.json", profiles_root=tmp_path)

    assert engine.suggest("Epi") == ["Epidemic"]


def test_settings_window_search_definition_render(monkeypatch, tmp_path: Path) -> None:
    save_profile(_profile(), profiles_root=tmp_path)

    class FakeVar:
        def __init__(self, value: str = "") -> None:
            self.value = value
        def set(self, value: str) -> None:
            self.value = value
        def get(self) -> str:
            return self.value

    class FakeWidget:
        def __init__(self, *args, **kwargs) -> None:
            self._text = ""
            self._title = ""
        def grid(self, *args, **kwargs) -> None:
            return None
        def pack(self, *args, **kwargs) -> None:
            return None
        def columnconfigure(self, *args, **kwargs) -> None:
            return None
        def delete(self, *args, **kwargs) -> None:
            self._text = ""
        def insert(self, *args) -> None:
            if len(args) >= 2:
                self._text += str(args[1])
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
        StringVar = lambda *args, value="", **kwargs: FakeVar(value=value)

    class FakeTtkModule:
        Frame = FakeWidget
        Label = FakeWidget
        Button = FakeWidget
        Combobox = FakeWidget
        Notebook = FakeWidget

    from ocring.ui import settings_window as settings_window_module

    settings_window_module.tk = FakeTkModule
    settings_window_module.ttk = FakeTtkModule
    settings_window_module.messagebox = type("MB", (), {"showinfo": staticmethod(lambda *args, **kwargs: None)})
    original_loader = SearchDefinition.load_active_profile
    monkeypatch.setattr(
        settings_window_module.SearchDefinition,
        "load_active_profile",
        staticmethod(lambda profile_id, **kwargs: original_loader(profile_id, profiles_root=tmp_path)),
    )

    window = settings_window_module.SettingsWindow(master=FakeWidget(), profile_id="defiance")

    assert "searchable_fields" in window.search_text._text
