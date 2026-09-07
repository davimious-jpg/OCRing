from __future__ import annotations

import json
from pathlib import Path

from ocring.ocr.assembler import apply_defiance_semantic_notes
from ocring.ocr.correctness_engine import CorrectnessEngine
from ocring.ocr.defiance_semantic import DefianceSemantic
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


def test_defiance_semantic_slot_compatibility_and_warnings(tmp_path: Path) -> None:
    profile_path = tmp_path / "profiles" / "defiance" / "profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        json.dumps(
            {
                "mod_slot_compatibility": {
                    "scope": ["assault_rifle", "sniper_rifle"],
                    "scope_unsupported": ["infector"],
                },
                "rarity_definitions": {
                    "Tier IV": {"color_name": "Purple", "color_hex": "#9c27b0", "label": "Epic"},
                },
            }
        ),
        encoding="utf-8",
    )

    semantic = DefianceSemantic.load(profile_path)

    assert semantic.is_slot_compatible("Scope", "Assault Rifle") is True
    assert semantic.is_slot_compatible("Scope", "Infector") is False
    assert semantic.get_supported_slots("Assault Rifle") == ["scope"]
    assert semantic.get_unsupported_slots("Infector") == ["scope"]
    warning = semantic.detect_slot_compatibility_warning("Scope", "Infector")
    assert warning is not None
    assert "Scope mod on Infector" in warning.message


def test_defiance_semantic_detects_rarity_conflict() -> None:
    semantic = DefianceSemantic.load()

    conflict = semantic.detect_rarity_conflict("Tier IV", "Blue")

    assert conflict is not None
    assert conflict.expected_color == "Purple"
    assert "Tier IV" in conflict.message


def test_correctness_engine_emits_first_class_semantic_states() -> None:
    ranked_candidates = (
        RankedFieldCandidate(
            row_id="f1:row:1",
            field_kind=FieldKind.ITEM_RARITY,
            candidate_value="Tier IV",
            source_crop_id="crop-rarity",
            source_variant=PreprocessVariant.GRAYSCALE,
            source_engine="classic_ocr",
            decision=CandidateDecision.SELECTED,
            confidence=0.88,
            reasons=(),
        ),
        RankedFieldCandidate(
            row_id="f1:row:1",
            field_kind=FieldKind.ITEM_TYPE,
            candidate_value="Infector",
            source_crop_id="crop-type",
            source_variant=PreprocessVariant.GRAYSCALE,
            source_engine="classic_ocr",
            decision=CandidateDecision.SELECTED,
            confidence=0.81,
            reasons=(),
        ),
    )
    temporal_aggregates = (
        TemporalFieldAggregate(
            temporal_key="1:item_rarity:Tier IV",
            row_slot=1,
            field_kind=FieldKind.ITEM_RARITY,
            candidate_value="Tier IV",
            support_state=TemporalSupportState.SUPPORTED,
            support_count=3,
            independent_support_count=3,
            best_confidence=0.88,
            contributing_frame_ids=("f1", "f2", "f3"),
            contributing_row_ids=("f1:row:1", "f2:row:1", "f3:row:1"),
        ),
        TemporalFieldAggregate(
            temporal_key="1:item_type:Infector",
            row_slot=1,
            field_kind=FieldKind.ITEM_TYPE,
            candidate_value="Infector",
            support_state=TemporalSupportState.SUPPORTED,
            support_count=3,
            independent_support_count=3,
            best_confidence=0.81,
            contributing_frame_ids=("f1", "f2", "f3"),
            contributing_row_ids=("f1:row:1", "f2:row:1", "f3:row:1"),
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
                FieldKind.ITEM_COUNT: "1",
                FieldKind.ITEM_TYPE: "Infector",
            },
            support_summary={
                "item_rarity": {
                    "best_confidence": 0.88,
                    "support_count": 3,
                    "source_frame_ids": ("f1", "f2", "f3"),
                    "source_crop_ids": ("crop-r1", "crop-r2", "crop-r3"),
                },
                "item_type": {
                    "best_confidence": 0.81,
                    "support_count": 3,
                    "source_frame_ids": ("f1", "f2", "f3"),
                    "source_crop_ids": ("crop-t1", "crop-t2", "crop-t3"),
                },
            },
            source_frame_ids=("f1", "f2", "f3"),
            source_row_ids=("f1:row:1", "f2:row:1", "f3:row:1"),
            missing_fields=(),
            field_details={
                "item_rarity": {"observed_color": "Blue", "source_text": "Tier IV"},
                "mod_slot": {"source_text": "Scope"},
            },
        ),
    )
    continuity_records = (
        ContinuityRecord(
            continuity_key="key-1",
            profile_id="defiance",
            row_slots=(1,),
            state=ContinuityState.STABLE,
            progression_state=ContinuityProgressionState.STATIONARY,
            support_count=3,
            frame_ids=("f1", "f2", "f3"),
            source_record_count=3,
            sightings=(("f1", 1), ("f2", 1), ("f3", 1)),
            fields={
                FieldKind.ITEM_NAME: "Power Bore",
                FieldKind.ITEM_RARITY: "Tier IV",
                FieldKind.ITEM_COUNT: "1",
                FieldKind.ITEM_TYPE: "Infector",
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

    states = {entry["field_kind"]: entry["state"] for entry in result["field_correctness"]}
    assert states["item_rarity"] == "RARITY_CONFLICT"
    assert states["item_type"] == "COMPATIBILITY_WARNING"


def test_assembler_adds_semantic_notes() -> None:
    record = AssembledCandidateRecord(
        row_slot=1,
        profile_id="defiance",
        state=RecordAssemblyState.COMPLETE,
        fields={
            FieldKind.ITEM_NAME: "Power Bore",
            FieldKind.ITEM_RARITY: "Tier IV",
            FieldKind.ITEM_COUNT: "1",
            FieldKind.ITEM_TYPE: "Infector",
        },
        support_summary={},
        source_frame_ids=("f1",),
        source_row_ids=("f1:row:1",),
        missing_fields=(),
        field_details={
            "item_rarity": {"observed_color": "Blue", "source_text": "Tier IV"},
            "mod_slot": {"source_text": "Scope"},
        },
    )

    enriched = apply_defiance_semantic_notes((record,))

    assert any(note.startswith("Rarity conflict:") for note in enriched[0].semantic_notes)
    assert any(note.startswith("Slot compatibility warning:") for note in enriched[0].semantic_notes)
