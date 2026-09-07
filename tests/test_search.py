from __future__ import annotations

import sqlite3
from pathlib import Path

from ocring.ocr.inventory import InventoryStore
from ocring.ocr.search import SearchEngine


def _seed_inventory(db_path: Path) -> InventoryStore:
    store = InventoryStore(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS review_inventory_records (
                session_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                row_slot INTEGER NOT NULL,
                review_status TEXT NOT NULL,
                fields_json TEXT NOT NULL,
                corrections_json TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO review_inventory_records (
                session_id, record_id, row_slot, review_status, fields_json, corrections_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("s1", "r1", 1, "ACCEPTED", '{"item_name":"Alpha Rocket","item_rarity":"Tier IV","item_type":"Rocket Launcher","item_count":"1"}', "{}"),
                ("s1", "r2", 2, "CORRECTED", '{"item_name":"Bravo SMG","item_rarity":"Tier III","item_type":"SMG","item_count":"2"}', "{}"),
                ("s2", "r3", 3, "ACCEPTED", '{"item_name":"Charlie Pistol","item_rarity":"Tier II","item_type":"Pistol","item_count":"1"}', "{}"),
            ],
        )
        connection.commit()
    return store


def test_query_parsing_and_field_filters(tmp_path: Path) -> None:
    store = _seed_inventory(tmp_path / "inventory.db")
    engine = SearchEngine(store, saved_search_path=tmp_path / "saved.json")

    results = engine.search("rarity:Tier IV AND type:Rocket Launcher", {})

    assert [record.record_id for record in results] == ["r1"]


def test_simple_text_search_across_item_name(tmp_path: Path) -> None:
    store = _seed_inventory(tmp_path / "inventory.db")
    engine = SearchEngine(store, saved_search_path=tmp_path / "saved.json")

    results = engine.search("Bravo", {})

    assert [record.record_id for record in results] == ["r2"]


def test_saved_searches_and_load(tmp_path: Path) -> None:
    store = _seed_inventory(tmp_path / "inventory.db")
    engine = SearchEngine(store, saved_search_path=tmp_path / "saved.json")

    engine.save_search("Epic SMGs", "rarity:Tier III AND type:SMG", {})
    names = [item.name for item in engine.list_saved_searches()]
    loaded = engine.load_search("Epic SMGs")

    assert "Epic SMGs" in names
    assert loaded.query == "rarity:Tier III AND type:SMG"


def test_smart_folders_available(tmp_path: Path) -> None:
    store = _seed_inventory(tmp_path / "inventory.db")
    engine = SearchEngine(store, saved_search_path=tmp_path / "saved.json")

    names = [item.name for item in engine.list_saved_searches()]

    assert "Needs Review" in names
    assert "Epic+" in names
    assert "Legendary Rocket Launchers" in names
    assert "Recently Added" in names
