from __future__ import annotations

from ocring.ocr.assembler import assemble_candidate_records
from ocring.ocr.auto_store import AutoStoreDisposition, evaluate_auto_store_eligibility
from ocring.ocr.models import FieldKind, TemporalFieldAggregate, TemporalSupportState


def _agg(
    *,
    row_slot: int,
    field_kind: FieldKind,
    value: str,
    frames: tuple[str, ...],
    support_state: TemporalSupportState = TemporalSupportState.SUPPORTED,
    confidence: float = 0.9,
    text_quality_state: str = "AUTO_STORE_TRUSTWORTHY",
) -> TemporalFieldAggregate:
    row_ids = tuple(f"{frame_id}:row:{row_slot}" for frame_id in frames)
    return TemporalFieldAggregate(
        temporal_key=f"{row_slot}:{field_kind.value}:{value}",
        row_slot=row_slot,
        field_kind=field_kind,
        candidate_value=value,
        support_state=support_state,
        support_count=len(frames),
        independent_support_count=len(frames),
        best_confidence=confidence,
        contributing_frame_ids=frames,
        contributing_row_ids=row_ids,
        contributing_crop_ids=tuple(f"crop-{frame_id}" for frame_id in frames),
        text_quality_state=text_quality_state if field_kind is FieldKind.ITEM_NAME else "",
    )


def _item_name_records(records) -> list[TemporalFieldAggregate]:
    return [record for record in records if FieldKind.ITEM_NAME in record.fields]


def test_same_row_slot_yields_multiple_temporally_distinct_records() -> None:
    # row_slot 2 hosts two different real items at two different times during
    # a scroll - exactly the kind of case observed in a real recorded
    # session where one screen row hosts dozens of distinct mods over time.
    aggregates = (
        _agg(row_slot=2, field_kind=FieldKind.ITEM_NAME, value="Item Alpha", frames=("frame-000001", "frame-000002", "frame-000003")),
        _agg(row_slot=2, field_kind=FieldKind.ITEM_NAME, value="Item Beta", frames=("frame-000050", "frame-000051", "frame-000052")),
    )

    records = assemble_candidate_records(aggregates, profile_id="defiance", temporal_identity_aware=True)

    assert len(records) == 2
    names = {record.fields[FieldKind.ITEM_NAME] for record in records}
    assert names == {"Item Alpha", "Item Beta"}
    identity_ids = {record.temporal_identity_id for record in records}
    assert len(identity_ids) == 2
    assert all(record.row_slot == 2 for record in records)


def test_repeated_identity_across_neighboring_frames_stays_one_record() -> None:
    # One continuous dwell on the same real item across many retained frames
    # must remain a single record, not fragment into duplicates.
    aggregate = _agg(
        row_slot=4,
        field_kind=FieldKind.ITEM_NAME,
        value="Tight Guidance System IV",
        frames=("frame-000010", "frame-000011", "frame-000012", "frame-000013", "frame-000014"),
    )

    records = assemble_candidate_records((aggregate,), profile_id="defiance", temporal_identity_aware=True)

    assert len(records) == 1
    assert records[0].fields[FieldKind.ITEM_NAME] == "Tight Guidance System IV"
    assert records[0].support_summary["item_name"]["independent_support_count"] == 5


def test_different_identities_at_different_times_remain_separate_not_merged() -> None:
    aggregates = (
        _agg(row_slot=3, field_kind=FieldKind.ITEM_NAME, value="Reserve Chamber IV", frames=("frame-000001", "frame-000002")),
        _agg(row_slot=3, field_kind=FieldKind.ITEM_NAME, value="Sniper Rapid Mag V", frames=("frame-000200", "frame-000201")),
    )

    records = assemble_candidate_records(aggregates, profile_id="defiance", temporal_identity_aware=True)

    assert len(records) == 2
    values = sorted(record.fields[FieldKind.ITEM_NAME] for record in records)
    assert values == ["Reserve Chamber IV", "Sniper Rapid Mag V"]


