from __future__ import annotations

from ocring.ocr.continuity import analyze_frame_overlaps, build_continuity_records
from ocring.ocr.models import AssembledCandidateRecord, ContinuityProgressionState, ContinuityState, FieldKind, RecordAssemblyState


def test_build_continuity_records_marks_stable_for_repeated_identity() -> None:
    records = (
        AssembledCandidateRecord(
            row_slot=1,
            profile_id="defiance",
            state=RecordAssemblyState.COMPLETE,
            fields={
                FieldKind.ITEM_NAME: "Power Bore",
                FieldKind.ITEM_TYPE: "Rocket Launcher",
                FieldKind.ITEM_RARITY: "Tier IV",
            },
            support_summary={
                "item_name": {"support_state": "supported", "support_count": 2, "best_confidence": 0.8, "frame_hint": "f1"},
                    "item_type": {"support_state": "supported", "support_count": 2, "best_confidence": 0.8, "frame_hint": "f1"},
                    "item_rarity": {"support_state": "supported", "support_count": 2, "best_confidence": 0.8, "frame_hint": "f1"},
            },
            source_frame_ids=("f1",),
            source_row_ids=("f1:row:1",),
            missing_fields=(),
        ),
        AssembledCandidateRecord(
            row_slot=1,
            profile_id="defiance",
            state=RecordAssemblyState.COMPLETE,
            fields={
                FieldKind.ITEM_NAME: "Power Bore",
                FieldKind.ITEM_TYPE: "Rocket Launcher",
                FieldKind.ITEM_RARITY: "Tier IV",
            },
            support_summary={
                "item_name": {"support_state": "supported", "support_count": 3, "best_confidence": 0.9, "frame_hint": "f2"},
                    "item_type": {"support_state": "supported", "support_count": 3, "best_confidence": 0.9, "frame_hint": "f2"},
                    "item_rarity": {"support_state": "supported", "support_count": 3, "best_confidence": 0.9, "frame_hint": "f2"},
            },
            source_frame_ids=("f2",),
            source_row_ids=("f2:row:1",),
            missing_fields=(),
        ),
    )

    continuity = build_continuity_records(records, profile_id="defiance", frame_order={"f1": 0, "f2": 1})

    assert len(continuity) == 1
    assert continuity[0].state is ContinuityState.STABLE
    assert continuity[0].progression_state is ContinuityProgressionState.STATIONARY
    assert continuity[0].support_count == 3
    assert continuity[0].frame_ids == ("f1", "f2")


def test_build_continuity_records_marks_weak_for_low_support() -> None:
    records = (
        AssembledCandidateRecord(
            row_slot=2,
            profile_id="defiance",
            state=RecordAssemblyState.PARTIAL,
            fields={
                FieldKind.ITEM_NAME: "Hellbug Rocket",
                FieldKind.ITEM_TYPE: "Rocket Launcher",
                FieldKind.ITEM_RARITY: "Tier IV",
            },
            support_summary={
                "item_name": {"support_state": "weak", "support_count": 1, "best_confidence": 0.7, "frame_hint": "f1"},
                    "item_type": {"support_state": "weak", "support_count": 1, "best_confidence": 0.7, "frame_hint": "f1"},
                    "item_rarity": {"support_state": "weak", "support_count": 1, "best_confidence": 0.7, "frame_hint": "f1"},
            },
            source_frame_ids=("f1",),
            source_row_ids=("f1:row:2",),
            missing_fields=(FieldKind.ITEM_COUNT,),
        ),
    )

    continuity = build_continuity_records(records, profile_id="defiance", frame_order={"f1": 0})

    assert len(continuity) == 1
    assert continuity[0].state is ContinuityState.WEAK
    assert continuity[0].progression_state is ContinuityProgressionState.STATIONARY
    assert "LOW_TEMPORAL_SUPPORT" in continuity[0].reasons


