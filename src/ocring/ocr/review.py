from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .auto_store import AutoStoreMode, AutoStoreDisposition, auto_store_dedupe_key, evaluate_auto_store_eligibility


class ReviewStatus:
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CORRECTED = "CORRECTED"
    AUTO_SAVED = "AUTO_SAVED"


@dataclass
class ReviewRecord:
    record_id: str
    row_slot: int
    fields: dict[str, str]
    support_summary: dict[str, Any]
    source_frame_ids: list[str]
    source_row_ids: list[str]
    overlap_provenance: dict[str, Any]
    reasons: list[str]
    field_details: dict[str, Any] = field(default_factory=dict)
    review_status: str = ReviewStatus.PENDING
    auto_store_decision: str = ""
    auto_store_policy: dict[str, Any] = field(default_factory=dict)
    record_class: str = ""
    required_fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)


@dataclass
class ReviewSession:
    session_id: str
    records: list[ReviewRecord]
    corrections: dict[str, dict[str, str]] = field(default_factory=dict)
    commit_ready: bool = False
    auto_store_summary: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_report(cls, report: dict[str, Any]) -> "ReviewSession":
        frame_reports = report.get("frame_reports", [])
        if frame_reports:
            session_id = str(frame_reports[0].get("frame", {}).get("session_id") or "session-unknown")
        else:
            session_id = "session-unknown"
        records: list[ReviewRecord] = []
        for index, item in enumerate(report.get("assembled_records", []), start=1):
            fields = dict(item.get("fields", {}))
            record_id = str(item.get("record_id") or f"record-{index:03d}")
            record_class = str(item.get("record_class") or item.get("definition_used") or "")
            records.append(
                ReviewRecord(
                    record_id=record_id,
                    row_slot=int(item.get("row_slot", index)),
                    fields=fields,
                    field_details=dict(item.get("field_details", {})),
                    support_summary=dict(item.get("support_summary", {})),
                    source_frame_ids=[str(value) for value in item.get("source_frame_ids", [])],
                    source_row_ids=[str(value) for value in item.get("source_row_ids", [])],
                    overlap_provenance=dict(item.get("overlap_provenance", {})),
                    reasons=[str(value) for value in item.get("reasons", [])],
                    auto_store_decision=str(item.get("auto_store_decision", "")),
                    auto_store_policy=dict(item.get("auto_store_policy", {})),
                    record_class=record_class,
                    required_fields=_required_fields_from_item(item, record_class),
                    missing_fields=[str(value) for value in item.get("missing_fields", [])],
                )
            )
        return cls(session_id=session_id, records=records)

    def accept_record(self, record_id: str) -> None:
        record = self._get_record(record_id)
        record.review_status = ReviewStatus.ACCEPTED
        self._refresh_commit_ready()

    def reject_record(self, record_id: str) -> None:
        record = self._get_record(record_id)
        record.review_status = ReviewStatus.REJECTED
        self._refresh_commit_ready()

    def correct_field(self, record_id: str, field: str, new_value: str) -> None:
        record = self._get_record(record_id)
        record.fields[field] = new_value
        record.review_status = ReviewStatus.CORRECTED
        self.corrections.setdefault(record_id, {})[field] = new_value
        self._refresh_commit_ready()

    def get_pending_count(self) -> int:
        return sum(1 for record in self.records if record.review_status == ReviewStatus.PENDING)

    def get_committable_records(self) -> list[ReviewRecord]:
        return [
            record
            for record in self.records
            if record.review_status in {ReviewStatus.ACCEPTED, ReviewStatus.CORRECTED, ReviewStatus.AUTO_SAVED}
        ]

    def get_exception_records(self) -> list[ReviewRecord]:
        return [
            record
            for record in self.records
            if record.review_status != ReviewStatus.AUTO_SAVED
        ]

    def apply_auto_store_policy(self, mode: str = AutoStoreMode.STRICT_MANUAL_REVIEW.value) -> dict[str, int]:
        if str(mode) != AutoStoreMode.AUTO_STORE_VERIFIED_STABLE.value:
            self.auto_store_summary = {
                "auto_store_eligible": 0,
                "automatically_stored": 0,
                "needs_manual_review": len(self.records),
                "hold_unknown": sum(1 for record in self.records if str(record.fields.get("item_name", "")).upper() == "UNKNOWN"),
                "duplicate_suppressions": 0,
            }
            return dict(self.auto_store_summary)

        seen: set[tuple[object, ...]] = set()
        summary = {
            "auto_store_eligible": 0,
            "automatically_stored": 0,
            "needs_manual_review": 0,
            "hold_unknown": 0,
            "duplicate_suppressions": 0,
        }
        for record in self.records:
            decision = evaluate_auto_store_eligibility(record)
            record.auto_store_decision = decision.disposition.value
            record.auto_store_policy = {
                "eligible": decision.eligible,
                "policy_rule": decision.policy_rule,
                "reasons": list(decision.reasons),
            }
            record.reasons = list(decision.reasons)
            if decision.disposition is AutoStoreDisposition.HOLD_UNKNOWN:
                summary["hold_unknown"] += 1
                record.review_status = ReviewStatus.PENDING
                continue
            if not decision.eligible:
                summary["needs_manual_review"] += 1
                record.review_status = ReviewStatus.PENDING
                continue
            summary["auto_store_eligible"] += 1
            dedupe_key = auto_store_dedupe_key(record)
            if dedupe_key in seen:
                summary["duplicate_suppressions"] += 1
                record.review_status = ReviewStatus.PENDING
                record.auto_store_decision = AutoStoreDisposition.NEEDS_REVIEW.value
                record.auto_store_policy["eligible"] = False
                record.auto_store_policy["reasons"] = list(dict.fromkeys([*record.auto_store_policy["reasons"], "DUPLICATE_STABLE_OBSERVATION_SUPPRESSED"]))
                record.reasons = list(record.auto_store_policy["reasons"])
                continue
            seen.add(dedupe_key)
            record.review_status = ReviewStatus.AUTO_SAVED
            summary["automatically_stored"] += 1
        self.auto_store_summary = summary
        self._refresh_commit_ready()
        return dict(summary)

    def get_review_summary(self) -> dict[str, int]:
        if self.auto_store_summary:
            return dict(self.auto_store_summary)
        return {
            "auto_store_eligible": 0,
            "automatically_stored": sum(1 for record in self.records if record.review_status == ReviewStatus.AUTO_SAVED),
            "needs_manual_review": sum(1 for record in self.records if record.review_status == ReviewStatus.PENDING),
            "hold_unknown": sum(1 for record in self.records if str(record.fields.get("item_name", "")).upper() == "UNKNOWN"),
            "duplicate_suppressions": 0,
        }

    def get_record(self, record_id: str) -> ReviewRecord:
        return self._get_record(record_id)

    def commit_to_sqlite(self, sqlite_path: Path) -> int:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        records = self.get_committable_records()
        with sqlite3.connect(sqlite_path) as connection:
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
                    (
                        self.session_id,
                        record.record_id,
                        record.row_slot,
                        record.review_status,
                        json.dumps(record.fields, sort_keys=True),
                        json.dumps(_commit_metadata(self, record), sort_keys=True),
                    )
                    for record in records
                ],
            )
            connection.commit()
        return len(records)

    def _get_record(self, record_id: str) -> ReviewRecord:
        for record in self.records:
            if record.record_id == record_id:
                return record
        raise KeyError(f"Unknown review record: {record_id}")

    def _refresh_commit_ready(self) -> None:
        self.commit_ready = bool(self.records) and all(
            record.review_status in {ReviewStatus.ACCEPTED, ReviewStatus.CORRECTED, ReviewStatus.REJECTED, ReviewStatus.AUTO_SAVED}
            for record in self.records
        )