def test_identical_names_from_distinct_physical_passages_are_not_collapsed() -> None:
    # A single temporal.py cluster ("Item Alpha") whose own contributing
    # frames span two disjoint time windows, with a genuinely different item
    # ("Item Beta") observed on the same row_slot strictly in between. This
    # must split into two separate "Item Alpha" records, not one merged
    # record and not a silent duplicate-collapse just because the name matches.
    alpha = _agg(
        row_slot=5,
        field_kind=FieldKind.ITEM_NAME,
        value="Item Alpha",
        frames=("frame-000001", "frame-000002", "frame-000003", "frame-000150", "frame-000151", "frame-000152"),
    )
    beta = _agg(
        row_slot=5,
        field_kind=FieldKind.ITEM_NAME,
        value="Item Beta",
        frames=("frame-000075", "frame-000076", "frame-000077"),
    )

    records = assemble_candidate_records((alpha, beta), profile_id="defiance", temporal_identity_aware=True)

    alpha_records = [record for record in records if record.fields.get(FieldKind.ITEM_NAME) == "Item Alpha"]
    beta_records = [record for record in records if record.fields.get(FieldKind.ITEM_NAME) == "Item Beta"]
    assert len(alpha_records) == 2, "the two Item Alpha passages must not be collapsed into one record"
    assert len(beta_records) == 1
    assert alpha_records[0].temporal_identity_id != alpha_records[1].temporal_identity_id
    # Each split Item Alpha epoch keeps its own frame-accurate support count
    # (3 frames each), not the original unsplit total of 6.
    assert {record.support_summary["item_name"]["independent_support_count"] for record in alpha_records} == {3}


def test_weak_single_frame_interloper_does_not_fragment_a_continuous_dwell() -> None:
    # Regression for a real defect found against a real recorded session:
    # a single garbled/transient (WEAK, one-frame) observation
    # sitting between two halves of one continuous, well-supported dwell must
    # NOT be treated as proof of a passage break. Only a SUPPORTED interloper
    # (itself corroborated across >=2 frames) counts as real evidence of a
    # different physical item having occupied the slot in between.
    mostly_continuous = _agg(
        row_slot=9,
        field_kind=FieldKind.ITEM_NAME,
        value="Sustained Power Muzzle V",
        frames=("frame-000403", "frame-000404", "frame-000405", "frame-000416", "frame-000428", "frame-000440"),
    )
    transient_misread = _agg(
        row_slot=9,
        field_kind=FieldKind.ITEM_NAME,
        value="garbled junk",
        frames=("frame-000423",),
        support_state=TemporalSupportState.WEAK,
    )

    records = assemble_candidate_records(
        (mostly_continuous, transient_misread), profile_id="defiance", temporal_identity_aware=True
    )

    muzzle_records = [record for record in records if record.fields.get(FieldKind.ITEM_NAME) == "Sustained Power Muzzle V"]
    assert len(muzzle_records) == 1, "a single WEAK interloper must not split a continuous dwell into two records"
    assert muzzle_records[0].support_summary["item_name"]["independent_support_count"] == 6


def test_fields_do_not_leak_across_temporal_identities() -> None:
    alpha_frames = ("frame-000001", "frame-000002", "frame-000003")
    beta_frames = ("frame-000100", "frame-000101", "frame-000102")
    aggregates = (
        _agg(row_slot=6, field_kind=FieldKind.ITEM_NAME, value="Item Alpha", frames=alpha_frames),
        _agg(row_slot=6, field_kind=FieldKind.ITEM_NAME, value="Item Beta", frames=beta_frames),
        # item_rarity evidence exists only during Alpha's window.
        _agg(row_slot=6, field_kind=FieldKind.ITEM_RARITY, value="Epic", frames=alpha_frames),
    )

    records = assemble_candidate_records(aggregates, profile_id="defiance", temporal_identity_aware=True)

    alpha_record = next(record for record in records if record.fields.get(FieldKind.ITEM_NAME) == "Item Alpha")
    beta_record = next(record for record in records if record.fields.get(FieldKind.ITEM_NAME) == "Item Beta")

    assert alpha_record.fields.get(FieldKind.ITEM_RARITY) == "Epic"
    # Beta must NOT inherit Alpha's rarity just because they share a row_slot.
    assert FieldKind.ITEM_RARITY not in beta_record.fields
    assert FieldKind.ITEM_RARITY in beta_record.missing_fields
    assert beta_record.field_details["item_rarity"]["status"] == "FIELD_NOT_VISIBLE"
    assert beta_record.field_details["item_rarity"]["raw_observation"] == ""


