from __future__ import annotations

from ocring.ocr.locking import build_scan_integrity_report
from ocring.ocr.models import ContinuityProgressionState, ContinuityRecord, ContinuityState, FieldKind, ScanScope


def test_scan_integrity_flags_name_type_semantic_contradiction() -> None:
    continuity_records = (
        ContinuityRecord(
            continuity_key="semantic-1",
            profile_id="defiance",
            row_slots=(1,),
            state=ContinuityState.STABLE,
            progression_state=ContinuityProgressionState.STATIONARY,
            support_count=2,
            frame_ids=("f1", "f2"),
            source_record_count=2,
            sightings=(("f1", 1), ("f2", 1)),
            fields={
                FieldKind.ITEM_NAME: "Tactical Scope",
                FieldKind.ITEM_RARITY: "Tier IV",
                FieldKind.ITEM_COUNT: "1",
                FieldKind.ITEM_TYPE: "Rocket Launcher",
            },
        ),
    )

    report = build_scan_integrity_report(continuity_records, scan_scope=ScanScope.CURRENT_PAGE)

    assert report.completeness_state == "review_required"
    contradiction_codes = {item.contradiction_code for item in report.contradictions}
    assert "NAME_TOKEN_SCOPE_LOOKS_NON_WEAPON" in contradiction_codes
    assert "SEMANTIC_CONTRADICTION_PRESENT" in report.reasons


def test_scan_integrity_flags_zero_count_contradiction() -> None:
    continuity_records = (
        ContinuityRecord(
            continuity_key="semantic-2",
            profile_id="defiance",
            row_slots=(1,),
            state=ContinuityState.STABLE,
            progression_state=ContinuityProgressionState.STATIONARY,
            support_count=2,
            frame_ids=("f1", "f2"),
            source_record_count=2,
            sightings=(("f1", 1), ("f2", 1)),
            fields={
                FieldKind.ITEM_NAME: "Power Bore",
                FieldKind.ITEM_RARITY: "Tier IV",
                FieldKind.ITEM_COUNT: "0",
                FieldKind.ITEM_TYPE: "Rocket Launcher",
            },
        ),
    )

    report = build_scan_integrity_report(continuity_records, scan_scope=ScanScope.CURRENT_PAGE)

    contradiction_codes = {item.contradiction_code for item in report.contradictions}
    assert "COUNT_ZERO_INVALID" in contradiction_codes
    assert report.completeness_state == "review_required"
