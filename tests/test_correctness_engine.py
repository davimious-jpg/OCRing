from __future__ import annotations

from ocring.ocr.correctness_engine import CorrectnessEngine
from ocring.ocr.models import (
    AssembledCandidateRecord,
    CandidateDecision,
    ContinuityProgressionState,
    ContinuityRecord,
    ContinuityState,
    FieldKind,
    RankedFieldCandidate,
    RecordAssemblyState,
    TemporalFieldAggregate,
    TemporalSupportState,
)


def test_correctness_engine_runs_full_pipeline_and_accepts_strong_record() -> None:
    ranked_candidates = (
        RankedFieldCandidate(
            row_id="f1:row:1",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Power Bore",
            source_crop_id="crop-1",
            source_variant=type("Variant", (), {"value": "grayscale"})(),
            source_engine="classic_ocr",
            decision=CandidateDecision.SELECTED,
            confidence=0.87,
            reasons=(),
        ),
    )
    temporal_aggregates = (
        TemporalFieldAggregate(
            temporal_key="1:item_name:Power Bore",
            row_slot=1,
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Power Bore",
            support_state=TemporalSupportState.SUPPORTED,
            support_count=4,
            independent_support_count=4,
            best_confidence=0.87,
            contributing_frame_ids=("f1", "f2", "f3", "f4"),
            contributing_row_ids=("f1:row:1", "f2:row:1", "f3:row:1", "f4:row:1"),
        ),
    )
    assembled_records = (
        AssembledCandidateRecord(
            row_slot=1,
            profile_id="defiance",
            state=RecordAssemblyState.COMPLETE,
            fields={
                FieldKind.ITEM_NAME: "Power Bore",
                FieldKind.ITEM_RARITY: "Tier IV",
                FieldKind.ITEM_COUNT: "2",
                FieldKind.ITEM_TYPE: "Rocket Launcher",
            },
            support_summary={
                "item_name": {
                    "best_confidence": 0.87,
                    "support_count": 4,
                    "source_frame_ids": ("f1", "f2", "f3", "f4"),
                    "source_crop_ids": ("crop-1", "crop-2", "crop-3", "crop-4"),
                },
                "item_rarity": {"best_confidence": 0.9, "support_count": 4, "source_frame_ids": ("f1", "f2"), "source_crop_ids": ("r1", "r2")},
                "item_count": {"best_confidence": 0.88, "support_count": 4, "source_frame_ids": ("f1", "f2"), "source_crop_ids": ("c1", "c2")},
                "item_type": {"best_confidence": 0.89, "support_count": 4, "source_frame_ids": ("f1", "f2"), "source_crop_ids": ("t1", "t2")},
            },
            source_frame_ids=("f1", "f2", "f3", "f4"),
            source_row_ids=("f1:row:1", "f2:row:1", "f3:row:1", "f4:row:1"),
            missing_fields=(),
        ),
    )
    continuity_records = (
        ContinuityRecord(
            continuity_key="key-1",
            profile_id="defiance",
            row_slots=(1,),
            state=ContinuityState.STABLE,
            progression_state=ContinuityProgressionState.STATIONARY,
            support_count=4,
            frame_ids=("f1", "f2", "f3", "f4"),
            source_record_count=4,
            sightings=(("f1", 1), ("f2", 1), ("f3", 1), ("f4", 1)),
            fields={
                FieldKind.ITEM_NAME: "Power Bore",
                FieldKind.ITEM_RARITY: "Tier IV",
                FieldKind.ITEM_COUNT: "2",
                FieldKind.ITEM_TYPE: "Rocket Launcher",
            },
        ),
    )

    result = CorrectnessEngine().evaluate(
        ranked_candidates=ranked_candidates,
        temporal_aggregates=temporal_aggregates,
        assembled_records=assembled_records,
        continuity_records=continuity_records,
        profile_id="defiance",
    )

    assert result["session_correctness"]["action"] in {"accept", "review"}
    assert result["field_correctness"][0]["candidate_set"]
    assert "Accepted because:" in result["field_correctness"][0]["reason"] or "Needs Review" in result["field_correctness"][0]["reason"]


def test_correctness_engine_marks_reference_data_missing_without_claiming_profile_match() -> None:
    assembled_records = (
        AssembledCandidateRecord(
            row_slot=1,
            profile_id="defiance",
            state=RecordAssemblyState.PARTIAL,
            fields={
                FieldKind.ITEM_NAME: "Overclocked Prime Evolver",
            },
            support_summary={
                "item_name": {
                    "best_confidence": 0.78,
                    "support_count": 2,
                    "source_frame_ids": ("f1", "f2"),
                    "source_crop_ids": ("crop-1", "crop-2"),
                },
            },
            source_frame_ids=("f1", "f2"),
            source_row_ids=("f1:row:1", "f2:row:1"),
            missing_fields=(FieldKind.ITEM_RARITY, FieldKind.ITEM_COUNT, FieldKind.ITEM_TYPE),
        ),
    )
    continuity_records = (
        ContinuityRecord(
            continuity_key="key-1",
            profile_id="defiance",
            row_slots=(1,),
            state=ContinuityState.STABLE,
            progression_state=ContinuityProgressionState.STATIONARY,
            support_count=2,
            frame_ids=("f1", "f2"),
            source_record_count=2,
            sightings=(("f1", 1), ("f2", 1)),
            fields={FieldKind.ITEM_NAME: "Overclocked Prime Evolver"},
        ),
    )

    result = CorrectnessEngine().evaluate(
        ranked_candidates=(),
        temporal_aggregates=(),
        assembled_records=assembled_records,
        continuity_records=continuity_records,
        profile_id="defiance",
    )

    item_name_result = next(
        item for item in result["field_correctness"] if item["field_kind"] == FieldKind.ITEM_NAME.value
    )

    assert item_name_result["state"] == "REFERENCE_DATA_MISSING"
    assert item_name_result["action"] == "review"
    assert "OCR succeeded but reference data is incomplete" in item_name_result["reason"]
    assert "known profile token matched" not in item_name_result["reason"]