def test_live_single_screen_assembly_is_unchanged_by_default() -> None:
    # Two competing item_name aggregates for the same row_slot, as
    # temporal.py would produce for a live (non-recorded) screen where
    # allow_slot_reuse=False leaves them CONFLICTED. Without
    # temporal_identity_aware, this must still collapse to exactly one
    # record, exactly like the original single-record-per-slot behavior.
    aggregates = (
        _agg(row_slot=2, field_kind=FieldKind.ITEM_NAME, value="Item Alpha", frames=("frame-000001", "frame-000002"), support_state=TemporalSupportState.CONFLICTED),
        _agg(row_slot=2, field_kind=FieldKind.ITEM_NAME, value="Item Beta", frames=("frame-000003", "frame-000004"), support_state=TemporalSupportState.CONFLICTED),
    )

    default_records = assemble_candidate_records(aggregates, profile_id="defiance")
    explicit_legacy_records = assemble_candidate_records(aggregates, profile_id="defiance", temporal_identity_aware=False)

    assert len(default_records) == 1
    assert len(explicit_legacy_records) == 1
    assert default_records[0].row_slot == 2
    assert default_records[0].temporal_identity_id == "2"


def test_epoch_record_still_requires_temporal_stability_for_auto_store() -> None:
    weak_aggregate = _agg(
        row_slot=7,
        field_kind=FieldKind.ITEM_NAME,
        value="Barely Seen Mod",
        frames=("frame-000001",),
        support_state=TemporalSupportState.WEAK,
    )

    records = assemble_candidate_records((weak_aggregate,), profile_id="defiance", temporal_identity_aware=True)

    assert len(records) == 1
    assert records[0].fields[FieldKind.ITEM_NAME] == "UNKNOWN"
    decision = evaluate_auto_store_eligibility(_review_record_from(records[0]))
    assert decision.disposition is AutoStoreDisposition.HOLD_UNKNOWN
    assert decision.eligible is False


def test_epoch_record_still_requires_text_quality_gate_for_auto_store() -> None:
    garbled = _agg(
        row_slot=8,
        field_kind=FieldKind.ITEM_NAME,
        value="Garbld Reedeng",
        frames=("frame-000001", "frame-000002"),
        text_quality_state="STABLE_BUT_REVIEW_REQUIRED",
    )
    clean = _agg(
        row_slot=8,
        field_kind=FieldKind.ITEM_NAME,
        value="Clean Reading V",
        frames=("frame-000100", "frame-000101"),
        text_quality_state="AUTO_STORE_TRUSTWORTHY",
    )

    records = assemble_candidate_records((garbled, clean), profile_id="defiance", temporal_identity_aware=True)
    garbled_record = next(record for record in records if record.fields.get(FieldKind.ITEM_NAME) == "Garbld Reedeng")
    clean_record = next(record for record in records if record.fields.get(FieldKind.ITEM_NAME) == "Clean Reading V")

    garbled_decision = evaluate_auto_store_eligibility(_review_record_from(garbled_record))
    clean_decision = evaluate_auto_store_eligibility(_review_record_from(clean_record))

    assert garbled_decision.disposition is AutoStoreDisposition.NEEDS_REVIEW
    assert "TEXT_QUALITY_LOW_OR_UNCERTAIN" in garbled_decision.reasons
    # The clean epoch is missing rarity/type/count in this minimal fixture, so
    # it is NEEDS_REVIEW too (required-field gate) rather than auto-store
    # eligible - but critically not blocked by identity/text-quality, proving
    # the two gates are independent of each other.
    assert "TEXT_QUALITY_LOW_OR_UNCERTAIN" not in clean_decision.reasons


class _ReviewRecordShim:
    """Minimal stand-in exposing exactly what evaluate_auto_store_eligibility reads."""

    def __init__(self, record) -> None:
        self.fields = {key.value: value for key, value in record.fields.items()}
        self.field_details = dict(record.field_details)
        self.support_summary = dict(record.support_summary)
        self.reasons = list(record.reasons)
        self.source_frame_ids = list(record.source_frame_ids)
        self.source_row_ids = list(record.source_row_ids)
        self.required_fields = tuple(field.value for field in (FieldKind.ITEM_NAME,))
        self.missing_fields = tuple(field.value for field in record.missing_fields)


def _review_record_from(record):
    return _ReviewRecordShim(record)
