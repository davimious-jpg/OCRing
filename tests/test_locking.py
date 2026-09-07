from __future__ import annotations

from ocring.ocr.locking import build_scan_integrity_report
from ocring.ocr.models import ContinuityProgressionState, ContinuityRecord, ContinuityState, FieldKind, LockState, ScanScope


def test_build_scan_integrity_report_locks_stable_required_fields() -> None:
    continuity_records = (
        ContinuityRecord(
            continuity_key="abc123",
            profile_id="defiance",
            row_slots=(1,),
            state=ContinuityState.STABLE,
            progression_state=ContinuityProgressionState.STATIONARY,
            support_count=3,
            frame_ids=("f1", "f2"),
            source_record_count=2,
            sightings=(("f1", 1), ("f2", 1)),
            fields={
                FieldKind.ITEM_NAME: "Power Bore",
                FieldKind.ITEM_RARITY: "Tier IV",
                FieldKind.ITEM_COUNT: "2",
                FieldKind.ITEM_TYPE: "Rocket Launcher",
            },
            field_provenance={
                "item_name": {"source_frame_ids": ["f1", "f2"], "source_crop_ids": ["c1", "c2"]},
                "item_rarity": {"source_frame_ids": ["f1", "f2"], "source_crop_ids": ["c3", "c4"]},
                "item_count": {"source_frame_ids": ["f1", "f2"], "source_crop_ids": ["c5", "c6"]},
                "item_type": {"source_frame_ids": ["f1", "f2"], "source_crop_ids": ["c7", "c8"]},
            },
        ),
    )

    report = build_scan_integrity_report(continuity_records, scan_scope=ScanScope.FULL_INVENTORY)

    assert report.completeness_state == "partial"
    assert report.completeness_reason == "scroll_exhaustion_unproven"
    assert report.review_required_fields == ()
    assert report.contradictions == ()
    required_locks = [field for field in report.locked_fields if field.field_kind in {
        FieldKind.ITEM_NAME, FieldKind.ITEM_RARITY, FieldKind.ITEM_COUNT, FieldKind.ITEM_TYPE
    }]
    assert len(required_locks) == 4
    assert all(field.lock_state is LockState.LOCKED for field in required_locks)


def test_build_scan_integrity_report_routes_conflicts_to_review() -> None:
    continuity_records = (
        ContinuityRecord(
            continuity_key="def456",
            profile_id="defiance",
            row_slots=(2,),
            state=ContinuityState.COLLIDED,
            progression_state=ContinuityProgressionState.STATIONARY,
            support_count=2,
            frame_ids=("f1", "f2"),
            source_record_count=2,
            sightings=(("f1", 2), ("f2", 2)),
            fields={
                FieldKind.ITEM_NAME: "Hellbug Rocket",
                FieldKind.ITEM_RARITY: "Tier IV",
            },
            field_provenance={
                "item_name": {"source_frame_ids": ["f1", "f2"], "source_crop_ids": ["n1", "n2"]},
                "item_rarity": {"source_frame_ids": ["f1", "f2"], "source_crop_ids": ["r1", "r2"]},
            },
            reasons=("SOURCE_RECORD_CONFLICTED",),
        ),
    )

    report = build_scan_integrity_report(continuity_records, scan_scope=ScanScope.CURRENT_PAGE)

    assert report.completeness_state == "review_required"
    assert report.review_required_fields
    assert report.contradictions
    assert any(field.lock_state is LockState.BLOCKED_BY_CONFLICT for field in report.review_required_fields)
    assert report.review_required_fields[0].provenance["source_frame_ids"] == ["f1", "f2"]
    assert report.contradictions[0].provenance["source_frame_ids"] == ["f1", "f2"]
    assert "CONTINUITY_CONFLICT_PRESENT" in report.reasons


def test_build_scan_integrity_report_marks_full_inventory_complete_only_with_boundary_evidence() -> None:
    continuity_records = (
        ContinuityRecord(
            continuity_key="ghi789",
            profile_id="defiance",
            row_slots=(3,),
            state=ContinuityState.STABLE,
            progression_state=ContinuityProgressionState.STATIONARY,
            support_count=2,
            frame_ids=("f1", "f2"),
            source_record_count=2,
            sightings=(("f1", 3), ("f2", 3)),
            fields={
                FieldKind.ITEM_NAME: "Power Bore",
                FieldKind.ITEM_RARITY: "Tier IV",
                FieldKind.ITEM_COUNT: "1",
                FieldKind.ITEM_TYPE: "Rocket Launcher",
            },
            reasons=("PAGE_BOUNDARY_DETECTED",),
        ),
    )

    report = build_scan_integrity_report(continuity_records, scan_scope=ScanScope.FULL_INVENTORY)

    assert report.completeness_state == "complete"
    assert report.completeness_reason == "page_boundary_detected"
