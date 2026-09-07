from __future__ import annotations

from ocring.ocr.models import CandidateStatus, FieldKind, OcrAttempt, OcrEngineStatus, PreprocessVariant
from ocring.ocr.normalize import build_field_candidates


def test_build_field_candidates_normalizes_count_value() -> None:
    attempts = (
        OcrAttempt(
            crop_id="crop-1",
            row_id="row-1",
            field_kind=FieldKind.ITEM_COUNT,
            variant=PreprocessVariant.HIGH_CONTRAST,
            engine_name="test",
            status=OcrEngineStatus.OK,
            raw_text="x 12",
            normalized_text="x 12",
            confidence=0.8,
        ),
    )

    candidates = build_field_candidates(attempts, profile_id="defiance")

    assert len(candidates) == 1
    assert candidates[0].candidate_value == "12"
    assert candidates[0].status is CandidateStatus.CANDIDATE


def test_build_field_candidates_normalizes_rarity_numeral() -> None:
    attempts = (
        OcrAttempt(
            crop_id="crop-2",
            row_id="row-2",
            field_kind=FieldKind.ITEM_RARITY,
            variant=PreprocessVariant.GRAYSCALE,
            engine_name="test",
            status=OcrEngineStatus.OK,
            raw_text="IV",
            normalized_text="IV",
            confidence=0.7,
        ),
    )

    candidates = build_field_candidates(attempts, profile_id="defiance")

    assert candidates[0].candidate_value == "Tier IV"
    assert candidates[0].status is CandidateStatus.CANDIDATE


def test_build_field_candidates_marks_unavailable_when_ocr_missing() -> None:
    attempts = (
        OcrAttempt(
            crop_id="crop-3",
            row_id="row-3",
            field_kind=FieldKind.ITEM_NAME,
            variant=PreprocessVariant.SHARPENED,
            engine_name="unavailable",
            status=OcrEngineStatus.UNAVAILABLE,
            raw_text="",
            normalized_text="",
            confidence=0.0,
            reasons=("NO_LOCAL_OCR_ENGINE",),
        ),
    )

    candidates = build_field_candidates(attempts, profile_id="defiance")

    assert candidates[0].status is CandidateStatus.UNAVAILABLE
    assert "NO_LOCAL_OCR_ENGINE" in candidates[0].reasons


def test_build_field_candidates_strips_synergy_prefix_without_inventing_value() -> None:
    attempts = (
        OcrAttempt(
            crop_id="crop-4",
            row_id="row-4",
            field_kind=FieldKind.ITEM_SYNERGY,
            variant=PreprocessVariant.HIGH_CONTRAST,
            engine_name="test",
            status=OcrEngineStatus.OK,
            raw_text="Synergy: Sol's Prominence",
            normalized_text="Synergy: Sol's Prominence",
            confidence=0.93,
        ),
    )

    candidates = build_field_candidates(attempts, profile_id="defiance")

    assert candidates[0].candidate_value == "Sol's Prominence"
    assert candidates[0].status is CandidateStatus.CANDIDATE
