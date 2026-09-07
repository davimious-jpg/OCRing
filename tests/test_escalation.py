from __future__ import annotations

from pathlib import Path

from ocring.ocr.calibration import CalibrationStore
from ocring.ocr.correctness_engine import CorrectnessEngine
from ocring.ocr.models import (
    AssembledCandidateRecord,
    CandidateDecision,
    ContinuityProgressionState,
    ContinuityRecord,
    ContinuityState,
    FieldKind,
    PreprocessVariant,
    RankedFieldCandidate,
    RecordAssemblyState,
    TemporalFieldAggregate,
    TemporalSupportState,
)


def test_escalation_chain_routes_weak_low_confidence_field_to_local_and_api_then_review(tmp_path: Path) -> None:
    engine = CorrectnessEngine(
        calibration_store=CalibrationStore(tmp_path / "calibration.db", min_verified_corrections=2),
        allow_api_escalation=True,
    )
    ranked_candidates = (
        RankedFieldCandidate(
            row_id="f1:row:1",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Power Bore",
            source_crop_id="crop-1",
            source_variant=PreprocessVariant.GRAYSCALE,
            source_engine="classic_ocr",
            decision=CandidateDecision.SELECTED,
            confidence=0.55,
            reasons=(),
        ),
    )
    temporal_aggregates = (
        TemporalFieldAggregate(
            temporal_key="1:item_name:Power Bore",
            row_slot=1,
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Power Bore",
            support_state=TemporalSupportState.WEAK,
            support_count=1,
            independent_support_count=1,
            best_confidence=0.55,
            contributing_frame_ids=("f1",),
            contributing_row_ids=("f1:row:1",),
        ),
    )
    assembled_records = (
        AssembledCandidateRecord(
            row_slot=1,
            profile_id="defiance",
            state=RecordAssemblyState.PARTIAL,
            fields={FieldKind.ITEM_NAME: "Power Bore"},
            support_summary={
                "item_name": {
                    "best_confidence": 0.55,
                    "support_count": 1,
                    "source_frame_ids": ("f1",),
                    "source_crop_ids": ("crop-1",),
                }
            },
            source_frame_ids=("f1",),
            source_row_ids=("f1:row:1",),
            missing_fields=(FieldKind.ITEM_RARITY, FieldKind.ITEM_COUNT, FieldKind.ITEM_TYPE),
        ),
    )
    continuity_records = (
        ContinuityRecord(
            continuity_key="weak-1",
            profile_id="defiance",
            row_slots=(1,),
            state=ContinuityState.WEAK,
            progression_state=ContinuityProgressionState.STATIONARY,
            support_count=1,
            frame_ids=("f1",),
            source_record_count=1,
            sightings=(("f1", 1),),
            fields={FieldKind.ITEM_NAME: "Power Bore"},
            reasons=("LOW_TEMPORAL_SUPPORT",),
        ),
    )

    result = engine.evaluate(
        ranked_candidates=ranked_candidates,
        temporal_aggregates=temporal_aggregates,
        assembled_records=assembled_records,
        continuity_records=continuity_records,
        profile_id="defiance",
    )

    chain = result["field_correctness"][0]["escalation_chain"]
    assert "local_ai" in chain
    assert "api_ai" in chain
    assert "NEEDS_REVIEW" in chain
    assert result["escalation_chain"]
