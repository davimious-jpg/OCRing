from __future__ import annotations

from ocring.ocr.models import CandidateDecision, CandidateStatus, FieldCandidate, FieldKind, PreprocessVariant
from ocring.ocr.ranking import rank_field_candidates


def test_rank_field_candidates_selects_best_valid_defiance_candidate() -> None:
    candidates = (
        FieldCandidate(
            crop_id="crop-a",
            row_id="row-1",
            field_kind=FieldKind.ITEM_RARITY,
            candidate_value="Tier IV",
            source_variant=PreprocessVariant.HIGH_CONTRAST,
            source_engine="test",
            status=CandidateStatus.CANDIDATE,
            confidence=0.8,
        ),
        FieldCandidate(
            crop_id="crop-b",
            row_id="row-1",
            field_kind=FieldKind.ITEM_RARITY,
            candidate_value="Tier X",
            source_variant=PreprocessVariant.GRAYSCALE,
            source_engine="test",
            status=CandidateStatus.CANDIDATE,
            confidence=0.9,
        ),
    )

    ranked = rank_field_candidates(candidates, profile_id="defiance")

    selected = [candidate for candidate in ranked if candidate.decision is CandidateDecision.SELECTED]
    rejected = [candidate for candidate in ranked if candidate.decision is CandidateDecision.REJECTED]
    assert len(selected) == 1
    assert selected[0].candidate_value == "Tier IV"
    assert len(rejected) == 1
    assert "RARITY_NOT_ALLOWED" in rejected[0].reasons


def test_rank_field_candidates_rejects_unknown_weapon_type() -> None:
    candidates = (
        FieldCandidate(
            crop_id="crop-c",
            row_id="row-2",
            field_kind=FieldKind.ITEM_TYPE,
            candidate_value="Laser Harp",
            source_variant=PreprocessVariant.HIGH_CONTRAST,
            source_engine="test",
            status=CandidateStatus.CANDIDATE,
            confidence=0.7,
        ),
    )

    ranked = rank_field_candidates(candidates, profile_id="defiance")

    assert ranked[0].decision is CandidateDecision.REJECTED
    assert "WEAPON_TYPE_NOT_ALLOWED" in ranked[0].reasons


def test_rank_field_candidates_accepts_detail_panel_mod_slot_type() -> None:
    candidates = (
        FieldCandidate(
            crop_id="crop-detail-type",
            row_id="row-11",
            field_kind=FieldKind.ITEM_TYPE,
            candidate_value="Barrel",
            source_variant=PreprocessVariant.HIGH_CONTRAST,
            source_engine="test",
            status=CandidateStatus.CANDIDATE,
            confidence=0.82,
        ),
    )

    ranked = rank_field_candidates(candidates, profile_id="defiance")

    assert ranked[0].decision is CandidateDecision.SELECTED
    assert "WEAPON_TYPE_NOT_ALLOWED" not in ranked[0].reasons


def test_rank_field_candidates_preserves_reference_data_missing_for_plausible_item_name() -> None:
    candidates = (
        FieldCandidate(
            crop_id="crop-d",
            row_id="row-6",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Cyber Rig Charge",
            source_variant=PreprocessVariant.HIGH_CONTRAST,
            source_engine="test",
            status=CandidateStatus.CANDIDATE,
            confidence=0.81,
        ),
    )

    ranked = rank_field_candidates(candidates, profile_id="defiance")

    assert ranked[0].decision is CandidateDecision.SELECTED
    assert "REFERENCE_DATA_MISSING" in ranked[0].reasons


def test_rank_field_candidates_preserves_reference_data_missing_for_visible_unknown_synergy() -> None:
    candidates = (
        FieldCandidate(
            crop_id="crop-synergy",
            row_id="row-12",
            field_kind=FieldKind.ITEM_SYNERGY,
            candidate_value="Sol's Prominence",
            source_variant=PreprocessVariant.HIGH_CONTRAST,
            source_engine="test",
            status=CandidateStatus.CANDIDATE,
            confidence=0.91,
        ),
    )

    ranked = rank_field_candidates(candidates, profile_id="defiance")

    assert ranked[0].decision is CandidateDecision.SELECTED
    assert "REFERENCE_DATA_MISSING" in ranked[0].reasons


def test_rank_field_candidates_still_rejects_implausible_unknown_item_name() -> None:
    candidates = (
        FieldCandidate(
            crop_id="crop-e",
            row_id="row-10",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="ASi7",
            source_variant=PreprocessVariant.HIGH_CONTRAST,
            source_engine="test",
            status=CandidateStatus.CANDIDATE,
            confidence=0.46,
        ),
    )

    ranked = rank_field_candidates(candidates, profile_id="defiance")

    assert ranked[0].decision is CandidateDecision.REJECTED
    assert "ITEM_NAME_UNKNOWN_TOKENS" in ranked[0].reasons


def test_item_name_ranking_prefers_complete_roman_ark_variant_over_slight_confidence_edge() -> None:
    candidates = (
        FieldCandidate(
            crop_id="crop-high-contrast",
            row_id="session-52571336-frame-000026:row:3",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Rebel Charger ARK",
            source_variant=PreprocessVariant.HIGH_CONTRAST,
            source_engine="rapidocr",
            status=CandidateStatus.CANDIDATE,
            confidence=0.904,
        ),
        FieldCandidate(
            crop_id="crop-grayscale",
            row_id="session-52571336-frame-000026:row:3",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="Rebel Charger V ARK",
            source_variant=PreprocessVariant.GRAYSCALE,
            source_engine="rapidocr",
            status=CandidateStatus.CANDIDATE,
            confidence=0.885,
        ),
    )

    ranked = rank_field_candidates(candidates, profile_id="defiance")

    selected = [candidate for candidate in ranked if candidate.decision is CandidateDecision.SELECTED]
    assert len(selected) == 1
    assert selected[0].candidate_value == "Rebel Charger V ARK"


def test_item_name_ranking_penalizes_glued_mixed_case_artifacts_without_rewriting() -> None:
    candidates = (
        FieldCandidate(
            crop_id="crop-glued",
            row_id="session-52571336-frame-000026:row:1",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="AMenclad RelpaderVARK",
            source_variant=PreprocessVariant.GRAYSCALE,
            source_engine="rapidocr",
            status=CandidateStatus.CANDIDATE,
            confidence=0.607,
        ),
        FieldCandidate(
            crop_id="crop-spaced",
            row_id="session-52571336-frame-000026:row:1",
            field_kind=FieldKind.ITEM_NAME,
            candidate_value="AMnclad Reloade ARK",
            source_variant=PreprocessVariant.HIGH_CONTRAST,
            source_engine="rapidocr",
            status=CandidateStatus.CANDIDATE,
            confidence=0.541,
        ),
    )

    ranked = rank_field_candidates(candidates, profile_id="defiance")

    selected = [candidate for candidate in ranked if candidate.decision is CandidateDecision.SELECTED]
    assert len(selected) == 1
    assert selected[0].candidate_value == "AMnclad Reloade ARK"
