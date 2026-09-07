from __future__ import annotations

from ocring.ocr.text_quality import (
    FrameTextObservation,
    TextQualityState,
    assess_item_name_text_quality,
)


def test_clean_repeated_ocr_is_trustworthy() -> None:
    observations = (
        FrameTextObservation(
            frame_id="frame-1",
            winner_value="Tight Guidance System IV",
            winner_confidence=0.86,
            variant_values=(
                "Tight Guidance System IV",
                "Tight Guidance System IV",
                "Tight Guidance System IV",
            ),
        ),
        FrameTextObservation(
            frame_id="frame-2",
            winner_value="Tight Guidance System IV",
            winner_confidence=0.94,
            variant_values=(
                "Tight Guidance System IV",
                "Tight Guidance System IV",
                "Tight Guidance System IV",
            ),
        ),
        FrameTextObservation(
            frame_id="frame-3",
            winner_value="Tight Guidance System IV",
            winner_confidence=0.90,
            variant_values=(
                "Tight Guidance System IV",
                "Tight Guidance System IV",
                "Tight Guidance System IV",
            ),
        ),
    )

    assessment = assess_item_name_text_quality(observations)

    assert assessment.state is TextQualityState.TRUSTWORTHY
    assert assessment.reasons == ()


def test_repeatable_garbled_ocr_is_temporally_stable_but_flagged_low_quality() -> None:
    # Modeled directly on real preserved recording evidence for the "Aaie Baid
    # Maay" reading: low, inconsistent confidence and disagreeing
    # preprocess variants within each frame, even though the winning reading
    # repeats closely enough across frames to already satisfy
    # independent_support_count >= 2 upstream.
    observations = (
        FrameTextObservation(
            frame_id="frame-1",
            winner_value="Aaie Baid Maa",
            winner_confidence=0.4835,
            variant_values=("AaieidM", "AaiiMa", "Aaie Baid Maa"),
        ),
        FrameTextObservation(
            frame_id="frame-2",
            winner_value="Aaie Baid Maay",
            winner_confidence=0.4632,
            variant_values=("Aaie Baid Maay", "AaiaiMay", "Aaie Baid Maay"),
        ),
        FrameTextObservation(
            frame_id="frame-3",
            winner_value="Aaie Baid Maay",
            winner_confidence=0.4530,
            variant_values=("Aaie Baid Maay", "Aai iy", "Aai aid Maay"),
        ),
    )

    assessment = assess_item_name_text_quality(observations)

    assert assessment.state is TextQualityState.LOW_OR_UNCERTAIN
    assert "MEAN_CONFIDENCE_BELOW_FLOOR" in assessment.reasons
    assert "PREPROCESS_AGREEMENT_BELOW_FLOOR" in assessment.reasons
    # The candidate text itself is never inspected or referenced by the gate.
    assert not any("Aaie" in reason or "Maay" in reason for reason in assessment.reasons)


def test_unusual_but_consistently_high_quality_name_is_not_penalized() -> None:
    # A legitimate item name can look nothing like an English phrase. The gate
    # must judge only agreement/confidence, never word-plausibility.
    observations = (
        FrameTextObservation(
            frame_id="frame-1",
            winner_value="Xhk'zzorath Emitter IX",
            winner_confidence=0.91,
            variant_values=(
                "Xhk'zzorath Emitter IX",
                "Xhk'zzorath Emitter IX",
                "Xhk'zzorath Emitter IX",
            ),
        ),
        FrameTextObservation(
            frame_id="frame-2",
            winner_value="Xhk'zzorath Emitter IX",
            winner_confidence=0.88,
            variant_values=(
                "Xhk'zzorath Emitter IX",
                "Xhk'zzorath Emitter IX",
                "Xhk'zzorath Emitter IX",
            ),
        ),
    )

    assessment = assess_item_name_text_quality(observations)

    assert assessment.state is TextQualityState.TRUSTWORTHY
    assert assessment.reasons == ()


def test_alternating_materially_different_strings_is_flagged() -> None:
    # Same evidence, but the frames disagree with each other on the actual
    # text even though each frame is individually confident and internally
    # consistent across its own preprocess variants.
    observations = (
        FrameTextObservation(
            frame_id="frame-1",
            winner_value="Scatter Scope V",
            winner_confidence=0.85,
            variant_values=("Scatter Scope V", "Scatter Scope V", "Scatter Scope V"),
        ),
        FrameTextObservation(
            frame_id="frame-2",
            winner_value="Shotgun Hip Spread V",
            winner_confidence=0.85,
            variant_values=("Shotgun Hip Spread V", "Shotgun Hip Spread V", "Shotgun Hip Spread V"),
        ),
    )

    assessment = assess_item_name_text_quality(observations)

    assert assessment.state is TextQualityState.LOW_OR_UNCERTAIN
    assert "CROSS_FRAME_TEXT_AGREEMENT_BELOW_FLOOR" in assessment.reasons


def test_gate_takes_no_reference_or_dictionary_input() -> None:
    # The function signature itself proves no reference/dictionary data can be
    # consulted: it accepts only frame-level OCR evidence.
    import inspect

    signature = inspect.signature(assess_item_name_text_quality)
    assert list(signature.parameters) == ["observations"]


def test_no_observations_is_not_applicable_not_trustworthy() -> None:
    assessment = assess_item_name_text_quality(())

    assert assessment.state is TextQualityState.NOT_APPLICABLE
