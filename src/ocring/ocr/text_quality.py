from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum
from statistics import mean


class TextQualityState(str, Enum):
    TRUSTWORTHY = "AUTO_STORE_TRUSTWORTHY"
    LOW_OR_UNCERTAIN = "STABLE_BUT_REVIEW_REQUIRED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


# Evidence-property floors, not word/dictionary checks. Calibrated against a
# real preserved recording: every genuinely clean auto-saved
# reading in that recording measured mean_confidence >= 0.70 and
# preprocess_agreement >= 0.90, while the one reproducibly-garbled reading
# ("Aaie Baid Maay") measured mean_confidence ~0.47 and preprocess_agreement
# ~0.75. These floors sit with margin on the low side of "clean" and above the
# one observed "garbled" case, without being fit to any single example.
MIN_MEAN_CONFIDENCE = 0.60
MIN_PREPROCESS_AGREEMENT = 0.80
MIN_CROSS_FRAME_AGREEMENT = 0.60


@dataclass(frozen=True)
class FrameTextObservation:
    """One contributing frame's collapsed observation of an item-name field.

    `variant_values` holds every preprocess-variant raw reading examined for
    that single frame/row (winner first) - the same evidence already produced
    by OCR, not re-derived or corrected. A frame with only one recorded
    variant is not penalized (nothing to disagree with).
    """

    frame_id: str
    winner_value: str
    winner_confidence: float
    variant_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class TextQualityAssessment:
    state: TextQualityState
    score: float
    mean_confidence: float
    min_confidence: float
    confidence_spread: float
    cross_frame_agreement: float
    preprocess_agreement: float
    reasons: tuple[str, ...]


def assess_item_name_text_quality(
    observations: tuple[FrameTextObservation, ...],
) -> TextQualityAssessment:
    """Score whether a temporally-stable item-name reading is textually trustworthy.

    This gate never inspects candidate text against a dictionary, word list, or
    reference catalogue, and never corrects or replaces the observed text. It
    measures only observable OCR/evidence properties: confidence level and
    spread across the independent frames that already satisfied
    `independent_support_count >= 2`, how closely those frames agree with each
    other, and how closely each frame's own preprocess variants agree with
    each other. An unusual but consistently, confidently, and identically
    read name scores exactly the same as a common one - only agreement and
    confidence are measured, never plausibility of the string itself.

    This is deliberately a *second* gate: it does not change, weaken, or
    replace `independent_support_count >= 2` or `TemporalSupportState`, and it
    is the caller's responsibility to only invoke it on observations that
    already passed temporal stability.
    """
    if not observations:
        return TextQualityAssessment(
            state=TextQualityState.NOT_APPLICABLE,
            score=0.0,
            mean_confidence=0.0,
            min_confidence=0.0,
            confidence_spread=0.0,
            cross_frame_agreement=0.0,
            preprocess_agreement=0.0,
            reasons=("NO_OBSERVATIONS",),
        )

    confidences = tuple(observation.winner_confidence for observation in observations)
    mean_confidence = mean(confidences)
    min_confidence = min(confidences)
    confidence_spread = max(confidences) - min_confidence

    cross_frame_agreement = _mean_pairwise_ratio(tuple(observation.winner_value for observation in observations))

    per_frame_preprocess_agreement = tuple(
        _mean_pairwise_ratio(observation.variant_values) if len(observation.variant_values) > 1 else 1.0
        for observation in observations
    )
    preprocess_agreement = mean(per_frame_preprocess_agreement)

    score = mean((mean_confidence, cross_frame_agreement, preprocess_agreement))

    reasons: list[str] = []
    if mean_confidence < MIN_MEAN_CONFIDENCE:
        reasons.append("MEAN_CONFIDENCE_BELOW_FLOOR")
    if cross_frame_agreement < MIN_CROSS_FRAME_AGREEMENT:
        reasons.append("CROSS_FRAME_TEXT_AGREEMENT_BELOW_FLOOR")
    if preprocess_agreement < MIN_PREPROCESS_AGREEMENT:
        reasons.append("PREPROCESS_AGREEMENT_BELOW_FLOOR")

    state = TextQualityState.LOW_OR_UNCERTAIN if reasons else TextQualityState.TRUSTWORTHY
    return TextQualityAssessment(
        state=state,
        score=score,
        mean_confidence=mean_confidence,
        min_confidence=min_confidence,
        confidence_spread=confidence_spread,
        cross_frame_agreement=cross_frame_agreement,
        preprocess_agreement=preprocess_agreement,
        reasons=tuple(reasons),
    )


def _mean_pairwise_ratio(values: tuple[str, ...]) -> float:
    cleaned = tuple(value.strip().casefold() for value in values)
    if len(cleaned) < 2:
        return 1.0
    ratios = [
        SequenceMatcher(None, cleaned[i], cleaned[j]).ratio()
        for i in range(len(cleaned))
        for j in range(i + 1, len(cleaned))
    ]
    return mean(ratios)
