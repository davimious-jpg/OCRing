from __future__ import annotations

from ocring.ocr.assembler import assemble_candidate_records, merge_allocation_fields
from ocring.ocr.models import FieldKind, RecordAssemblyState, TemporalFieldAggregate, TemporalSupportState


class _WeaponModDefinitionEngine:
    def determine_record_class(self, _fields: dict[str, str]) -> str:
        return "WeaponMod"

    def get_required_fields(self, record_class: str) -> list[str]:
        assert record_class == "WeaponMod"
        return ["item_name"]


def test_assemble_candidate_records_marks_complete_when_required_fields_exist() -> None:
    aggregates = (
        TemporalFieldAggregate(
            temporal_key="1:item_name:Power Bore",
            row_slot=1,
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Power Bore",
            support_state=TemporalSupportState.SUPPORTED,
            support_count=2,
            independent_support_count=2,
            best_confidence=0.8,
            contributing_frame_ids=("f1", "f2"),
            contributing_row_ids=("f1:row:1", "f2:row:1"),
            contributing_crop_ids=("crop-a", "crop-b"),
        ),
        TemporalFieldAggregate(
            temporal_key="1:item_rarity:Tier IV",
            row_slot=1,
            field_kind=FieldKind.ITEM_RARITY,
            candidate_value="Tier IV",
            support_state=TemporalSupportState.SUPPORTED,
            support_count=2,
            independent_support_count=2,
            best_confidence=0.75,
            contributing_frame_ids=("f1", "f2"),
            contributing_row_ids=("f1:row:1", "f2:row:1"),
            contributing_crop_ids=("crop-c", "crop-d"),
        ),
        TemporalFieldAggregate(
            temporal_key="1:item_count:2",
            row_slot=1,
            field_kind=FieldKind.ITEM_COUNT,
            candidate_value="2",
            support_state=TemporalSupportState.WEAK,
            support_count=1,
            independent_support_count=1,
            best_confidence=0.6,
            contributing_frame_ids=("f1",),
            contributing_row_ids=("f1:row:1",),
            contributing_crop_ids=("crop-e",),
        ),
        TemporalFieldAggregate(
            temporal_key="1:item_type:Rocket Launcher",
            row_slot=1,
            field_kind=FieldKind.ITEM_TYPE,
            candidate_value="Rocket Launcher",
            support_state=TemporalSupportState.SUPPORTED,
            support_count=2,
            independent_support_count=2,
            best_confidence=0.85,
            contributing_frame_ids=("f1", "f2"),
            contributing_row_ids=("f1:row:1", "f2:row:1"),
            contributing_crop_ids=("crop-f", "crop-g"),
        ),
    )

    records = assemble_candidate_records(aggregates, profile_id="defiance")

    assert len(records) == 1
    assert records[0].state is RecordAssemblyState.COMPLETE
    assert records[0].fields[FieldKind.ITEM_NAME] == "Power Bore"
    assert set(records[0].source_frame_ids) == {"f1", "f2"}
    assert "f1:row:1" in records[0].source_row_ids
    assert records[0].support_summary["item_name"]["source_crop_ids"] == ("crop-a", "crop-b")
    assert not records[0].missing_fields


def test_assemble_candidate_records_marks_conflicted_when_selected_field_conflicts() -> None:
    aggregates = (
        TemporalFieldAggregate(
            temporal_key="2:item_name:Power Bore",
            row_slot=2,
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Power Bore",
            support_state=TemporalSupportState.CONFLICTED,
            support_count=1,
            independent_support_count=1,
            best_confidence=0.8,
            contributing_frame_ids=("f1", "f2"),
            contributing_row_ids=("f1:row:2", "f2:row:2"),
            reasons=("TEMPORAL_VALUE_CONFLICT",),
        ),
        TemporalFieldAggregate(
            temporal_key="2:item_rarity:Tier IV",
            row_slot=2,
            field_kind=FieldKind.ITEM_RARITY,
            candidate_value="Tier IV",
            support_state=TemporalSupportState.SUPPORTED,
            support_count=2,
            independent_support_count=2,
            best_confidence=0.75,
            contributing_frame_ids=("f1", "f2"),
            contributing_row_ids=("f1:row:2", "f2:row:2"),
        ),
    )

    records = assemble_candidate_records(aggregates, profile_id="defiance")

    assert len(records) == 1
    assert records[0].state is RecordAssemblyState.CONFLICTED
    assert set(records[0].source_frame_ids) == {"f1", "f2"}
    assert "ITEM_NAME_TEMPORAL_CONFLICT" in records[0].reasons


