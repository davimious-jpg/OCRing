from __future__ import annotations

from ocring.ocr.locking import build_scan_integrity_report
from ocring.ocr.models import ContinuityProgressionState, ContinuityRecord, ContinuityState, FieldKind, ScanScope


def test_current_page_scope_returns_page_complete_when_locked() -> None:
    continuity_records = (
        ContinuityRecord(
            continuity_key="scope1",
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
                FieldKind.ITEM_COUNT: "2",
                FieldKind.ITEM_TYPE: "Rocket Launcher",
            },
        ),
    )

    report = build_scan_integrity_report(continuity_records, scan_scope=ScanScope.CURRENT_PAGE)

    assert report.completeness_state == "page_complete"
    assert report.scan_scope is ScanScope.CURRENT_PAGE


def test_full_inventory_scope_stays_partial_when_required_fields_pending() -> None:
    continuity_records = (
        ContinuityRecord(
            continuity_key="scope2",
            profile_id="defiance",
            row_slots=(1,),
            state=ContinuityState.WEAK,
            progression_state=ContinuityProgressionState.STATIONARY,
            support_count=1,
            frame_ids=("f1",),
            source_record_count=1,
            sightings=(("f1", 1),),
            fields={
                FieldKind.ITEM_NAME: "Power Bore",
                FieldKind.ITEM_RARITY: "Tier IV",
            },
            reasons=("LOW_TEMPORAL_SUPPORT",),
        ),
    )

    report = build_scan_integrity_report(continuity_records, scan_scope=ScanScope.FULL_INVENTORY)

    assert report.completeness_state == "partial"
    assert report.scan_scope is ScanScope.FULL_INVENTORY
