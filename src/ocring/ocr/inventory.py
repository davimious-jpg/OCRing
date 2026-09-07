from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .review import ReviewRecord, ReviewSession, ReviewStatus


@dataclass(frozen=True)
class InventoryRecord:
    session_id: str
    record_id: str
    row_slot: int
    review_status: str
    fields: dict[str, str]
    corrections: dict[str, str]
    added_order: int = 0


class InventoryStore:
    def __init__(self, sqlite_path: Path) -> None:
        self.sqlite_path = sqlite_path

    def get_all_verified_records(self) -> list[InventoryRecord]:
        return self._fetch_records("WHERE review_status IN ('ACCEPTED', 'CORRECTED', 'AUTO_SAVED')")

    def get_records_by_filter(self, filters: dict[str, Any]) -> list[InventoryRecord]:
        records = self.get_all_verified_records()
        return [record for record in records if _matches_filters(record, filters)]

    def commit_reviewed_records(self, review_session: ReviewSession) -> int:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        records = review_session.get_committable_records()
        rows = [
            (
                review_session.session_id,
                record.record_id,
                record.row_slot,
                record.review_status,
                json.dumps(record.fields, sort_keys=True),
                json.dumps(_commit_metadata(review_session, record), sort_keys=True),
            )
            for record in records
        ]
        self.commit_inventory(rows)
        return len(records)

    def commit_inventory(self, rows: list[tuple[str, str, int, str, str, str]]) -> int:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.sqlite_path) as connection:
            try:
                connection.execute("BEGIN")
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
                    _dedupe_rows(rows),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return len(_dedupe_rows(rows))

    def _fetch_records(self, where_clause: str = "", params: tuple[Any, ...] = ()) -> list[InventoryRecord]:
        if not self.sqlite_path.exists():
            return []
        query = (
            "SELECT rowid, session_id, record_id, row_slot, review_status, fields_json, corrections_json "
            "FROM review_inventory_records "
            f"{where_clause} "
            "ORDER BY rowid DESC"
        )
        with sqlite3.connect(self.sqlite_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            InventoryRecord(
                session_id=str(session_id),
                record_id=str(record_id),
                row_slot=int(row_slot),
                review_status=str(review_status),
                fields=dict(json.loads(fields_json)),
                corrections=dict(json.loads(corrections_json)),
                added_order=int(rowid),
            )
            for rowid, session_id, record_id, row_slot, review_status, fields_json, corrections_json in rows
        ]


def _matches_filters(record: InventoryRecord, filters: dict[str, Any]) -> bool:
    for key, expected in filters.items():
        if expected in (None, "", []):
            continue
        expected_value = str(expected).lower()
        if key == "session_id":
            actual = record.session_id
        elif key == "review_status":
            actual = record.review_status
        elif key == "recently_added":
            if not bool(expected):
                continue
            actual = "true"
            expected_value = "true"
        else:
            actual = record.fields.get(key, "")
        if str(actual).lower() != expected_value:
            return False
    return True


def _commit_metadata(review_session: ReviewSession, record: ReviewRecord) -> dict[str, Any]:
    metadata: dict[str, Any] = dict(review_session.corrections.get(record.record_id, {}))
    if record.review_status == ReviewStatus.AUTO_SAVED:
        metadata["_auto_store"] = dict(record.auto_store_policy)
        metadata["_provenance"] = {
            "source_frame_ids": list(record.source_frame_ids),
            "source_row_ids": list(record.source_row_ids),
            "support_summary": record.support_summary,
            "field_details": record.field_details,
            "reasons": list(record.reasons),
        }
    return metadata


def _dedupe_rows(rows: list[tuple[str, str, int, str, str, str]]) -> list[tuple[str, str, int, str, str, str]]:
    deduped: list[tuple[str, str, int, str, str, str]] = []
    seen_auto_saved: set[tuple[str, str, str]] = set()
    for row in rows:
        session_id, record_id, _row_slot, review_status, fields_json, _corrections_json = row
        if review_status == ReviewStatus.AUTO_SAVED:
            key = (session_id, record_id, fields_json)
            if key in seen_auto_saved:
                continue
            seen_auto_saved.add(key)
        deduped.append(row)
    return deduped
