from __future__ import annotations

import sqlite3
from pathlib import Path

from ocring.ocr.inventory import InventoryStore
from ocring.ocr.review import ReviewRecord, ReviewSession


def _review_session() -> ReviewSession:
    session = ReviewSession(
        "session-1",
        [
            ReviewRecord(
                "record-1",
                1,
                {"item_name": "Power Bore", "item_rarity": "Tier IV"},
                {},
                [],
                [],
                {},
                [],
            )
        ],
    )
    session.accept_record("record-1")
    return session


def test_inventory_store_commit_reviewed_records_is_atomic(tmp_path: Path) -> None:
    store = InventoryStore(tmp_path / "inventory.db")
    count = store.commit_reviewed_records(_review_session())

    assert count == 1
    rows = store.get_all_verified_records()
    assert len(rows) == 1
    assert rows[0].record_id == "record-1"


def test_inventory_store_rolls_back_failed_commit(tmp_path: Path) -> None:
    store = InventoryStore(tmp_path / "inventory.db")
    with sqlite3.connect(store.sqlite_path) as connection:
        connection.execute(
            """
            CREATE TABLE review_inventory_records (
                session_id TEXT NOT NULL,
                record_id TEXT NOT NULL UNIQUE,
                row_slot INTEGER NOT NULL,
                review_status TEXT NOT NULL,
                fields_json TEXT NOT NULL,
                corrections_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO review_inventory_records (
                session_id, record_id, row_slot, review_status, fields_json, corrections_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("session-1", "record-1", 1, "ACCEPTED", "{}", "{}"),
        )
        connection.commit()

    try:
        store.commit_inventory(
            [
                ("session-1", "record-1", 1, "ACCEPTED", "{}", "{}"),
                ("session-1", "record-2", 2, "ACCEPTED", "{}", "{}"),
            ]
        )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("expected duplicate primary write to fail")

    with sqlite3.connect(store.sqlite_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM review_inventory_records").fetchone()[0]
    assert count == 1

