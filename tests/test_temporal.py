from __future__ import annotations

from ocring.ocr.models import CandidateDecision, FieldKind, PreprocessVariant, RankedFieldCandidate, TemporalSupportState
from ocring.ocr.temporal import merge_ranked_candidates


def test_same_frame_preprocess_variants_count_as_one_source_observation() -> None:
    candidates = (
        RankedFieldCandidate(
            row_id="frame-1:row:5",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="SHELDGRENADES SPIKESSTIMS",
            source_crop_id="sharpened-crop",
            source_variant=PreprocessVariant.SHARPENED,
            source_engine="rapidocr",
            decision=CandidateDecision.SELECTED,
            confidence=0.91,
            reasons=("REFERENCE_DATA_MISSING",),
        ),
        RankedFieldCandidate(
            row_id="frame-1:row:5",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="SHELDGRENADES SPIKESSTIMS",
            source_crop_id="grayscale-crop",
            source_variant=PreprocessVariant.GRAYSCALE,
            source_engine="rapidocr",
            decision=CandidateDecision.SECONDARY,
            confidence=0.89,
            reasons=("REFERENCE_DATA_MISSING",),
        ),
    )

    aggregates = merge_ranked_candidates(candidates)

    assert len(aggregates) == 1
    assert aggregates[0].support_state is TemporalSupportState.WEAK
    assert aggregates[0].support_count == 1
    assert aggregates[0].independent_support_count == 1
    assert aggregates[0].contributing_crop_ids == ("sharpened-crop", "grayscale-crop")
    assert "PREPROCESS_VARIANTS_COLLAPSED" in aggregates[0].reasons


def test_stable_observed_item_name_preserves_missing_reference_status() -> None:
    candidates = (
        RankedFieldCandidate(
            row_id="frame-1:row:8",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Scatter Scope V",
            source_crop_id="crop-1",
            source_variant=PreprocessVariant.HIGH_CONTRAST,
            source_engine="rapidocr",
            decision=CandidateDecision.SELECTED,
            confidence=0.704,
            reasons=("REFERENCE_DATA_MISSING",),
        ),
        RankedFieldCandidate(
            row_id="frame-2:row:8",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Scatter Scope V",
            source_crop_id="crop-2",
            source_variant=PreprocessVariant.HIGH_CONTRAST,
            source_engine="rapidocr",
            decision=CandidateDecision.SELECTED,
            confidence=0.683,
            reasons=("REFERENCE_DATA_MISSING",),
        ),
    )

    aggregates = merge_ranked_candidates(candidates)

    assert len(aggregates) == 1
    assert aggregates[0].candidate_value == "Scatter Scope V"
    assert aggregates[0].support_state is TemporalSupportState.SUPPORTED
    assert aggregates[0].independent_support_count == 2
    assert "REFERENCE_DATA_MISSING" in aggregates[0].reasons


def test_near_identical_cross_frame_ocr_groups_without_synthesizing_spelling() -> None:
    candidates = (
        RankedFieldCandidate(
            row_id="frame-1:row:8",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Scatter Scope V",
            source_crop_id="crop-1",
            source_variant=PreprocessVariant.HIGH_CONTRAST,
            source_engine="rapidocr",
            decision=CandidateDecision.SELECTED,
            confidence=0.704,
            reasons=("REFERENCE_DATA_MISSING",),
        ),
        RankedFieldCandidate(
            row_id="frame-2:row:8",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Scater scope V",
            source_crop_id="crop-2",
            source_variant=PreprocessVariant.SHARPENED,
            source_engine="rapidocr",
            decision=CandidateDecision.SELECTED,
            confidence=0.692,
            reasons=("REFERENCE_DATA_MISSING",),
        ),
        RankedFieldCandidate(
            row_id="frame-3:row:8",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Scatter Scope V",
            source_crop_id="crop-3",
            source_variant=PreprocessVariant.GRAYSCALE,
            source_engine="rapidocr",
            decision=CandidateDecision.SELECTED,
            confidence=0.686,
            reasons=("REFERENCE_DATA_MISSING",),
        ),
    )

    aggregates = merge_ranked_candidates(candidates)

    assert len(aggregates) == 1
    assert aggregates[0].candidate_value == "Scatter Scope V"
    assert aggregates[0].support_state is TemporalSupportState.SUPPORTED
    assert aggregates[0].independent_support_count == 3
    assert "OBSERVED_IDENTITY_CLUSTERED" in aggregates[0].reasons