def test_conflicted_item_name_remains_unknown_until_independently_supported() -> None:
    aggregates = (
        TemporalFieldAggregate(
            temporal_key="1:item_name:AMenclad RelpaderVARK",
            row_slot=1,
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="AMenclad RelpaderVARK",
            support_state=TemporalSupportState.CONFLICTED,
            support_count=1,
            independent_support_count=1,
            best_confidence=0.607,
            contributing_frame_ids=("session-52571336-frame-000026",),
            contributing_row_ids=("session-52571336-frame-000026:row:1",),
            contributing_crop_ids=("740f1deb295a737bf7a4",),
            reasons=("TEMPORAL_VALUE_CONFLICT",),
        ),
    )

    records = assemble_candidate_records(aggregates, profile_id="defiance")

    assert records[0].state is RecordAssemblyState.CONFLICTED
    assert records[0].fields[FieldKind.ITEM_NAME] == "UNKNOWN"
    assert records[0].field_details["item_name"]["source_text"] == "UNKNOWN"
    assert records[0].field_details["item_name"]["raw_observation"] == "AMenclad RelpaderVARK"
    assert records[0].field_details["item_name"]["status"] == "UNRESOLVED_IDENTITY"
    assert records[0].field_details["item_name"]["direct_observation"] is False
    assert records[0].support_summary["item_name"]["source_crop_ids"] == ("740f1deb295a737bf7a4",)
    assert "ITEM_NAME_UNRESOLVED_IDENTITY" in records[0].reasons


def test_stable_observed_item_name_survives_missing_reference_data() -> None:
    aggregates = (
        TemporalFieldAggregate(
            temporal_key="8:item_name:Scatter Scope V",
            row_slot=8,
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Scatter Scope V",
            support_state=TemporalSupportState.SUPPORTED,
            support_count=2,
            independent_support_count=2,
            best_confidence=0.704,
            contributing_frame_ids=("frame-1", "frame-2"),
            contributing_row_ids=("frame-1:row:8", "frame-2:row:8"),
            contributing_crop_ids=("crop-1", "crop-2"),
            reasons=("REFERENCE_DATA_MISSING",),
        ),
    )

    records = assemble_candidate_records(aggregates, profile_id="defiance")

    assert records[0].fields[FieldKind.ITEM_NAME] == "Scatter Scope V"
    assert records[0].field_details["item_name"]["source_text"] == "Scatter Scope V"
    assert records[0].field_details["item_name"]["raw_observation"] == "Scatter Scope V"
    assert records[0].field_details["item_name"]["status"] == "OBSERVED_STABLE"
    assert records[0].field_details["item_name"]["identity_status"] == "OBSERVED_STABLE"
    assert records[0].field_details["item_name"]["reference_status"] == "REFERENCE_DATA_MISSING"
    assert records[0].field_details["item_name"]["direct_observation"] is True
    assert "ITEM_NAME_UNRESOLVED_IDENTITY" not in records[0].reasons