def test_build_continuity_records_groups_same_identity_across_row_slot_shift() -> None:
    records = (
        AssembledCandidateRecord(
            row_slot=1,
            profile_id="defiance",
            state=RecordAssemblyState.COMPLETE,
            fields={
                FieldKind.ITEM_NAME: "Power Bore",
                FieldKind.ITEM_TYPE: "Rocket Launcher",
                FieldKind.ITEM_RARITY: "Tier IV",
            },
            support_summary={
                "item_name": {"support_state": "supported", "support_count": 2, "best_confidence": 0.8, "frame_hint": "f1"},
                "item_type": {"support_state": "supported", "support_count": 2, "best_confidence": 0.8, "frame_hint": "f1"},
                "item_rarity": {"support_state": "supported", "support_count": 2, "best_confidence": 0.8, "frame_hint": "f1"},
            },
            source_frame_ids=("f1",),
            source_row_ids=("f1:row:1",),
            missing_fields=(),
        ),
        AssembledCandidateRecord(
            row_slot=2,
            profile_id="defiance",
            state=RecordAssemblyState.COMPLETE,
            fields={
                FieldKind.ITEM_NAME: "Power Bore",
                FieldKind.ITEM_TYPE: "Rocket Launcher",
                FieldKind.ITEM_RARITY: "Tier IV",
            },
            support_summary={
                "item_name": {"support_state": "supported", "support_count": 2, "best_confidence": 0.85, "frame_hint": "f2"},
                "item_type": {"support_state": "supported", "support_count": 2, "best_confidence": 0.85, "frame_hint": "f2"},
                "item_rarity": {"support_state": "supported", "support_count": 2, "best_confidence": 0.85, "frame_hint": "f2"},
            },
            source_frame_ids=("f2",),
            source_row_ids=("f2:row:2",),
            missing_fields=(),
        ),
    )

    continuity = build_continuity_records(records, profile_id="defiance", frame_order={"f1": 0, "f2": 1})

    assert len(continuity) == 1
    assert continuity[0].state is ContinuityState.STABLE
    assert continuity[0].progression_state is ContinuityProgressionState.SLOT_INCREASE
    assert continuity[0].row_slots == (1, 2)
    assert "ROW_SLOT_SHIFT_DETECTED" in continuity[0].reasons
    assert continuity[0].frame_ids == ("f1", "f2")
    assert continuity[0].sightings == (("f1", 1), ("f2", 2))