def test_materially_conflicting_item_names_remain_conflicted() -> None:
    candidates = (
        RankedFieldCandidate(
            row_id="frame-1:row:8",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Scatter Scope V",
            source_crop_id="crop-1",
            source_variant=PreprocessVariant.HIGH_CONTRAST,
            source_engine="rapidocr",
            decision=CandidateDecision.SELECTED,
            confidence=0.704,
            reasons=("REFERENCE_DATA_MISSING",),
        ),
        RankedFieldCandidate(
            row_id="frame-2:row:8",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Shotgun Hip Spread V",
            source_crop_id="crop-2",
            source_variant=PreprocessVariant.HIGH_CONTRAST,
            source_engine="rapidocr",
            decision=CandidateDecision.SELECTED,
            confidence=0.892,
            reasons=("REFERENCE_DATA_MISSING",),
        ),
    )

    aggregates = merge_ranked_candidates(candidates)

    assert len(aggregates) == 2
    assert {aggregate.support_state for aggregate in aggregates} == {TemporalSupportState.CONFLICTED}
    assert all("TEMPORAL_VALUE_CONFLICT" in aggregate.reasons for aggregate in aggregates)


def test_same_frame_near_identical_preprocess_variants_still_count_once() -> None:
    candidates = (
        RankedFieldCandidate(
            row_id="frame-1:row:8",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Scatter Scope V",
            source_crop_id="crop-1",
            source_variant=PreprocessVariant.HIGH_CONTRAST,
            source_engine="rapidocr",
            decision=CandidateDecision.SELECTED,
            confidence=0.704,
            reasons=("REFERENCE_DATA_MISSING",),
        ),
        RankedFieldCandidate(
            row_id="frame-1:row:8",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Scater scope V",
            source_crop_id="crop-2",
            source_variant=PreprocessVariant.SHARPENED,
            source_engine="rapidocr",
            decision=CandidateDecision.SECONDARY,
            confidence=0.692,
            reasons=("REFERENCE_DATA_MISSING",),
        ),
    )

    aggregates = merge_ranked_candidates(candidates)

    assert len(aggregates) == 1
    assert aggregates[0].support_state is TemporalSupportState.WEAK
    assert aggregates[0].support_count == 1
    assert aggregates[0].independent_support_count == 1
    assert "PREPROCESS_VARIANTS_COLLAPSED" in aggregates[0].reasons


def test_leading_single_character_ocr_junk_does_not_split_stable_identity_cluster() -> None:
    candidates = (
        RankedFieldCandidate(
            row_id="frame-1:row:10",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Shotgun Hip Spread V",
            source_crop_id="crop-1",
            source_variant=PreprocessVariant.HIGH_CONTRAST,
            source_engine="rapidocr",
            decision=CandidateDecision.SELECTED,
            confidence=0.892,
            reasons=("REFERENCE_DATA_MISSING",),
        ),
        RankedFieldCandidate(
            row_id="frame-2:row:10",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value='6",Shotgun Hip Spread V',
            source_crop_id="crop-2",
            source_variant=PreprocessVariant.SHARPENED,
            source_engine="rapidocr",
            decision=CandidateDecision.SECONDARY,
            confidence=0.838,
            reasons=("REFERENCE_DATA_MISSING",),
        ),
        RankedFieldCandidate(
            row_id="frame-3:row:10",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="e Shotgun Hip Spread V",
            source_crop_id="crop-3",
            source_variant=PreprocessVariant.GRAYSCALE,
            source_engine="rapidocr",
            decision=CandidateDecision.SECONDARY,
            confidence=0.808,
            reasons=("REFERENCE_DATA_MISSING",),
        ),
    )

    aggregates = merge_ranked_candidates(candidates)

    assert len(aggregates) == 1
    assert aggregates[0].candidate_value == "Shotgun Hip Spread V"
    assert aggregates[0].support_state is TemporalSupportState.SUPPORTED
    assert aggregates[0].independent_support_count == 3