def load_review_session_from_store(session_id: str, *, sessions_root: Path) -> ReviewSession:
    session_root = sessions_root / session_id
    if not session_root.exists():
        raise FileNotFoundError(f"No stored session found for {session_id!r} in {sessions_root}")
    commit_dirs = sorted((path for path in session_root.iterdir() if path.is_dir() and not path.name.startswith(".")), reverse=True)
    if not commit_dirs:
        raise FileNotFoundError(f"No committed session bundles found for {session_id!r}.")
    report_path = commit_dirs[0] / "report.json"
    if not report_path.exists():
        raise FileNotFoundError(f"Missing report.json in committed session bundle: {commit_dirs[0]}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return ReviewSession.from_report(report)


def _commit_metadata(session: ReviewSession, record: ReviewRecord) -> dict[str, Any]:
    metadata: dict[str, Any] = dict(session.corrections.get(record.record_id, {}))
    if record.review_status == ReviewStatus.AUTO_SAVED:
        metadata["_auto_store"] = dict(record.auto_store_policy)
        metadata["_provenance"] = {
            "source_frame_ids": list(record.source_frame_ids),
            "source_row_ids": list(record.source_row_ids),
            "support_summary": record.support_summary,
            "field_details": record.field_details,
            "record_class": record.record_class,
            "required_fields": list(record.required_fields),
            "missing_fields": list(record.missing_fields),
            "reasons": list(record.reasons),
        }
    return metadata


def _required_fields_from_item(item: dict[str, Any], record_class: str) -> list[str]:
    explicit = item.get("required_fields")
    if isinstance(explicit, (list, tuple)):
        return [str(value) for value in explicit]
    normalized = record_class.strip().lower()
    if normalized == "weaponmod":
        return ["item_name"]
    if normalized == "weapon":
        return ["item_name", "item_rarity", "item_type"]
    return ["item_name"]