def test_assemble_candidate_records_uses_profile_required_fields_for_weapon_mod() -> None:
    aggregates = (
        TemporalFieldAggregate(
            temporal_key="10:item_name:Shotgun Hip Spread V",
            row_slot=10,
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Shotgun Hip Spread V",
            support_state=TemporalSupportState.SUPPORTED,
            support_count=2,
            independent_support_count=2,
            best_confidence=0.892,
            contributing_frame_ids=("frame-1", "frame-2"),
            contributing_row_ids=("frame-1:row:10", "frame-2:row:10"),
            contributing_crop_ids=("crop-1", "crop-2"),
            reasons=("REFERENCE_DATA_MISSING",),
        ),
    )

    records = assemble_candidate_records(
        aggregates,
        profile_id="defiance",
        definition_engine=_WeaponModDefinitionEngine(),
    )

    assert records[0].definition_used == "WeaponMod"
    assert records[0].state is RecordAssemblyState.COMPLETE
    assert records[0].missing_fields == ()
    assert records[0].fields[FieldKind.ITEM_NAME] == "Shotgun Hip Spread V"


def test_unresolved_item_name_is_not_reused_as_semantic_fragment() -> None:
    from ocring.ocr.pipeline import _assembled_semantic_fragments, _has_unresolved_item_name_identity

    aggregates = (
        TemporalFieldAggregate(
            temporal_key="1:item_name:AMenclad RelpaderVARK",
            row_slot=1,
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="AMenclad RelpaderVARK",
            support_state=TemporalSupportState.WEAK,
            support_count=1,
            independent_support_count=1,
            best_confidence=0.607,
            contributing_frame_ids=("session-52571336-frame-000026",),
            contributing_row_ids=("session-52571336-frame-000026:row:1",),
            contributing_crop_ids=("740f1deb295a737bf7a4",),
        ),
    )

    record = assemble_candidate_records(aggregates, profile_id="defiance")[0]

    assert _has_unresolved_item_name_identity(record) is True
    assert _assembled_semantic_fragments(record) == ()


def test_merge_allocation_fields_backfills_item_type_from_mod_slot() -> None:
    aggregates = (
        TemporalFieldAggregate(
            temporal_key="3:item_name:Critical Force Barrel IV",
            row_slot=3,
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Critical Force Barrel IV",
            support_state=TemporalSupportState.SUPPORTED,
            support_count=2,
            independent_support_count=2,
            best_confidence=0.86,
            contributing_frame_ids=("f1",),
            contributing_row_ids=("f1:row:3",),
        ),
        TemporalFieldAggregate(
            temporal_key="3:item_rarity:Epic",
            row_slot=3,
            field_kind=FieldKind.ITEM_RARITY,
            candidate_value="Epic",
            support_state=TemporalSupportState.SUPPORTED,
            support_count=2,
            independent_support_count=2,
            best_confidence=0.84,
            contributing_frame_ids=("f1",),
            contributing_row_ids=("f1:row:3",),
        ),
        TemporalFieldAggregate(
            temporal_key="3:item_count:1",
            row_slot=3,
            field_kind=FieldKind.ITEM_COUNT,
            candidate_value="1",
            support_state=TemporalSupportState.SUPPORTED,
            support_count=2,
            independent_support_count=2,
            best_confidence=0.82,
            contributing_frame_ids=("f1",),
            contributing_row_ids=("f1:row:3",),
        ),
    )

    records = assemble_candidate_records(aggregates, profile_id="defiance")
    merged = merge_allocation_fields(
        records,
        {
            # Keyed by temporal_identity_id now, not row_slot; the
            # legacy (non-recorded) assembly path sets it to str(row_slot).
            "3": {
                "field_values": {
                    "item_synergy": "Ether Acceleration",
                    "mod_slot": "Barrel",
                },
                "confidence": 0.91,
            }
        },
    )

    assert merged[0].fields[FieldKind.ITEM_TYPE] == "Barrel"
    assert merged[0].fields[FieldKind.ITEM_SYNERGY] == "Ether Acceleration"
    assert merged[0].state is RecordAssemblyState.COMPLETE
    assert "ITEM_TYPE_MISSING" not in merged[0].reasons
    assert merged[0].field_details["item_type"]["status"] == "ALLOCATED"
    assert merged[0].field_details["item_type"]["direct_observation"] is False