def test_analyze_frame_overlaps_detects_partial_overlap_and_stabilizes_progression() -> None:
    records = (
        AssembledCandidateRecord(
            row_slot=5,
            profile_id="defiance",
            state=RecordAssemblyState.COMPLETE,
            fields={
                FieldKind.ITEM_NAME: "Bravo",
                FieldKind.ITEM_TYPE: "Rocket Launcher",
                FieldKind.ITEM_RARITY: "Tier IV",
                FieldKind.ITEM_COUNT: "2",
            },
            support_summary={
                "item_name": {"support_state": "weak", "support_count": 1, "best_confidence": 0.8, "frame_hint": "f1", "source_row_ids": ("f1:row:5",)},
                "item_type": {"support_state": "weak", "support_count": 1, "best_confidence": 0.8, "frame_hint": "f1", "source_row_ids": ("f1:row:5",)},
                "item_rarity": {"support_state": "weak", "support_count": 1, "best_confidence": 0.8, "frame_hint": "f1", "source_row_ids": ("f1:row:5",)},
                "item_count": {"support_state": "weak", "support_count": 1, "best_confidence": 0.8, "frame_hint": "f1", "source_row_ids": ("f1:row:5",)},
            },
            source_frame_ids=("f1",),
            source_row_ids=("f1:row:5",),
            missing_fields=(),
        ),
        AssembledCandidateRecord(
            row_slot=1,
            profile_id="defiance",
            state=RecordAssemblyState.COMPLETE,
            fields={
                FieldKind.ITEM_NAME: "Bravo",
                FieldKind.ITEM_TYPE: "Rocket Launcher",
                FieldKind.ITEM_RARITY: "Tier IV",
                FieldKind.ITEM_COUNT: "2",
            },
            support_summary={
                "item_name": {"support_state": "weak", "support_count": 1, "best_confidence": 0.82, "frame_hint": "f2", "source_row_ids": ("f2:row:1",)},
                "item_type": {"support_state": "weak", "support_count": 1, "best_confidence": 0.82, "frame_hint": "f2", "source_row_ids": ("f2:row:1",)},
                "item_rarity": {"support_state": "weak", "support_count": 1, "best_confidence": 0.82, "frame_hint": "f2", "source_row_ids": ("f2:row:1",)},
                "item_count": {"support_state": "weak", "support_count": 1, "best_confidence": 0.82, "frame_hint": "f2", "source_row_ids": ("f2:row:1",)},
            },
            source_frame_ids=("f2",),
            source_row_ids=("f2:row:1",),
            missing_fields=(),
        ),
        AssembledCandidateRecord(
            row_slot=6,
            profile_id="defiance",
            state=RecordAssemblyState.COMPLETE,
            fields={
                FieldKind.ITEM_NAME: "Charlie",
                FieldKind.ITEM_TYPE: "Shotgun",
                FieldKind.ITEM_RARITY: "Tier III",
                FieldKind.ITEM_COUNT: "1",
            },
            support_summary={
                "item_name": {"support_state": "weak", "support_count": 1, "best_confidence": 0.78, "frame_hint": "f1", "source_row_ids": ("f1:row:6",)},
                "item_type": {"support_state": "weak", "support_count": 1, "best_confidence": 0.78, "frame_hint": "f1", "source_row_ids": ("f1:row:6",)},
                "item_rarity": {"support_state": "weak", "support_count": 1, "best_confidence": 0.78, "frame_hint": "f1", "source_row_ids": ("f1:row:6",)},
                "item_count": {"support_state": "weak", "support_count": 1, "best_confidence": 0.78, "frame_hint": "f1", "source_row_ids": ("f1:row:6",)},
            },
            source_frame_ids=("f1",),
            source_row_ids=("f1:row:6",),
            missing_fields=(),
        ),
        AssembledCandidateRecord(
            row_slot=2,
            profile_id="defiance",
            state=RecordAssemblyState.COMPLETE,
            fields={
                FieldKind.ITEM_NAME: "Charlie",
                FieldKind.ITEM_TYPE: "Shotgun",
                FieldKind.ITEM_RARITY: "Tier III",
                FieldKind.ITEM_COUNT: "1",
            },
            support_summary={
                "item_name": {"support_state": "weak", "support_count": 1, "best_confidence": 0.81, "frame_hint": "f2", "source_row_ids": ("f2:row:2",)},
                "item_type": {"support_state": "weak", "support_count": 1, "best_confidence": 0.81, "frame_hint": "f2", "source_row_ids": ("f2:row:2",)},
                "item_rarity": {"support_state": "weak", "support_count": 1, "best_confidence": 0.81, "frame_hint": "f2", "source_row_ids": ("f2:row:2",)},
                "item_count": {"support_state": "weak", "support_count": 1, "best_confidence": 0.81, "frame_hint": "f2", "source_row_ids": ("f2:row:2",)},
            },
            source_frame_ids=("f2",),
            source_row_ids=("f2:row:2",),
            missing_fields=(),
        ),
        AssembledCandidateRecord(
            row_slot=4,
            profile_id="defiance",
            state=RecordAssemblyState.COMPLETE,
            fields={
                FieldKind.ITEM_NAME: "Alpha",
                FieldKind.ITEM_TYPE: "Pistol",
                FieldKind.ITEM_RARITY: "Tier II",
                FieldKind.ITEM_COUNT: "1",
            },
            support_summary={
                "item_name": {"support_state": "weak", "support_count": 1, "best_confidence": 0.76, "frame_hint": "f1", "source_row_ids": ("f1:row:4",)},
                "item_type": {"support_state": "weak", "support_count": 1, "best_confidence": 0.76, "frame_hint": "f1", "source_row_ids": ("f1:row:4",)},
                "item_rarity": {"support_state": "weak", "support_count": 1, "best_confidence": 0.76, "frame_hint": "f1", "source_row_ids": ("f1:row:4",)},
                "item_count": {"support_state": "weak", "support_count": 1, "best_confidence": 0.76, "frame_hint": "f1", "source_row_ids": ("f1:row:4",)},
            },
            source_frame_ids=("f1",),
            source_row_ids=("f1:row:4",),
            missing_fields=(),
        ),
        AssembledCandidateRecord(
            row_slot=3,
            profile_id="defiance",
            state=RecordAssemblyState.COMPLETE,
            fields={
                FieldKind.ITEM_NAME: "Delta",
                FieldKind.ITEM_TYPE: "SMG",
                FieldKind.ITEM_RARITY: "Tier I",
                FieldKind.ITEM_COUNT: "1",
            },
            support_summary={
                "item_name": {"support_state": "weak", "support_count": 1, "best_confidence": 0.79, "frame_hint": "f2", "source_row_ids": ("f2:row:3",)},
                "item_type": {"support_state": "weak", "support_count": 1, "best_confidence": 0.79, "frame_hint": "f2", "source_row_ids": ("f2:row:3",)},
                "item_rarity": {"support_state": "weak", "support_count": 1, "best_confidence": 0.79, "frame_hint": "f2", "source_row_ids": ("f2:row:3",)},
                "item_count": {"support_state": "weak", "support_count": 1, "best_confidence": 0.79, "frame_hint": "f2", "source_row_ids": ("f2:row:3",)},
            },
            source_frame_ids=("f2",),
            source_row_ids=("f2:row:3",),
            missing_fields=(),
        ),
    )

    continuity = build_continuity_records(records, profile_id="defiance", frame_order={"f1": 0, "f2": 1})
    continuity, overlaps, overlap_count, overlap_confidence, continuity_summary = analyze_frame_overlaps(
        continuity,
        frame_order={"f1": 0, "f2": 1},
    )

    assert len(overlaps) == 1
    assert overlaps[0].frame_a_id == "f1"
    assert overlaps[0].frame_b_id == "f2"
    assert overlaps[0].overlap_rows == ((5, 1), (6, 2))
    assert overlap_count == 2
    assert overlap_confidence == 1.0
    assert continuity_summary == "OVERLAP_DETECTED"

    by_name = {record.fields[FieldKind.ITEM_NAME]: record for record in continuity}
    assert by_name["Bravo"].progression_state is ContinuityProgressionState.STATIONARY
    assert by_name["Charlie"].progression_state is ContinuityProgressionState.STATIONARY
    assert "FRAME_OVERLAP_CONFIRMED" in by_name["Bravo"].reasons
    assert by_name["Alpha"].progression_state is ContinuityProgressionState.STATIONARY
    assert by_name["Delta"].progression_state is ContinuityProgressionState.STATIONARY


