from __future__ import annotations

from typing import Any


def build_replay_snapshot(report: dict[str, Any]) -> dict[str, Any]:
    continuity_records = report.get("continuity_records", [])
    assembled_records = report.get("assembled_records", [])
    scan_integrity = report.get("scan_integrity", {})

    return {
        "profile_id": report.get("profile_id"),
        "scan_scope": scan_integrity.get("scan_scope"),
        "completeness_state": scan_integrity.get("completeness_state"),
        "completeness_reason": scan_integrity.get("completeness_reason"),
        "continuity_records": [
            {
                "state": record.get("state"),
                "support_count": record.get("support_count"),
                "fields": record.get("fields"),
            }
            for record in continuity_records
        ],
        "assembled_records": [
            {
                "row_slot": record.get("row_slot"),
                "state": record.get("state"),
                "fields": record.get("fields"),
                "missing_fields": record.get("missing_fields"),
                "support_summary": record.get("support_summary"),
            }
            for record in assembled_records
        ],
        "locked_fields": [
            {
                "field_kind": field.get("field_kind"),
                "candidate_value": field.get("candidate_value"),
                "lock_state": field.get("lock_state"),
            }
            for field in scan_integrity.get("locked_fields", [])
        ],
        "review_required_fields": [
            {
                "field_kind": field.get("field_kind"),
                "candidate_value": field.get("candidate_value"),
                "lock_state": field.get("lock_state"),
                "provenance": field.get("provenance"),
                "reasons": field.get("reasons"),
            }
            for field in scan_integrity.get("review_required_fields", [])
        ],
        "contradictions": [
            {
                "field_kind": contradiction.get("field_kind"),
                "candidate_value": contradiction.get("candidate_value"),
                "contradiction_code": contradiction.get("contradiction_code"),
                "provenance": contradiction.get("provenance"),
            }
            for contradiction in scan_integrity.get("contradictions", [])
        ],
    }