def test_analyze_frame_overlaps_keeps_weak_overlap_directional() -> None:
    records = (
        AssembledCandidateRecord(
            row_slot=5,
            profile_id="defiance",
            state=RecordAssemblyState.PARTIAL,
            fields={FieldKind.ITEM_NAME: "Bravo"},
            support_summary={
                "item_name": {"support_state": "weak", "support_count": 1, "best_confidence": 0.8, "frame_hint": "f1"},
            },
            source_frame_ids=("f1",),
            source_row_ids=("f1:row:5",),
            missing_fields=(FieldKind.ITEM_TYPE, FieldKind.ITEM_RARITY, FieldKind.ITEM_COUNT),
        ),
        AssembledCandidateRecord(
            row_slot=1,
            profile_id="defiance",
            state=RecordAssemblyState.PARTIAL,
            fields={FieldKind.ITEM_NAME: "Bravo"},
            support_summary={
                "item_name": {"support_state": "weak", "support_count": 1, "best_confidence": 0.81, "frame_hint": "f2"},
            },
            source_frame_ids=("f2",),
            source_row_ids=("f2:row:1",),
            missing_fields=(FieldKind.ITEM_TYPE, FieldKind.ITEM_RARITY, FieldKind.ITEM_COUNT),
        ),
    )

    continuity = build_continuity_records(records, profile_id="defiance", frame_order={"f1": 0, "f2": 1})
    continuity, overlaps, overlap_count, overlap_confidence, continuity_summary = analyze_frame_overlaps(
        continuity,
        frame_order={"f1": 0, "f2": 1},
    )

    assert len(overlaps) == 1
    assert overlap_count == 1
    assert overlap_confidence == 0.25
    assert continuity_summary == "OVERLAP_WEAK"
    assert continuity[0].progression_state is ContinuityProgressionState.SLOT_DECREASE
    assert "FRAME_OVERLAP_CONFIRMED" not in continuity[0].reasons
